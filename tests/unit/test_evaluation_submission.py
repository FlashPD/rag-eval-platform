import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragops.config import DatasetCatalog, LocalDatasetManifest, VariantRegistry
from ragops.contracts import (
    EVALUATION_JOB_KIND,
    EvalRunSpec,
    EvalRunState,
    JobStatus,
    SparseStageConfig,
    VariantConfig,
)
from ragops.evaluation import submit_retrieval_evaluation
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.models import EvalRunRow, JobRow
from ragops.persistence.repositories import SqlAlchemyEvaluationRunRepository


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
        variants={"bm25": VariantConfig(name="bm25", sparse=SparseStageConfig(k=100))}
    )
    return datasets, variants


async def build_sessions() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, create_session_factory(engine)


def test_submission_queues_the_run_and_its_job_together() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        datasets, variants = build_catalogs()
        spec = EvalRunSpec(dataset="fixture", variants=("bm25",), sample_size=2, seed=42)

        run = await submit_retrieval_evaluation(
            sessions,
            datasets=datasets,
            variants=variants,
            spec=spec,
            git_commit="abc123",
        )

        assert run.state is EvalRunState.QUEUED
        assert run.git_commit == "abc123"

        async with sessions() as session:  # type: ignore[operator]
            jobs = list(await session.scalars(select(JobRow)))
            stored = await SqlAlchemyEvaluationRunRepository(session).get(run.id)

        assert stored is not None
        assert stored.state is EvalRunState.QUEUED
        # Exactly one job, addressed to this run, waiting for a worker.
        assert len(jobs) == 1
        assert jobs[0].kind == EVALUATION_JOB_KIND
        assert jobs[0].payload == {"run_id": str(run.id)}
        assert jobs[0].status == JobStatus.PENDING.value
        assert jobs[0].idempotency_key == f"{EVALUATION_JOB_KIND}:{run.id}"
        await engine.dispose()

    asyncio.run(exercise())


def test_a_rejected_spec_writes_neither_a_run_nor_a_job() -> None:
    """Validation failures must not leave a queued run behind."""

    async def exercise() -> None:
        engine, sessions = await build_sessions()
        datasets, variants = build_catalogs()

        with pytest.raises(KeyError):
            await submit_retrieval_evaluation(
                sessions,
                datasets=datasets,
                variants=variants,
                spec=EvalRunSpec(dataset="missing", variants=("bm25",)),
            )

        async with sessions() as session:  # type: ignore[operator]
            assert list(await session.scalars(select(EvalRunRow))) == []
            assert list(await session.scalars(select(JobRow))) == []
        await engine.dispose()

    asyncio.run(exercise())


def test_an_unknown_variant_is_rejected_before_anything_is_written() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        datasets, variants = build_catalogs()

        with pytest.raises(KeyError):
            await submit_retrieval_evaluation(
                sessions,
                datasets=datasets,
                variants=variants,
                spec=EvalRunSpec(dataset="fixture", variants=("nonexistent",)),
            )

        async with sessions() as session:  # type: ignore[operator]
            assert list(await session.scalars(select(EvalRunRow))) == []
            assert list(await session.scalars(select(JobRow))) == []
        await engine.dispose()

    asyncio.run(exercise())
