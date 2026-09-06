import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ragops.contracts import DocumentEmbedding, IndexVersionSpec
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.embeddings import (
    SqlAlchemyEmbeddingRepository,
    SqlAlchemyIndexVersionRepository,
)
from ragops.persistence.models import CorpusVersionRow, DatasetRow, DocumentRow


def test_embedding_contract_enforces_v1_dimension() -> None:
    with pytest.raises(ValidationError, match="exactly 384"):
        DocumentEmbedding(
            document_id=uuid4(),
            index_version_id=uuid4(),
            values=(0.0,),
        )


def test_embedding_batches_are_resumable() -> None:
    async def exercise_repository() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        sessions = create_session_factory(engine)
        async with sessions.begin() as session:
            dataset = DatasetRow(
                name="scifact",
                version="1.0",
                split="test",
                license_name="CC BY-NC 2.0",
            )
            session.add(dataset)
            await session.flush()
            corpus = CorpusVersionRow(
                dataset_id=dataset.id,
                content_hash="c" * 64,
                document_count=1,
            )
            session.add(corpus)
            await session.flush()
            document = DocumentRow(
                corpus_version_id=corpus.id,
                external_id="doc-1",
                title="A document",
                text="Evidence",
            )
            session.add(document)
            await session.flush()

            indexes = SqlAlchemyIndexVersionRepository(session)
            index = await indexes.create(
                IndexVersionSpec(
                    dataset_id=dataset.id,
                    corpus_version_id=corpus.id,
                    corpus_hash=corpus.content_hash,
                    configuration_hash="i" * 64,
                    embedding_model="BAAI/bge-small-en-v1.5",
                    dimension=384,
                    normalized=True,
                    hnsw_parameters={"m": 16, "ef_construction": 64},
                    bm25_artifact_hash="b" * 64,
                    total_document_count=1,
                )
            )
            embedding = DocumentEmbedding(
                document_id=document.id,
                index_version_id=index.id,
                values=tuple([0.0] * 383 + [1.0]),
            )
            repository = SqlAlchemyEmbeddingRepository(session)

            assert await repository.add_missing([embedding]) == 1
            assert await repository.add_missing([embedding]) == 0
            assert await repository.count(index.id) == 1
            assert await repository.get_for_documents(index.id, [document.id]) == {
                document.id: embedding.values
            }

        await engine.dispose()

    asyncio.run(exercise_repository())
