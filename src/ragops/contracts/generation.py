"""Answer-generation contracts."""

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ragops.contracts.base import Contract


class GenerationOutcome(StrEnum):
    OK = "ok"
    ABSTAINED = "abstained"
    CITATION_ERROR = "citation_error"
    SCHEMA_ERROR = "schema_error"
    REFUSAL = "refusal"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SciFactLabel(StrEnum):
    SUPPORT = "SUPPORT"
    CONTRADICT = "CONTRADICT"
    NOT_ENOUGH_INFO = "NOT_ENOUGH_INFO"


class CitedAnswer(Contract):
    """Provider-normalized structured answer before context validation."""

    answer: str = Field(min_length=1, max_length=32_768)
    citations: tuple[str, ...] = ()
    abstained: bool
    confidence: Confidence
    verification_label: SciFactLabel | None = None
    rationale_sentences: dict[str, tuple[int, ...]] = Field(default_factory=dict)

    @field_validator("answer")
    @classmethod
    def reject_blank_answer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer cannot be blank")
        return value


class GenerationRequest(Contract):
    """Rendered prompt and schema requested from any generation provider."""

    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    prompt_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    trace_id: str = Field(min_length=1)
    response_schema: Literal["cited_answer_v1"] = "cited_answer_v1"

    @field_validator("system_prompt", "user_prompt")
    @classmethod
    def reject_blank_prompts(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("generation prompts cannot be blank")
        return value

    @property
    def rendered_prompt_hash(self) -> str:
        """Hash the semantic prompt, excluding its per-call trace identity."""

        canonical = json.dumps(
            {
                "prompt_version": self.prompt_version,
                "response_schema": self.response_schema,
                "system_prompt": self.system_prompt,
                "user_prompt": self.user_prompt,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class Passage(Contract):
    local_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    title: str
    text: str
    retrieval_rank: int = Field(ge=1)
    retrieval_score: float = Field(allow_inf_nan=False)


class TokenUsage(Contract):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_write_input_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_cached_input_tokens(self) -> "TokenUsage":
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("cached and cache-write tokens cannot exceed input tokens")
        return self


class GenerationResult(Contract):
    """Provider response normalized for the answer pipeline."""

    output: CitedAnswer
    usage: TokenUsage
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    generator_configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_request_id: str | None = Field(default=None, min_length=1)
    cache_hit: bool = False


class CitationValidation(Contract):
    """Deterministic citation checks retained for metrics and failure reporting."""

    valid: bool
    unknown_citations: tuple[str, ...] = ()
    duplicate_citations: tuple[str, ...] = ()
    missing_inline_citations: tuple[str, ...] = ()
    missing_required_citation: bool = False
    citations_on_abstention: bool = False

    @model_validator(mode="after")
    def validate_summary(self) -> "CitationValidation":
        has_errors = bool(
            self.unknown_citations
            or self.duplicate_citations
            or self.missing_inline_citations
            or self.missing_required_citation
            or self.citations_on_abstention
        )
        if self.valid == has_errors:
            raise ValueError("citation validity must agree with reported errors")
        return self


class AnswerRequest(Contract):
    query: str = Field(min_length=1, max_length=4_096)
    dataset: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    generator_profile: str = Field(default="default", min_length=1)
    prompt_version: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]*$")


class AnswerResponse(Contract):
    answer: str
    citations: tuple[str, ...]
    abstained: bool
    confidence: Confidence
    verification_label: SciFactLabel | None = None
    rationale_sentences: dict[str, tuple[int, ...]] = Field(default_factory=dict)
    contexts: tuple[Passage, ...]
    usage: TokenUsage
    outcome: GenerationOutcome
    trace_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    generator_configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    rendered_prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_request_id: str | None = Field(default=None, min_length=1)
    cache_hit: bool = False
    citation_validation: CitationValidation | None = None
    error: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_outcome(self) -> "AnswerResponse":
        generated_outcomes = {
            GenerationOutcome.OK,
            GenerationOutcome.ABSTAINED,
            GenerationOutcome.CITATION_ERROR,
        }
        if self.outcome in generated_outcomes:
            if self.citation_validation is None:
                raise ValueError("generated answer outcomes require citation validation")
            if self.error is not None:
                raise ValueError("generated answer outcomes cannot carry a generation error")
            CitedAnswer(
                answer=self.answer,
                citations=self.citations,
                abstained=self.abstained,
                confidence=self.confidence,
                verification_label=self.verification_label,
                rationale_sentences=self.rationale_sentences,
            )
            if self.outcome == GenerationOutcome.OK and (
                self.abstained or not self.citations or not self.citation_validation.valid
            ):
                raise ValueError("ok outcome requires a valid, cited, non-abstained answer")
            if self.outcome == GenerationOutcome.ABSTAINED and (
                not self.abstained or self.citations or not self.citation_validation.valid
            ):
                raise ValueError("abstained outcome requires a valid, uncited abstention")
            if self.outcome == GenerationOutcome.CITATION_ERROR and self.citation_validation.valid:
                raise ValueError("citation_error outcome requires an invalid citation report")
        else:
            if self.citation_validation is not None:
                raise ValueError("generation failures cannot carry citation validation")
            if self.error is None:
                raise ValueError("generation failures require an error message")
        return self
