"""Database access required by online retrieval."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.contracts import IndexBuildState, IndexVersion, PersistedDocument
from ragops.persistence.embeddings import index_version_contract
from ragops.persistence.models import DatasetRow, DocumentEmbeddingRow, DocumentRow, IndexVersionRow
from ragops.retrieval.errors import (
    CompatibleIndexNotFoundError,
    DatasetNotIngestedError,
)
from ragops.retrieval.types import StageHit


def dense_search_statement(
    index_version_id: UUID, query_embedding: Sequence[float], *, k: int
) -> Select[tuple[str, float]]:
    distance = DocumentEmbeddingRow.embedding.cosine_distance(list(query_embedding)).label(
        "distance"
    )
    return (
        select(DocumentRow.external_id, distance)
        .join(DocumentEmbeddingRow, DocumentEmbeddingRow.document_id == DocumentRow.id)
        .where(DocumentEmbeddingRow.index_version_id == index_version_id)
        .order_by(distance, DocumentRow.external_id)
        .limit(k)
    )


class SearchDataStore(Protocol):
    async def resolve_index(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        split: str,
        embedding_model: str | None,
    ) -> IndexVersion: ...

    async def dense_search(
        self, index_version_id: UUID, query_embedding: Sequence[float], *, k: int
    ) -> tuple[StageHit, ...]: ...

    async def load_documents(
        self, corpus_version_id: UUID, document_ids: Sequence[str]
    ) -> dict[str, PersistedDocument]: ...


class SqlAlchemySearchDataStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def resolve_index(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        split: str,
        embedding_model: str | None,
    ) -> IndexVersion:
        async with self._sessions() as session:
            dataset = await session.scalar(
                select(DatasetRow).where(
                    DatasetRow.name == dataset_name,
                    DatasetRow.version == dataset_version,
                    DatasetRow.split == split,
                )
            )
            if dataset is None:
                raise DatasetNotIngestedError(
                    f"dataset is not ingested: {dataset_name}/{dataset_version}/{split}"
                )
            conditions = [
                IndexVersionRow.dataset_id == dataset.id,
                IndexVersionRow.state == IndexBuildState.READY.value,
            ]
            if embedding_model is not None:
                conditions.append(IndexVersionRow.embedding_model == embedding_model)
            row = await session.scalar(
                select(IndexVersionRow)
                .where(*conditions)
                .order_by(IndexVersionRow.created_at.desc())
                .limit(1)
            )
            if row is None:
                model_detail = f" for embedding model {embedding_model}" if embedding_model else ""
                raise CompatibleIndexNotFoundError(
                    f"no ready index for {dataset_name}/{split}{model_detail}"
                )
            return index_version_contract(row)

    async def dense_search(
        self, index_version_id: UUID, query_embedding: Sequence[float], *, k: int
    ) -> tuple[StageHit, ...]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    dense_search_statement(index_version_id, query_embedding, k=k)
                )
            ).tuples()
            return tuple(
                StageHit(document_id=document_id, score=1.0 - float(distance))
                for document_id, distance in rows
            )

    async def load_documents(
        self, corpus_version_id: UUID, document_ids: Sequence[str]
    ) -> dict[str, PersistedDocument]:
        if not document_ids:
            return {}
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(DocumentRow).where(
                        DocumentRow.corpus_version_id == corpus_version_id,
                        DocumentRow.external_id.in_(document_ids),
                    )
                )
            ).all()
        documents = {
            row.external_id: PersistedDocument(
                id=row.id,
                external_id=row.external_id,
                title=row.title,
                text=row.text,
            )
            for row in rows
        }
        missing = set(document_ids) - documents.keys()
        if missing:
            raise ValueError(f"retrieval index references missing documents: {sorted(missing)}")
        return documents
