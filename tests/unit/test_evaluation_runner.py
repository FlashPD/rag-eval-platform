import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import DatasetCatalog, LocalDatasetManifest, VariantRegistry
from ragops.contracts import (
    EvalRunSpec,
    EvalRunState,
    EvaluationQuery,
    QueryResult,
    RankedHit,
    RerankStageConfig,
    SearchRequest,
    SearchResponse,
    SparseStageConfig,
    StageTiming,
    VariantConfig,
)
from ragops.evaluation import (
    RetrievalEvaluationRunner,
    get_evaluation_report,
    run_retrieval_evaluation,
    select_evaluation_queries,
)
from ragops.evaluation.repository import SqlAlchemyEvaluationDataRepository
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.models import (
    CorpusVersionRow,
    DatasetRow,
    DocumentRow,
    EvalQueryResultRow,
    QrelRow,
    QueryRow,
)
from ragops.persistence.repositories import SqlAlchemyEvaluationRunRepository


class FakeSearchExecutor:
    def __init__(self, variants: VariantRegistry) -> None:
        self._variants = variants
        self.requests: list[SearchRequest] = []

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.requests.append(request)
        ranked_ids = (
            ("doc-a", "doc-b", "doc-c")
            if request.query == "first question"
            else ("doc-a", "doc-c", "doc-b")
        )
        return SearchResponse(
            hits=tuple(
                RankedHit(
                    document_id=document_id,
                    title=document_id,
                    text=f"Text for {document_id}",
                    rank=rank,
                    score=1.0 / rank,
                )
                for rank, document_id in enumerate(ranked_ids, start=1)
            ),
            timings=(StageTiming(stage="sparse_retrieve", duration_ms=2.5),),
            trace_id=uuid4().hex,
            variant_hash=self._variants.get(request.variant).configuration_hash,
        )


def build_catalogs() -> tuple[DatasetCatalog, VariantRegistry]:
    datasets = DatasetCatalog(
        datasets={
            "fixture": LocalDatasetManifest(
                source="local",
                version="1",
                default_split="test",
                license_name="Test",
                path=Path("fixtures/tiny-beir"),
            )
        }
    )
    variants = VariantRegistry(
        variants={
            "bm25": VariantConfig(name="bm25", sparse=SparseStageConfig(k=100)),
            "reranked": VariantConfig(
                name="reranked",
                sparse=SparseStageConfig(k=100),
                rerank=RerankStageConfig(model="test/reranker", candidates=50, keep=10),
            ),
        }
    )
    return datasets, variants


async def seed_dataset(sessions: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    async with sessions.begin() as session:
        dataset = DatasetRow(
            name="fixture",
            version="1",
            split="test",
            license_name="Test",
        )
        session.add(dataset)
        await session.flush()
        corpus = CorpusVersionRow(
            dataset_id=dataset.id,
            content_hash="c" * 64,
            document_count=3,
        )
        session.add(corpus)
        await session.flush()
        documents = {
            external_id: DocumentRow(
                corpus_version_id=corpus.id,
                external_id=external_id,
                title=external_id,
                text=f"Text for {external_id}",
            )
            for external_id in ("doc-a", "doc-b", "doc-c")
        }
        queries = {
            "q-1": QueryRow(dataset_id=dataset.id, external_id="q-1", text="first question"),
            "q-2": QueryRow(dataset_id=dataset.id, external_id="q-2", text="second question"),
        }
        session.add_all([*documents.values(), *queries.values()])
        await session.flush()
        session.add_all(
            [
                QrelRow(query_id=queries["q-1"].id, document_id=documents["doc-a"].id, relevance=2),
                QrelRow(query_id=queries["q-2"].id, document_id=documents["doc-c"].id, relevance=1),
            ]
        )
        await session.flush()
        return queries["q-1"].id, queries["q-2"].id


def test_runner_executes_variants_and_persists_metrics() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        await seed_dataset(sessions)
        datasets, variants = build_catalogs()
        search = FakeSearchExecutor(variants)

        async with sessions.begin() as session:
            runs = SqlAlchemyEvaluationRunRepository(session)
            run = await runs.create(
                EvalRunSpec(dataset="fixture", variants=("bm25", "reranked")),
                variant_hashes={
                    name: variants.get(name).configuration_hash for name in ("bm25", "reranked")
                },
            )
            await runs.set_state(run.id, EvalRunState.QUEUED)

        completed = await RetrievalEvaluationRunner(
            sessions,
            search=search,
            datasets=datasets,
            variants=variants,
        ).run(run.id)

        assert completed.state is EvalRunState.COMPLETED
        assert completed.progress.completed_queries == 4
        assert completed.progress.total_queries == 4
        assert len(search.requests) == 4
        # Every variant is evaluated at the same depth, including reranked ones, so
        # depth-100 metrics stay comparable across variants.
        assert {request.k for request in search.requests} == {100}

        async with sessions() as session:
            results = (
                await session.scalars(
                    select(EvalQueryResultRow).order_by(
                        EvalQueryResultRow.query_id, EvalQueryResultRow.variant
                    )
                )
            ).all()
        assert len(results) == 4
        second_query_results = [
            row for row in results if row.deterministic_scores["mrr_at_10"] == 0.5
        ]
        assert len(second_query_results) == 2
        assert all(row.deterministic_scores["recall_at_10"] == 1.0 for row in results)
        assert all(row.stage_timings[0]["stage"] == "sparse_retrieve" for row in results)
        await engine.dispose()

    asyncio.run(exercise())


def test_runner_resumes_without_repeating_persisted_work() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        first_query_id, _ = await seed_dataset(sessions)
        datasets, variants = build_catalogs()

        async with sessions.begin() as session:
            runs = SqlAlchemyEvaluationRunRepository(session)
            run = await runs.create(
                EvalRunSpec(dataset="fixture", variants=("bm25",)),
                variant_hashes={"bm25": variants.get("bm25").configuration_hash},
            )
            await runs.set_state(run.id, EvalRunState.QUEUED)
            await runs.set_state(run.id, EvalRunState.PREPARING)
            await runs.set_progress(run.id, completed_queries=0, total_queries=2)
            await runs.set_state(run.id, EvalRunState.RETRIEVING)
            await SqlAlchemyEvaluationDataRepository(session).add_result(
                QueryResult(
                    run_id=run.id,
                    variant="bm25",
                    query_id="q-1",
                    ranked_document_ids=("doc-a",),
                    stage_timings=(),
                    deterministic_scores={
                        "ndcg_at_10": 1.0,
                        "recall_at_10": 1.0,
                        "recall_at_100": 1.0,
                        "mrr_at_10": 1.0,
                    },
                ),
                query_id=first_query_id,
            )

        search = FakeSearchExecutor(variants)
        completed = await RetrievalEvaluationRunner(
            sessions,
            search=search,
            datasets=datasets,
            variants=variants,
        ).run(run.id)

        assert completed.state is EvalRunState.COMPLETED
        assert completed.progress.completed_queries == 2
        assert [request.query for request in search.requests] == ["second question"]
        await engine.dispose()

    asyncio.run(exercise())


def test_service_creates_queues_and_executes_a_sampled_run() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        await seed_dataset(sessions)
        datasets, variants = build_catalogs()
        search = FakeSearchExecutor(variants)

        completed = await run_retrieval_evaluation(
            sessions,
            search=search,
            datasets=datasets,
            variants=variants,
            spec=EvalRunSpec(
                dataset="fixture",
                variants=("bm25",),
                sample_size=1,
                seed=7,
            ),
            git_commit="a" * 40,
        )

        assert completed.state is EvalRunState.COMPLETED
        assert completed.progress.completed_queries == 1
        assert completed.progress.total_queries == 1
        assert completed.git_commit == "a" * 40
        assert len(search.requests) == 1
        report = await get_evaluation_report(sessions, completed.id)
        assert len(report.metrics) == 4
        assert all(summary.query_count == 1 for summary in report.metrics)
        assert report.latencies[0].stage == "sparse_retrieve"
        await engine.dispose()

    asyncio.run(exercise())


def test_query_sampling_is_stable_and_validates_size() -> None:
    queries = tuple(
        EvaluationQuery(id=uuid4(), external_id=f"q-{index}", text="question", qrels={})
        for index in range(5)
    )

    first = select_evaluation_queries(queries, sample_size=3, seed=42)
    reordered = select_evaluation_queries(tuple(reversed(queries)), sample_size=3, seed=42)

    assert [query.external_id for query in first] == [query.external_id for query in reordered]
    assert [query.external_id for query in first] == sorted(query.external_id for query in first)
    with pytest.raises(ValueError, match="exceeds"):
        select_evaluation_queries(queries, sample_size=6, seed=42)
