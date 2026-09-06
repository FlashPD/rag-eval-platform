"""Answer-generation contracts."""

from decimal import Decimal
from enum import StrEnum

from pydantic import Field

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


class Passage(Contract):
    local_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    title: str
    text: str
    retrieval_rank: int = Field(ge=1)
    retrieval_score: float


class TokenUsage(Contract):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)


class AnswerRequest(Contract):
    query: str = Field(min_length=1, max_length=4_096)
    dataset: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    generator_profile: str = Field(default="default", min_length=1)


class AnswerResponse(Contract):
    answer: str
    citations: tuple[str, ...]
    abstained: bool
    confidence: Confidence
    contexts: tuple[Passage, ...]
    usage: TokenUsage
    outcome: GenerationOutcome
    trace_id: str = Field(min_length=1)
