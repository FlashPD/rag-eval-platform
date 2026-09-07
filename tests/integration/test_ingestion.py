import asyncio
from collections.abc import Sequence
from pathlib import Path

import bm25s
import httpx
import pytest
from sqlalchemy import select

from ragops.api import create_app
from ragops.config import DatasetCatalog, LocalDatasetManifest, VariantRegistry
from ragops.contracts import (
    EvalRunSpec,
    EvalRunState,
    IndexBuildState,
    SparseStageConfig,
    VariantConfig,
)
from ragops.evaluation import run_retrieval_evaluation
from ragops.ingestion.artifacts import Bm25sIndexBuilder
from ragops.ingestion.service import IngestionService
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.models import EvalQueryResultRow
from ragops.retrieval.pipeline import RetrievalPipeline
from ragops.retrieval.sparse import Bm25sSparseRetriever
from ragops.retrieval.store import SqlAlchemySearchDataStore

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "fixtures" / "tiny-beir"


class DeterministicEmbedder:
    model_id = "test/deterministic-384"
    dimension = 384
    normalized = True

    async def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            vector[len(text) % self.dimension] = 1.0
            vectors.append(vector)
        return vectors


class InterruptingEmbedder(DeterministicEmbedder):
    def __init__(self) -> None:
        self.calls = 0

    async def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("simulated interruption")
        return await super().encode_documents(texts)


def test_ingestion_is_complete_and_resumable(tmp_path: Path) -> None:
    async def exercise_ingestion() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        service = IngestionService(
            create_session_factory(engine),
            download_root=tmp_path / "downloads",
            artifact_root=tmp_path / "artifacts",
            sparse_index_builder=Bm25sIndexBuilder(),
        )
        manifest = LocalDatasetManifest(
            source="local",
            version="1",
            license_name="Test fixture",
            path=FIXTURE_DIRECTORY,
        )
        first = await service.ingest(
            name="fixture",
            manifest=manifest,
            embedder=DeterministicEmbedder(),
            write_batch_size=2,
            embedding_batch_size=2,
        )
        assert first.inserted_documents == 3
        assert first.inserted_queries == 2
        assert first.inserted_qrels == 2
        assert first.inserted_embeddings == 3
        assert first.index_version.state is IndexBuildState.READY
        assert first.index_version.embedded_document_count == 3
        assert first.bm25_artifact.path.is_dir()
        retriever = bm25s.BM25.load(first.bm25_artifact.path, load_corpus=True)
        query_tokens = bm25s.tokenize(["red planet"], stopwords="en", show_progress=False)
        matches, _ = retriever.retrieve(query_tokens, k=1, show_progress=False)
        assert matches[0, 0]["id"] == "doc-a"

        resumed = await service.ingest(
            name="fixture",
            manifest=manifest,
            embedder=DeterministicEmbedder(),
            write_batch_size=2,
            embedding_batch_size=2,
        )
        assert resumed.index_version.id == first.index_version.id
        assert resumed.bm25_artifact == first.bm25_artifact
        assert resumed.inserted_documents == 0
        assert resumed.inserted_queries == 0
        assert resumed.inserted_qrels == 0
        assert resumed.inserted_embeddings == 0

        sessions = create_session_factory(engine)
        variants = VariantRegistry(
            variants={
                "bm25": VariantConfig(
                    name="bm25",
                    sparse=SparseStageConfig(k=100),
                )
            }
        )
        pipeline = RetrievalPipeline(
            datasets=DatasetCatalog(datasets={"fixture": manifest}),
            variants=variants,
            store=SqlAlchemySearchDataStore(sessions),
            sparse_retriever=Bm25sSparseRetriever(tmp_path / "artifacts" / "bm25"),
            query_embedders={},
            rerankers={},
        )
        application = create_app(pipeline)
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/search",
                json={
                    "query": "Which planet is known as the red planet?",
                    "dataset": "fixture",
                    "variant": "bm25",
                    "k": 2,
                },
            )
        assert response.status_code == 200
        assert response.json()["hits"][0]["document_id"] == "doc-a"

        eval_run = await run_retrieval_evaluation(
            sessions,
            search=pipeline,
            datasets=DatasetCatalog(datasets={"fixture": manifest}),
            variants=variants,
            spec=EvalRunSpec(dataset="fixture", variants=("bm25",)),
        )
        assert eval_run.state is EvalRunState.COMPLETED
        assert eval_run.progress.completed_queries == 2
        async with sessions() as session:
            eval_results = (
                await session.scalars(
                    select(EvalQueryResultRow).where(EvalQueryResultRow.eval_run_id == eval_run.id)
                )
            ).all()
        assert len(eval_results) == 2
        assert all(result.deterministic_scores["mrr_at_10"] == 1.0 for result in eval_results)

        await engine.dispose()

    asyncio.run(exercise_ingestion())


def test_ingestion_resumes_after_embedding_interruption(tmp_path: Path) -> None:
    async def exercise_resumption() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        service = IngestionService(
            create_session_factory(engine),
            download_root=tmp_path / "downloads",
            artifact_root=tmp_path / "artifacts",
            sparse_index_builder=Bm25sIndexBuilder(),
        )
        manifest = LocalDatasetManifest(
            source="local",
            version="1",
            license_name="Test fixture",
            path=FIXTURE_DIRECTORY,
        )
        with pytest.raises(RuntimeError, match="simulated interruption"):
            await service.ingest(
                name="fixture",
                manifest=manifest,
                embedder=InterruptingEmbedder(),
                embedding_batch_size=2,
            )

        resumed = await service.ingest(
            name="fixture",
            manifest=manifest,
            embedder=DeterministicEmbedder(),
            embedding_batch_size=2,
        )
        assert resumed.inserted_documents == 0
        assert resumed.inserted_queries == 0
        assert resumed.inserted_qrels == 0
        assert resumed.inserted_embeddings == 1
        assert resumed.index_version.state is IndexBuildState.READY

        await engine.dispose()

    asyncio.run(exercise_resumption())
