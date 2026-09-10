"""Durable job queue contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, JsonValue, PositiveInt

from ragops.contracts.base import Contract

EVALUATION_JOB_KIND = "evaluation.retrieval"
ONLINE_JUDGE_JOB_KIND = "evaluation.online_judge"


class JobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobSpec(Contract):
    kind: str = Field(min_length=1, max_length=100)
    payload: dict[str, JsonValue]
    max_attempts: PositiveInt = 3
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    available_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Job(Contract):
    id: UUID
    kind: str
    payload: dict[str, JsonValue]
    status: JobStatus
    attempt_count: int = Field(ge=0)
    max_attempts: PositiveInt
    idempotency_key: str | None
    available_at: datetime
    lease_expires_at: datetime | None
    leased_by: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
