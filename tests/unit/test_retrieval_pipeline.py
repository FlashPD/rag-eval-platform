import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ragops.config import DatasetCatalog, LocalDatasetManifest, VariantRegistry
from ragops.contracts import (
    DenseStageConfig,
    FusionStageConfig,
    IndexBuildState,
    IndexVersion,
    PersistedDocument,
    RerankStageConfig,
    SearchRequest,
    SparseStageConfig,
    VariantConfig,
)
from ragops.retrieval.pipeline import RetrievalPipeline
from ragops.retrieval.types import StageHit


class FakeSparseRetriever:
    async def retrieve(self, query: str, *, artifact_hash: str, k: int) -> tuple[StageHit, ...]:
        return (
            StageHit(document_id="doc-a", score=0.9),
            StageHit(document_id="doc-b", score=0.8),
        )


class FakeQueryEmbedder:
    model_id = "test/embedding"
    dimension = 384
    normalized = True

    async def encode_query(self, text: str) -> Sequence[float]:
        return [0.0] * 383 + [1.0]


class FakeReranker:
    model_id = "test/reranker"

    async def score(self, query: str, documents: Sequence[PersistedDocument]) -> Sequence[float]:
        scores = {"doc-a": 0.9, "doc-b": 0.5, "doc-c": 0.1}
        return [scores[document.external_id] for document in documents]


class FakeStore:
    def __init__(self) -> None:
        self.index = IndexVersion(
            id=uuid4(),
            dataset_id=uuid4(),
            corpus_version_id=uuid4(),
            corpus_hash="c" * 64,
            configuration_hash="i" * 64,
            embedding_model="test/embedding",
            normalized=True,
            hnsw_parameters={"m": 16},
            bm25_artifact_hash="b" * 64,
            total_document_count=3,
            state=IndexBuildState.READY,
            embedded_document_count=3,
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.documents = {
            name: PersistedDocument(
                id=uuid4(), external_id=name, title=name, text=f"Text for {name}"
            )
            for name in ("doc-a", "doc-b", "doc-c")
        }

    async def resolve_index(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        split: str,
        embedding_model: str | None,
    ) -> IndexVersion:
        assert dataset_name == "fixture"
        assert dataset_version == "1"
        assert split == "test"
        return self.index

    async def dense_search(
        self, index_version_id: UUID, query_embedding: Sequence[float], *, k: int
    ) -> tuple[StageHit, ...]:
        assert len(query_embedding) == 384
        return (
            StageHit(document_id="doc-b", score=0.95),
            StageHit(document_id="doc-c", score=0.7),
        )

    async def load_documents(
        self, corpus_version_id: UUID, document_ids: Sequence[str]
    ) -> dict[str, PersistedDocument]:
        return {document_id: self.documents[document_id] for document_id in document_ids}


def build_pipeline(*, rerank: bool = False) -> RetrievalPipeline:
    variant = VariantConfig(
        name="hybrid",
        sparse=SparseStageConfig(k=100),
        dense=DenseStageConfig(model="test/embedding", k=100),
        fusion=FusionStageConfig(k=60),
        rerank=(RerankStageConfig(model="test/reranker", candidates=3, keep=2) if rerank else None),
    )
    return RetrievalPipeline(
        datasets=DatasetCatalog(
            datasets={
                "fixture": LocalDatasetManifest(
                    source="local",
                    version="1",
                    license_name="Test",
                    path=Path("fixtures/tiny-beir"),
                )
            }
        ),
        variants=VariantRegistry(variants={"hybrid": variant}),
        store=FakeStore(),
        sparse_retriever=FakeSparseRetriever(),
        query_embedders={"test/embedding": FakeQueryEmbedder()},
        rerankers={"test/reranker": FakeReranker()},
    )


def test_hybrid_pipeline_returns_scores_documents_and_timings() -> None:
    response = asyncio.run(
        build_pipeline().search(
            SearchRequest(query="question", dataset="fixture", variant="hybrid", k=3)
        )
    )

    assert [hit.document_id for hit in response.hits] == ["doc-b", "doc-a", "doc-c"]
    assert response.hits[0].stage_scores.keys() == {
        "sparse_score",
        "dense_score",
        "fused_score",
    }
    assert response.hits[0].text == "Text for doc-b"
    assert [timing.stage for timing in response.timings] == [
        "sparse_retrieve",
        "dense_embed_query",
        "dense_retrieve",
        "fuse",
        "hydrate_results",
    ]
    assert len(response.trace_id) == 32
    assert response.index_fingerprint == FakeStore().index.fingerprint


def test_reranker_reorders_fused_candidates() -> None:
    response = asyncio.run(
        build_pipeline(rerank=True).search(
            SearchRequest(query="question", dataset="fixture", variant="hybrid", k=2)
        )
    )

    assert [hit.document_id for hit in response.hits] == ["doc-a", "doc-b"]
    assert response.hits[0].stage_scores["rerank_score"] == 0.9


def test_reranking_preserves_retrieval_depth_beyond_keep() -> None:
    """Reranking reorders the candidate window; it must not shorten the result list.

    Truncating to ``keep`` would cap deep metrics such as Recall@100 at Recall@keep
    and make a reranked variant look worse than its unreranked parent at depth.
    """
    response = asyncio.run(
        build_pipeline(rerank=True).search(
            SearchRequest(query="question", dataset="fixture", variant="hybrid", k=3)
        )
    )

    # keep=2 promotes doc-a and doc-b; doc-c stays below in its fused order.
    assert [hit.document_id for hit in response.hits] == ["doc-a", "doc-b", "doc-c"]
    assert [hit.rank for hit in response.hits] == [1, 2, 3]
    # Every scored candidate keeps its rerank score, including the unpromoted tail.
    assert [hit.stage_scores["rerank_score"] for hit in response.hits] == [0.9, 0.5, 0.1]
