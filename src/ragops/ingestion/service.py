"""End-to-end, resumable dataset ingestion orchestration."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import DatasetManifest
from ragops.contracts import (
    DocumentEmbedding,
    IndexVersion,
    IndexVersionSpec,
    IngestionResult,
    PersistedDocument,
)
from ragops.ingestion.artifacts import SparseIndexBuilder
from ragops.ingestion.embedders import DocumentEmbedder
from ragops.ingestion.hashing import hash_dataset, hash_json
from ragops.ingestion.loader import load_beir_dataset
from ragops.ingestion.repository import IngestionRepository, validate_persisted_counts
from ragops.ingestion.sources import materialize_dataset
from ragops.persistence.embeddings import (
    SqlAlchemyEmbeddingRepository,
    SqlAlchemyIndexVersionRepository,
)


def _batches[T](values: Sequence[T], size: int) -> list[Sequence[T]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    return [values[offset : offset + size] for offset in range(0, len(values), size)]


class IngestionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        download_root: Path,
        artifact_root: Path,
        sparse_index_builder: SparseIndexBuilder,
    ) -> None:
        self._sessions = sessions
        self._download_root = download_root
        self._artifact_root = artifact_root
        self._sparse_index_builder = sparse_index_builder

    async def ingest(
        self,
        *,
        name: str,
        manifest: DatasetManifest,
        embedder: DocumentEmbedder,
        split: str | None = None,
        write_batch_size: int = 500,
        embedding_batch_size: int = 64,
    ) -> IngestionResult:
        if embedder.dimension != 384:
            raise ValueError("v1 ingestion requires exactly 384 embedding dimensions")
        selected_split = split or manifest.default_split
        source_directory = await asyncio.to_thread(
            materialize_dataset, name, manifest, self._download_root
        )
        dataset = await asyncio.to_thread(load_beir_dataset, source_directory, split=selected_split)
        corpus_hash = hash_dataset(dataset)

        async with self._sessions.begin() as session:
            repository = IngestionRepository(session)
            dataset_row = await repository.get_or_create_dataset(
                name=name,
                version=manifest.version,
                split=selected_split,
                license_name=manifest.license_name,
            )
            corpus_row = await repository.get_or_create_corpus(
                dataset_id=dataset_row.id,
                content_hash=corpus_hash,
                document_count=len(dataset.documents),
            )
            dataset_id = dataset_row.id
            corpus_version_id = corpus_row.id

        inserted_documents = await self._write_batches(
            dataset.documents,
            write_batch_size,
            lambda repository, batch: repository.add_documents(corpus_version_id, batch),
        )
        inserted_queries = await self._write_batches(
            dataset.queries,
            write_batch_size,
            lambda repository, batch: repository.add_queries(dataset_id, batch),
        )
        inserted_qrels = await self._write_batches(
            dataset.qrels,
            write_batch_size,
            lambda repository, batch: repository.add_qrels(
                dataset_id=dataset_id,
                corpus_version_id=corpus_version_id,
                qrels=batch,
            ),
        )

        async with self._sessions() as session:
            persisted = await IngestionRepository(session).load_corpus(
                dataset_id=dataset_id,
                corpus_version_id=corpus_version_id,
            )
        validate_persisted_counts(dataset, persisted)

        bm25_artifact = await asyncio.to_thread(
            self._sparse_index_builder.build,
            dataset.documents,
            self._artifact_root / "bm25",
        )
        index_configuration_hash = hash_json(
            {
                "corpus_hash": corpus_hash,
                "embedding_model": embedder.model_id,
                "dimension": embedder.dimension,
                "normalized": embedder.normalized,
                "hnsw": {"m": 16, "ef_construction": 64},
                "bm25_artifact_hash": bm25_artifact.content_hash,
            }
        )
        index_spec = IndexVersionSpec(
            dataset_id=dataset_id,
            corpus_version_id=corpus_version_id,
            corpus_hash=corpus_hash,
            configuration_hash=index_configuration_hash,
            embedding_model=embedder.model_id,
            dimension=384,
            normalized=embedder.normalized,
            hnsw_parameters={"m": 16, "ef_construction": 64},
            bm25_artifact_hash=bm25_artifact.content_hash,
            total_document_count=len(dataset.documents),
        )
        index_version = await self._get_or_create_index(index_spec)
        inserted_embeddings = await self._embed_missing(
            persisted.documents,
            index_version,
            embedder,
            embedding_batch_size,
        )
        async with self._sessions.begin() as session:
            index_version = await SqlAlchemyIndexVersionRepository(session).refresh_progress(
                index_version.id
            )

        return IngestionResult(
            dataset=name,
            split=selected_split,
            corpus_hash=corpus_hash,
            bm25_artifact=bm25_artifact,
            index_version=index_version,
            inserted_documents=inserted_documents,
            inserted_queries=inserted_queries,
            inserted_qrels=inserted_qrels,
            inserted_embeddings=inserted_embeddings,
        )

    async def _write_batches[T](
        self,
        values: Sequence[T],
        batch_size: int,
        write: Callable[[IngestionRepository, Sequence[T]], Awaitable[int]],
    ) -> int:
        inserted = 0
        for batch in _batches(values, batch_size):
            async with self._sessions.begin() as session:
                repository = IngestionRepository(session)
                inserted += await write(repository, batch)
        return inserted

    async def _get_or_create_index(self, spec: IndexVersionSpec) -> IndexVersion:
        async with self._sessions.begin() as session:
            repository = SqlAlchemyIndexVersionRepository(session)
            existing = await repository.get_by_configuration(
                spec.corpus_version_id, spec.configuration_hash
            )
            return existing if existing is not None else await repository.create(spec)

    async def _embed_missing(
        self,
        documents: Sequence[PersistedDocument],
        index_version: IndexVersion,
        embedder: DocumentEmbedder,
        batch_size: int,
    ) -> int:
        inserted = 0
        # Transformer inference pads every batch to its longest input. Stable
        # length bucketing avoids making thousands of short FiQA passages pay
        # the cost of an unrelated long passage while preserving resumability.
        embedding_order = sorted(
            documents,
            key=lambda document: (
                -(len(document.title) + len(document.text)),
                document.external_id,
            ),
        )
        for batch in _batches(embedding_order, batch_size):
            document_batch = list(batch)
            document_ids = [document.id for document in document_batch]
            async with self._sessions() as session:
                missing_ids = await SqlAlchemyEmbeddingRepository(session).missing_document_ids(
                    index_version.id, document_ids
                )
            missing = [document for document in document_batch if document.id in missing_ids]
            if not missing:
                continue
            texts = [f"{document.title}\n{document.text}" for document in missing]
            vectors = await embedder.encode_documents(texts)
            if len(vectors) != len(missing):
                raise ValueError("embedder returned a different number of vectors than documents")
            records = [
                DocumentEmbedding(
                    document_id=document.id,
                    index_version_id=index_version.id,
                    values=tuple(float(value) for value in vector),
                )
                for document, vector in zip(missing, vectors, strict=True)
            ]
            async with self._sessions.begin() as session:
                inserted_batch = await SqlAlchemyEmbeddingRepository(session).add_missing(records)
                inserted += inserted_batch
                await SqlAlchemyIndexVersionRepository(session).advance_progress(
                    index_version.id,
                    inserted_count=inserted_batch,
                )
        return inserted
