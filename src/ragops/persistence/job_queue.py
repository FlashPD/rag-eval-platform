"""Postgres-backed durable job queue with renewable worker leases."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.contracts import Job, JobSpec, JobStatus
from ragops.persistence.models import JobRow
from ragops.persistence.time import as_utc, optional_as_utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def claimable_job_statement(now: datetime) -> Select[tuple[JobRow]]:
    """Build the row-locking claim query used by competing workers."""
    pending = and_(JobRow.status == JobStatus.PENDING.value, JobRow.available_at <= now)
    expired = and_(
        JobRow.status == JobStatus.LEASED.value,
        JobRow.lease_expires_at <= now,
        JobRow.attempt_count < JobRow.max_attempts,
    )
    return (
        select(JobRow)
        .where(or_(pending, expired))
        .order_by(JobRow.available_at, JobRow.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


class JobQueue(Protocol):
    async def enqueue(self, spec: JobSpec) -> Job: ...

    async def get(self, job_id: UUID) -> Job | None: ...

    async def claim(self, *, worker_id: str, lease_seconds: int) -> Job | None: ...

    async def heartbeat(self, job_id: UUID, *, worker_id: str, lease_seconds: int) -> Job: ...

    async def complete(self, job_id: UUID, *, worker_id: str) -> Job: ...

    async def fail(
        self, job_id: UUID, *, worker_id: str, error: str, retry_delay_seconds: int = 0
    ) -> Job: ...


def _job_contract(row: JobRow) -> Job:
    return Job(
        id=row.id,
        kind=row.kind,
        payload=row.payload,
        status=JobStatus(row.status),
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        idempotency_key=row.idempotency_key,
        available_at=as_utc(row.available_at),
        lease_expires_at=optional_as_utc(row.lease_expires_at),
        leased_by=row.leased_by,
        last_error=row.last_error,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


class SqlAlchemyJobQueue:
    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def enqueue(self, spec: JobSpec) -> Job:
        if spec.idempotency_key is None:
            row = JobRow(
                kind=spec.kind,
                payload=spec.payload,
                status=JobStatus.PENDING.value,
                max_attempts=spec.max_attempts,
                available_at=spec.available_at,
            )
            self._session.add(row)
            await self._session.flush()
            await self._session.refresh(row)
            return _job_contract(row)

        job_id = uuid4()
        values = {
            "id": job_id,
            "kind": spec.kind,
            "payload": spec.payload,
            "status": JobStatus.PENDING.value,
            "attempt_count": 0,
            "max_attempts": spec.max_attempts,
            "idempotency_key": spec.idempotency_key,
            "available_at": spec.available_at,
        }
        bind = self._session.get_bind()
        statement: Any
        if bind.dialect.name == "postgresql":
            statement = postgresql_insert(JobRow).values(**values)
        elif bind.dialect.name == "sqlite":
            statement = sqlite_insert(JobRow).values(**values)
        else:
            raise RuntimeError(f"unsupported database dialect: {bind.dialect.name}")
        statement = statement.on_conflict_do_nothing(index_elements=["idempotency_key"])
        await self._session.execute(statement)

        existing_row = await self._session.scalar(
            select(JobRow).where(JobRow.idempotency_key == spec.idempotency_key)
        )
        if existing_row is None:
            raise RuntimeError("idempotent job insert did not return a row")
        return _job_contract(existing_row)

    async def get(self, job_id: UUID) -> Job | None:
        row = await self._session.get(JobRow, job_id)
        return _job_contract(row) if row is not None else None

    async def claim(self, *, worker_id: str, lease_seconds: int) -> Job | None:
        self._validate_lease(worker_id, lease_seconds)
        now = self._clock()
        await self._mark_exhausted_leases_failed(now)
        row = await self._session.scalar(claimable_job_statement(now))
        if row is None:
            return None

        row.status = JobStatus.LEASED.value
        row.attempt_count += 1
        row.leased_by = worker_id
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self._session.flush()
        await self._session.refresh(row)
        return _job_contract(row)

    async def heartbeat(self, job_id: UUID, *, worker_id: str, lease_seconds: int) -> Job:
        self._validate_lease(worker_id, lease_seconds)
        row = await self._owned_lease(job_id, worker_id)
        row.lease_expires_at = self._clock() + timedelta(seconds=lease_seconds)
        await self._session.flush()
        await self._session.refresh(row)
        return _job_contract(row)

    async def complete(self, job_id: UUID, *, worker_id: str) -> Job:
        row = await self._owned_lease(job_id, worker_id)
        row.status = JobStatus.COMPLETED.value
        row.leased_by = None
        row.lease_expires_at = None
        await self._session.flush()
        await self._session.refresh(row)
        return _job_contract(row)

    async def fail(
        self, job_id: UUID, *, worker_id: str, error: str, retry_delay_seconds: int = 0
    ) -> Job:
        if retry_delay_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        row = await self._owned_lease(job_id, worker_id)
        row.last_error = error
        row.leased_by = None
        row.lease_expires_at = None
        if row.attempt_count >= row.max_attempts:
            row.status = JobStatus.FAILED.value
        else:
            row.status = JobStatus.PENDING.value
            row.available_at = self._clock() + timedelta(seconds=retry_delay_seconds)
        await self._session.flush()
        await self._session.refresh(row)
        return _job_contract(row)

    async def cancel(self, job_id: UUID) -> Job:
        row = await self._session.get(JobRow, job_id)
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        status = JobStatus(row.status)
        if status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            raise ValueError(f"cannot cancel a {status.value} job")
        row.status = JobStatus.CANCELLED.value
        row.leased_by = None
        row.lease_expires_at = None
        await self._session.flush()
        await self._session.refresh(row)
        return _job_contract(row)

    async def pending_count(self) -> int:
        statement = (
            select(func.count()).select_from(JobRow).where(JobRow.status == JobStatus.PENDING.value)
        )
        return int(await self._session.scalar(statement) or 0)

    async def _owned_lease(self, job_id: UUID, worker_id: str) -> JobRow:
        row = await self._session.get(JobRow, job_id)
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        if row.status != JobStatus.LEASED.value or row.leased_by != worker_id:
            raise ValueError(f"job {job_id} is not leased by worker {worker_id!r}")
        return row

    async def _mark_exhausted_leases_failed(self, now: datetime) -> None:
        statement = (
            update(JobRow)
            .where(
                JobRow.status == JobStatus.LEASED.value,
                JobRow.lease_expires_at <= now,
                JobRow.attempt_count >= JobRow.max_attempts,
            )
            .values(
                status=JobStatus.FAILED.value,
                leased_by=None,
                lease_expires_at=None,
                last_error="worker lease expired after final attempt",
            )
        )
        await self._session.execute(statement)

    @staticmethod
    def _validate_lease(worker_id: str, lease_seconds: int) -> None:
        if not worker_id:
            raise ValueError("worker_id cannot be empty")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
