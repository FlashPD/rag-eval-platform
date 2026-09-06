import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from ragops.contracts import JobSpec, JobStatus
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.job_queue import SqlAlchemyJobQueue, claimable_job_statement


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 6, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def test_claim_query_uses_skip_locked() -> None:
    statement = claimable_job_statement(datetime(2026, 9, 6, tzinfo=UTC))

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in sql


def test_queue_is_idempotent_and_reclaims_expired_leases() -> None:
    async def exercise_queue() -> None:
        clock = MutableClock()
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        sessions = create_session_factory(engine)
        async with sessions.begin() as session:
            queue = SqlAlchemyJobQueue(session, clock=clock)
            spec = JobSpec(
                kind="eval_run",
                payload={"run_id": "run-1"},
                max_attempts=2,
                idempotency_key="eval-run-1",
                available_at=clock(),
            )
            first = await queue.enqueue(spec)
            duplicate = await queue.enqueue(spec)
            assert duplicate.id == first.id
            assert await queue.pending_count() == 1

            claimed = await queue.claim(worker_id="worker-1", lease_seconds=10)
            assert claimed is not None
            assert claimed.attempt_count == 1
            assert await queue.claim(worker_id="worker-2", lease_seconds=10) is None

            clock.advance(seconds=11)
            reclaimed = await queue.claim(worker_id="worker-2", lease_seconds=10)
            assert reclaimed is not None
            assert reclaimed.id == first.id
            assert reclaimed.attempt_count == 2

            with pytest.raises(ValueError, match="not leased by"):
                await queue.complete(first.id, worker_id="worker-1")

            failed = await queue.fail(first.id, worker_id="worker-2", error="provider error")
            assert failed.status is JobStatus.FAILED
            assert failed.last_error == "provider error"

        await engine.dispose()

    asyncio.run(exercise_queue())


def test_queue_heartbeat_completion_and_cancel() -> None:
    async def exercise_queue() -> None:
        clock = MutableClock()
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        sessions = create_session_factory(engine)
        async with sessions.begin() as session:
            queue = SqlAlchemyJobQueue(session, clock=clock)
            job = await queue.enqueue(JobSpec(kind="ingest", payload={}, available_at=clock()))
            claimed = await queue.claim(worker_id="worker-1", lease_seconds=10)
            assert claimed is not None

            clock.advance(seconds=5)
            renewed = await queue.heartbeat(job.id, worker_id="worker-1", lease_seconds=20)
            assert renewed.lease_expires_at == clock() + timedelta(seconds=20)
            completed = await queue.complete(job.id, worker_id="worker-1")
            assert completed.status is JobStatus.COMPLETED

            cancellable = await queue.enqueue(
                JobSpec(kind="ingest", payload={}, available_at=clock())
            )
            cancelled = await queue.cancel(cancellable.id)
            assert cancelled.status is JobStatus.CANCELLED

        await engine.dispose()

    asyncio.run(exercise_queue())
