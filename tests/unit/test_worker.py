import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragops.contracts import EVALUATION_JOB_KIND, JobSpec, JobStatus
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.job_queue import SqlAlchemyJobQueue
from ragops.worker import JobWorker, build_evaluation_job_handler, default_worker_id


async def build_sessions() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, create_session_factory(engine)


async def enqueue(sessions: object, *, kind: str = "test.job", max_attempts: int = 3) -> object:
    async with sessions.begin() as session:  # type: ignore[attr-defined]
        return await SqlAlchemyJobQueue(session).enqueue(
            JobSpec(kind=kind, payload={"value": 1}, max_attempts=max_attempts)
        )


async def read_job(sessions: object, job_id: object) -> object:
    async with sessions() as session:  # type: ignore[operator]
        return await SqlAlchemyJobQueue(session).get(job_id)


def test_worker_runs_a_claimed_job_and_completes_it() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        job = await enqueue(sessions)
        seen: list[dict[str, object]] = []

        async def handler(payload: dict[str, object]) -> None:
            seen.append(payload)

        worker = JobWorker(sessions, handlers={"test.job": handler})
        finished = await worker.run_once()

        assert seen == [{"value": 1}]
        assert finished is not None
        assert finished.status is JobStatus.COMPLETED
        stored = await read_job(sessions, job.id)
        assert stored.status is JobStatus.COMPLETED
        assert stored.leased_by is None
        await engine.dispose()

    asyncio.run(exercise())


def test_worker_returns_an_empty_queue_without_work() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()

        async def handler(payload: dict[str, object]) -> None:
            raise AssertionError("handler must not run")

        worker = JobWorker(sessions, handlers={"test.job": handler})

        assert await worker.run_once() is None
        await engine.dispose()

    asyncio.run(exercise())


def test_a_failing_job_returns_to_the_queue_then_exhausts_its_attempts() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        job = await enqueue(sessions, max_attempts=2)

        async def handler(payload: dict[str, object]) -> None:
            raise RuntimeError("handler exploded")

        worker = JobWorker(sessions, handlers={"test.job": handler}, retry_delay_seconds=0)

        first = await worker.run_once()
        assert first is not None
        assert first.status is JobStatus.PENDING
        assert "handler exploded" in (first.last_error or "")
        assert first.attempt_count == 1

        second = await worker.run_once()
        assert second is not None
        assert second.status is JobStatus.FAILED
        assert second.attempt_count == 2

        stored = await read_job(sessions, job.id)
        assert stored.status is JobStatus.FAILED
        await engine.dispose()

    asyncio.run(exercise())


def test_a_job_with_no_registered_handler_fails_with_a_clear_error() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        await enqueue(sessions, kind="unregistered.kind", max_attempts=1)

        async def handler(payload: dict[str, object]) -> None:
            raise AssertionError("handler must not run")

        worker = JobWorker(sessions, handlers={"test.job": handler}, retry_delay_seconds=0)
        finished = await worker.run_once()

        assert finished is not None
        assert finished.status is JobStatus.FAILED
        assert "no handler registered" in (finished.last_error or "")
        await engine.dispose()

    asyncio.run(exercise())


def test_a_long_job_keeps_its_lease_alive_while_it_runs() -> None:
    """A job outliving its lease window must be heartbeated, not handed to another worker."""

    async def exercise() -> None:
        engine, sessions = await build_sessions()
        job = await enqueue(sessions)
        observed: list[object] = []

        async def handler(payload: dict[str, object]) -> None:
            # Run well past several heartbeat intervals.
            for _ in range(10):
                await asyncio.sleep(0.02)
                stored = await read_job(sessions, job.id)
                observed.append(stored.lease_expires_at)

        worker = JobWorker(
            sessions,
            handlers={"test.job": handler},
            lease_seconds=60,
            heartbeat_interval_seconds=0.01,
        )
        finished = await worker.run_once()

        assert finished is not None
        assert finished.status is JobStatus.COMPLETED
        # The lease was pushed forward at least once while the handler was running.
        assert max(observed) > min(observed)
        await engine.dispose()

    asyncio.run(exercise())


def test_run_forever_stops_when_asked() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        await enqueue(sessions)
        stop = asyncio.Event()
        handled = asyncio.Event()

        async def handler(payload: dict[str, object]) -> None:
            handled.set()

        worker = JobWorker(sessions, handlers={"test.job": handler}, poll_interval_seconds=0.01)
        task = asyncio.create_task(worker.run_forever(stop=stop))
        await asyncio.wait_for(handled.wait(), timeout=2)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        await engine.dispose()

    asyncio.run(exercise())


def test_evaluation_handler_rejects_a_payload_without_a_run_id() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()
        handler = build_evaluation_job_handler(
            sessions, search=object(), datasets=object(), variants=object()
        )

        with pytest.raises(ValueError, match="requires a string run_id"):
            await handler({})
        with pytest.raises(ValueError, match="invalid run_id"):
            await handler({"run_id": "not-a-uuid"})
        await engine.dispose()

    asyncio.run(exercise())


def test_worker_requires_handlers_and_positive_intervals() -> None:
    async def exercise() -> None:
        engine, sessions = await build_sessions()

        async def handler(payload: dict[str, object]) -> None:
            return None

        with pytest.raises(ValueError, match="at least one job handler"):
            JobWorker(sessions, handlers={})
        with pytest.raises(ValueError, match="lease_seconds must be positive"):
            JobWorker(sessions, handlers={"k": handler}, lease_seconds=0)
        with pytest.raises(ValueError, match="poll_interval_seconds must be positive"):
            JobWorker(sessions, handlers={"k": handler}, poll_interval_seconds=0)
        await engine.dispose()

    asyncio.run(exercise())


def test_worker_ids_are_unique_per_process() -> None:
    assert default_worker_id() != default_worker_id()


def test_evaluation_job_kind_is_stable() -> None:
    # The API enqueues this kind and the worker dispatches on it; they must agree.
    assert EVALUATION_JOB_KIND == "evaluation.retrieval"
