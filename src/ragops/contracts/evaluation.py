"""Evaluation run, metric, gate, and judge contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ragops.contracts.base import Contract
from ragops.contracts.generation import AnswerResponse, Passage, TokenUsage
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
    generation_sample_size: int | None = Field(default=None, gt=0)
    generation_variants: tuple[str, ...] = ()
    seed: int = 42
    generation_enabled: bool = False
    generator_profile: str | None = None
    judge_profiles: tuple[str, ...] = ()
    generation_prompt_version: str | None = None
    judge_prompt_version: str | None = None

    @model_validator(mode="after")
    def validate_generation_settings(self) -> EvalRunSpec:
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("eval variants must be unique")
        if self.generation_enabled and (
            self.generator_profile is None or self.generation_prompt_version is None
        ):
            raise ValueError(
                "generator_profile and generation_prompt_version are required "
                "when generation is enabled"
            )
        if len(set(self.generation_variants)) != len(self.generation_variants):
            raise ValueError("generation_variants must be unique")
        if self.generation_variants and not set(self.generation_variants).issubset(self.variants):
            raise ValueError("generation_variants must be a subset of variants")
        if not self.generation_enabled and (
            self.generation_sample_size is not None
            or self.generation_variants
            or self.generator_profile is not None
            or self.judge_profiles
            or self.generation_prompt_version is not None
            or self.judge_prompt_version is not None
        ):
            raise ValueError("generation settings require generation_enabled")
        if self.judge_profiles and self.judge_prompt_version is None:
            raise ValueError("judge_prompt_version is required when judges are enabled")
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
    index_fingerprints: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None


class EvaluationQuery(Contract):
    """An ingested benchmark query and its document relevance judgments."""

    id: UUID
    external_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    qrels: dict[str, int]
    metadata: dict[str, object] = Field(default_factory=dict)


class QueryResult(Contract):
    run_id: UUID
    variant: str
    query_id: str
    ranked_document_ids: tuple[str, ...]
    stage_timings: tuple[StageTiming, ...]
    answer: AnswerResponse | None = None
    deterministic_scores: dict[str, float] = Field(default_factory=dict)
    judge_scores: dict[str, float] = Field(default_factory=dict)
    judge_records: dict[str, JudgeVerdict] = Field(default_factory=dict)
    scifact_gold_label: str | None = None
    token_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)


class RetrievalMetricScores(Contract):
    """Deterministic retrieval scores for one query."""

    ndcg_at_10: float = Field(ge=0, le=1)
    recall_at_10: float = Field(ge=0, le=1)
    recall_at_100: float = Field(ge=0, le=1)
    mrr_at_10: float = Field(ge=0, le=1)

    def as_score_dict(self) -> dict[str, float]:
        """Return the representation persisted in ``QueryResult``."""
        return self.model_dump()


class MetricSummary(Contract):
    metric: str
    variant: str
    mean: float
    interval_low: float
    interval_high: float
    query_count: int = Field(gt=0)


class LatencySummary(Contract):
    variant: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    sample_count: int = Field(gt=0)


class Comparison(Contract):
    """A paired-bootstrap difference between two variants on one metric."""

    metric: str = Field(min_length=1)
    variant_a: str = Field(min_length=1)
    variant_b: str = Field(min_length=1)
    difference: float
    interval_low: float
    interval_high: float
    significant: bool


class EvaluationReport(Contract):
    run: EvalRun
    metrics: tuple[MetricSummary, ...]
    latencies: tuple[LatencySummary, ...]
    comparisons: tuple[Comparison, ...] = ()


class BaselineDocument(Contract):
    """Committed reference metrics for one dataset split.

    Baselines are updated only through a reviewed pull request, so the run that
    produced each number stays attributable.
    """

    version: Literal[2] = 2
    dataset: str = Field(min_length=1)
    split: str = Field(min_length=1)
    sample_size: int | None = Field(default=None, gt=0)
    seed: int
    generation_sample_size: int | None = Field(default=None, gt=0)
    generation_variants: tuple[str, ...] = ()
    generator_profile: str | None = None
    judge_profiles: tuple[str, ...] = ()
    generation_prompt_version: str | None = None
    judge_prompt_version: str | None = None
    run_id: UUID
    git_commit: str | None = None
    recorded_at: datetime
    variant_hashes: dict[str, str] = Field(default_factory=dict)
    index_fingerprints: dict[str, str] = Field(min_length=1)
    metrics: dict[str, dict[str, float]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_metrics(self) -> BaselineDocument:
        for variant, scores in self.metrics.items():
            if not variant:
                raise ValueError("baseline variant names cannot be empty")
            if not scores:
                raise ValueError(f"baseline variant {variant!r} records no metrics")
        metric_variants = set(self.metrics)
        if set(self.variant_hashes) != metric_variants:
            raise ValueError("baseline variant hashes must cover exactly the baselined variants")
        if set(self.index_fingerprints) != metric_variants:
            raise ValueError(
                "baseline index fingerprints must cover exactly the baselined variants"
            )
        for label, hashes in (
            ("variant configuration", self.variant_hashes),
            ("index fingerprint", self.index_fingerprints),
        ):
            invalid = [variant for variant, value in hashes.items() if len(value) != 64]
            if invalid:
                raise ValueError(f"baseline {label} hashes must be 64 characters: {invalid}")
        return self


class GateMetricResult(Contract):
    variant: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    baseline: float
    observed: float
    tolerance: float = Field(ge=0)
    breached: bool

    @property
    def delta(self) -> float:
        """Return the signed change from the baseline; negative is a regression."""
        return self.observed - self.baseline


class GateResult(Contract):
    passed: bool
    dataset: str = Field(min_length=1)
    run_id: UUID
    baseline_run_id: UUID
    metrics: tuple[GateMetricResult, ...]

    @property
    def breaches(self) -> tuple[GateMetricResult, ...]:
        """Return only the metrics that regressed past their tolerance."""
        return tuple(result for result in self.metrics if result.breached)


class JudgeClaimVerdict(Contract):
    claim: str = Field(min_length=1)
    supported: bool
    citation_ids: tuple[str, ...]


class JudgeVerdict(Contract):
    claims: tuple[JudgeClaimVerdict, ...]
    faithfulness: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    rationale: str
    provider: str = Field(min_length=1)
    judge_model: str
    judge_configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    judge_prompt_version: str
    rendered_prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    usage: TokenUsage
    provider_request_id: str | None = Field(default=None, min_length=1)
    cache_hit: bool = False


class JudgeOutput(Contract):
    """Provider-normalized rubric output before provenance is attached."""

    claims: tuple[JudgeClaimVerdict, ...]
    faithfulness: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class JudgeRequest(Contract):
    query: str = Field(min_length=1, max_length=4_096)
    answer: str
    abstained: bool
    citations: tuple[str, ...]
    contexts: tuple[Passage, ...]
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    prompt_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    trace_id: str = Field(min_length=1)

    @property
    def rendered_prompt_hash(self) -> str:
        canonical = json.dumps(
            {
                "prompt_version": self.prompt_version,
                "system_prompt": self.system_prompt,
                "user_prompt": self.user_prompt,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class AnswerMetricScores(Contract):
    citation_validity: float = Field(ge=0, le=1)
    context_precision: float = Field(ge=0, le=1)
    abstention_correctness: float = Field(ge=0, le=1)

    def as_score_dict(self) -> dict[str, float]:
        return self.model_dump()


class CalibrationLabel(Contract):
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    answer: str
    abstained: bool = False
    citations: tuple[str, ...] = ()
    contexts: tuple[Passage, ...]
    human_faithful: bool
    human_relevant: bool
    annotator: str = Field(min_length=1)


class CalibrationAgreement(Contract):
    judge_profile: str = Field(min_length=1)
    judge_model: str = Field(min_length=1)
    judge_prompt_version: str = Field(min_length=1)
    sample_count: int = Field(gt=0)
    faithfulness_kappa: float = Field(ge=-1, le=1)
    relevance_kappa: float = Field(ge=-1, le=1)
