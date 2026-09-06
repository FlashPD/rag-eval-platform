"""Retrieval configuration and API contracts."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from ragops.contracts.base import Contract


class SparseStageConfig(Contract):
    backend: Literal["bm25s"] = "bm25s"
    k: int = Field(default=100, ge=1, le=1_000)


class DenseStageConfig(Contract):
    model: str = Field(min_length=1)
    k: int = Field(default=100, ge=1, le=1_000)
    index: Literal["hnsw"] = "hnsw"


class FusionStageConfig(Contract):
    method: Literal["rrf", "weighted"] = "rrf"
    k: int = Field(default=60, ge=1)


class RerankStageConfig(Contract):
    model: str = Field(min_length=1)
    candidates: int = Field(default=50, ge=1, le=1_000)
    keep: int = Field(default=10, ge=1, le=1_000)

    @model_validator(mode="after")
    def validate_candidate_window(self) -> "RerankStageConfig":
        if self.keep > self.candidates:
            raise ValueError("rerank.keep cannot exceed rerank.candidates")
        return self


class VariantConfig(Contract):
    """A named retrieval pipeline whose hash changes with any stage setting."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    sparse: SparseStageConfig | None = None
    dense: DenseStageConfig | None = None
    fusion: FusionStageConfig | None = None
    rerank: RerankStageConfig | None = None

    @model_validator(mode="after")
    def validate_pipeline(self) -> "VariantConfig":
        if self.sparse is None and self.dense is None:
            raise ValueError("a variant requires a sparse or dense retrieval stage")
        if self.fusion is not None and (self.sparse is None or self.dense is None):
            raise ValueError("fusion requires both sparse and dense stages")
        if self.sparse is not None and self.dense is not None and self.fusion is None:
            raise ValueError("a variant with sparse and dense stages requires fusion")
        return self

    @property
    def configuration_hash(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class SearchRequest(Contract):
    query: str = Field(min_length=1, max_length=4_096)
    dataset: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)


class RankedHit(Contract):
    document_id: str = Field(min_length=1)
    title: str
    text: str
    rank: int = Field(ge=1)
    score: float
    stage_scores: dict[str, float] = Field(default_factory=dict)


class StageTiming(Contract):
    stage: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)


class SearchResponse(Contract):
    hits: tuple[RankedHit, ...]
    timings: tuple[StageTiming, ...]
    trace_id: str = Field(min_length=1)
    variant_hash: str = Field(min_length=64, max_length=64)
