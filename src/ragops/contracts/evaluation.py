"""Evaluation run, metric, gate, and judge contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from ragops.contracts.base import Contract
from ragops.contracts.generation import AnswerResponse
from ragops.contracts.retrieval import StageTiming


class EvalRunState(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    PREPARING = "preparing"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    JUDGING = "judging"
    SCORING = "scoring"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_NEXT_STATES: dict[EvalRunState, frozenset[EvalRunState]] = {
    EvalRunState.CREATED: frozenset({EvalRunState.QUEUED}),
    EvalRunState.QUEUED: frozenset({EvalRunState.PREPARING}),
    EvalRunState.PREPARING: frozenset({EvalRunState.RETRIEVING}),
    EvalRunState.RETRIEVING: frozenset({EvalRunState.GENERATING, EvalRunState.SCORING}),
    EvalRunState.GENERATING: frozenset({EvalRunState.JUDGING, EvalRunState.SCORING}),
    EvalRunState.JUDGING: frozenset({EvalRunState.SCORING}),
    EvalRunState.SCORING: frozenset({EvalRunState.COMPLETED}),
    EvalRunState.COMPLETED: frozenset(),
    EvalRunState.FAILED: frozenset(),
    EvalRunState.CANCELLED: frozenset(),
}


def ensure_state_transition(current: EvalRunState, target: EvalRunState) -> None:
    """Reject lifecycle transitions that would make a run inconsistent."""
    if target == current:
        return
    if target in {EvalRunState.FAILED, EvalRunState.CANCELLED} and current not in {
        EvalRunState.COMPLETED,
        EvalRunState.FAILED,
        EvalRunState.CANCELLED,
    }:
        return
    if target not in _NEXT_STATES[current]:
        raise ValueError(f"invalid eval run transition: {current.value} -> {target.value}")


class EvalRunSpec(Contract):
    dataset: str = Field(min_length=1)
    split: str = Field(default="test", min_length=1)
    variants: tuple[str, ...] = Field(min_length=1)
    sample_size: int | None = Field(default=None, gt=0)
    seed: int = 42
    generation_enabled: bool = False
    generator_profile: str | None = None
    judge_profiles: tuple[str, ...] = ()
    generation_prompt_version: str | None = None
    judge_prompt_version: str | None = None

    @model_validator(mode="after")
    def validate_generation_settings(self) -> "EvalRunSpec":
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("eval variants must be unique")
        if self.generation_enabled and self.generator_profile is None:
            raise ValueError("generator_profile is required when generation is enabled")
        return self


class EvalProgress(Contract):
    completed_queries: int = Field(default=0, ge=0)
    total_queries: int = Field(default=0, ge=0)


class EvalRun(Contract):
    id: UUID
    spec: EvalRunSpec
    state: EvalRunState
    progress: EvalProgress
    git_commit: str | None = None
    image_digest: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class QueryResult(Contract):
    run_id: UUID
    variant: str
    query_id: str
    ranked_document_ids: tuple[str, ...]
    stage_timings: tuple[StageTiming, ...]
    answer: AnswerResponse | None = None
    deterministic_scores: dict[str, float] = Field(default_factory=dict)
    judge_scores: dict[str, float] = Field(default_factory=dict)
    token_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)


class MetricSummary(Contract):
    metric: str
    variant: str
    mean: float
    interval_low: float
    interval_high: float
    query_count: int = Field(gt=0)


class Comparison(Contract):
    metric: str
    variant_a: str
    variant_b: str
    difference: float
    interval_low: float
    interval_high: float
    significant: bool


class GateMetricResult(Contract):
    metric: str
    baseline: float
    observed: float
    tolerance: float = Field(ge=0)
    breached: bool


class GateResult(Contract):
    passed: bool
    metrics: tuple[GateMetricResult, ...]


class JudgeClaimVerdict(Contract):
    claim: str = Field(min_length=1)
    supported: bool
    citation_ids: tuple[str, ...]


class JudgeVerdict(Contract):
    claims: tuple[JudgeClaimVerdict, ...]
    faithfulness: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    rationale: str
    judge_model: str
    judge_prompt_version: str
