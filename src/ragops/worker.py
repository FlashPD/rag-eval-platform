"""Durable worker that executes queued jobs from the Postgres job queue."""

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import DatasetCatalog, VariantRegistry
from ragops.contracts import Job
from ragops.evaluation.judging import VersionedJudgePromptRenderer
from ragops.evaluation.runner import RetrievalEvaluationRunner
from ragops.generation.service import AnswerService
from ragops.persistence.job_queue import SqlAlchemyJobQueue
from ragops.protocols import Judge
from ragops.retrieval.pipeline import SearchExecutor

LOGGER = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, JsonValue]], Awaitable[None]]

# Renew a lease several times within its window so one slow heartbeat cannot let
# the lease lapse and hand live work to a second worker.
HEARTBEATS_PER_LEASE = 3
MINIMUM_HEARTBEAT_INTERVAL_SECONDS = 1.0


async def _invoke(handler: JobHandler, payload: dict[str, JsonValue]) -> None:
    """Adapt a handler's awaitable into a coroutine that can become a task."""
    await handler(payload)


class UnknownJobKindError(Exception):
    """Raised when a claimed job has no handler registered in this worker."""


def default_worker_id() -> str:
    """Identify this worker by host and a random suffix, unique per process."""
    return f"{socket.gethostname()}:{uuid4().hex[:8]}"


def build_evaluation_job_handler(
    sessions: async_sessionmaker[AsyncSession],
    *,
    search: SearchExecutor,
    datasets: DatasetCatalog,
    variants: VariantRegistry,
    answer_service: AnswerService | None = None,
    judge_renderer: VersionedJudgePromptRenderer | None = None,
    judges: Mapping[str, Judge] | None = None,
) -> JobHandler:
    """Build the handler that executes one queued retrieval evaluation run.

    The runner is resumable and skips work already committed, so a job redelivered
    after a crash continues from the last persisted query rather than restarting.
    """

    async def handle(payload: dict[str, JsonValue]) -> None:
        raw_run_id = payload.get("run_id")
        if not isinstance(raw_run_id, str):
            raise ValueError(f"evaluation job payload requires a string run_id: {raw_run_id!r}")
        try:
            run_id = UUID(raw_run_id)
        except ValueError as error:
            raise ValueError(f"evaluation job has an invalid run_id: {raw_run_id!r}") from error
        await RetrievalEvaluationRunner(
            sessions,
            search=search,
            datasets=datasets,
            variants=variants,
            answer_service=answer_service,
            judge_renderer=judge_renderer,
            judges=judges,
        ).run(run_id)

    return handle


class JobWorker:
    """Claim jobs from the durable queue and run them under a renewed lease."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        handlers: Mapping[str, JobHandler],
        worker_id: str | None = None,
        lease_seconds: int = 300,
        poll_interval_seconds: float = 1.0,
        retry_delay_seconds: int = 10,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        if not handlers:
            raise ValueError("a worker needs at least one job handler")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if heartbeat_interval_seconds is not None and heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        self._sessions = sessions
        self._handlers = dict(handlers)
        self.worker_id = worker_id or default_worker_id()
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    @property
    def heartbeat_interval_seconds(self) -> float:
        """How often a running job renews its lease."""
        if self._heartbeat_interval_seconds is not None:
            return self._heartbeat_interval_seconds
        return max(
            self._lease_seconds / HEARTBEATS_PER_LEASE,
            MINIMUM_HEARTBEAT_INTERVAL_SECONDS,
        )

    async def run_once(self) -> Job | None:
        """Claim and execute at most one job, returning its final record."""
        job = await self._claim()
        if job is None:
            return None
        LOGGER.info("claimed job %s of kind %s", job.id, job.kind)
        try:
            await self._execute(job)
        except Exception as error:
            LOGGER.exception("job %s failed", job.id)
            return await self._fail(job, error)
        LOGGER.info("completed job %s", job.id)
        return await self._complete(job)

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        """Process jobs until ``stop`` is set, finishing any job already in flight."""
        stop_event = stop or asyncio.Event()
        while not stop_event.is_set():
            job = await self.run_once()
            if job is None:
                await self._sleep_until_stopped(stop_event, self._poll_interval_seconds)

    async def _execute(self, job: Job) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise UnknownJobKindError(f"no handler registered for job kind {job.kind!r}")

        task: asyncio.Task[None] = asyncio.create_task(_invoke(handler, job.payload))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=self.heartbeat_interval_seconds)
                if task in done:
                    await task
                    return
                await self._heartbeat(job)
        except BaseException:
            # A heartbeat failure or a shutdown must not leave the handler running
            # against a lease this worker no longer holds.
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            raise

    async def _claim(self) -> Job | None:
        async with self._sessions.begin() as session:
            return await SqlAlchemyJobQueue(session).claim(
                worker_id=self.worker_id, lease_seconds=self._lease_seconds
            )

    async def _heartbeat(self, job: Job) -> Job:
        async with self._sessions.begin() as session:
            return await SqlAlchemyJobQueue(session).heartbeat(
                job.id, worker_id=self.worker_id, lease_seconds=self._lease_seconds
            )

    async def _complete(self, job: Job) -> Job:
        async with self._sessions.begin() as session:
            return await SqlAlchemyJobQueue(session).complete(job.id, worker_id=self.worker_id)

    async def _fail(self, job: Job, error: Exception) -> Job:
        async with self._sessions.begin() as session:
            return await SqlAlchemyJobQueue(session).fail(
                job.id,
                worker_id=self.worker_id,
                error=f"{type(error).__name__}: {error}",
                retry_delay_seconds=self._retry_delay_seconds,
            )

    @staticmethod
    async def _sleep_until_stopped(stop: asyncio.Event, seconds: float) -> None:
        """Wait out the poll interval, but wake immediately on shutdown."""
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
