import asyncio

import pytest

from ragops.contracts import EvalRunSpec, EvalRunState
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyEvaluationRunRepository,
)


def test_core_metadata_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == {
        "corpus_versions",
        "datasets",
        "document_embeddings",
        "documents",
        "eval_query_results",
        "eval_run_variants",
        "eval_runs",
        "generation_cache",
        "index_versions",
        "judge_cache",
        "jobs",
        "online_evaluations",
        "qrels",
        "queries",
    }


def test_async_repositories_round_trip_contracts() -> None:
    async def exercise_repositories() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        sessions = create_session_factory(engine)
        async with sessions.begin() as session:
            datasets = SqlAlchemyDatasetRepository(session)
            created_dataset = await datasets.create(
                name="scifact",
                version="1.0",
                split="test",
                license_name="CC BY-NC 2.0",
            )
            loaded_dataset = await datasets.get_by_key(name="scifact", version="1.0", split="test")
            assert loaded_dataset == created_dataset

            runs = SqlAlchemyEvaluationRunRepository(session)
            run = await runs.create(
                EvalRunSpec(dataset="scifact", variants=("bm25",)),
                variant_hashes={"bm25": "a" * 64},
            )
            queued = await runs.set_state(run.id, EvalRunState.QUEUED)
            assert queued.state is EvalRunState.QUEUED

            pinned = await runs.pin_index_fingerprint(run.id, variant="bm25", fingerprint="f" * 64)
            assert pinned.index_fingerprints == {"bm25": "f" * 64}

            with pytest.raises(ValueError, match="queued -> retrieving"):
                await runs.set_state(run.id, EvalRunState.RETRIEVING)

        await engine.dispose()

    asyncio.run(exercise_repositories())
