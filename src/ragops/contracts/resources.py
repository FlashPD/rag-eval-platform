"""Dataset and index contracts."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ragops.contracts.base import Contract


class Dataset(Contract):
    id: UUID
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    split: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    created_at: datetime


class IndexBuildState(StrEnum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class IndexVersionSpec(Contract):
    dataset_id: UUID
    corpus_version_id: UUID
    corpus_hash: str = Field(min_length=64, max_length=64)
    configuration_hash: str = Field(min_length=64, max_length=64)
    embedding_model: str = Field(min_length=1)
    dimension: Literal[384] = 384
    normalized: bool
    hnsw_parameters: dict[str, int]
    bm25_artifact_hash: str = Field(min_length=64, max_length=64)
    total_document_count: int = Field(ge=0)


class IndexVersion(IndexVersionSpec):
    id: UUID
    state: IndexBuildState
    embedded_document_count: int = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None = None

    @property
    def fingerprint(self) -> str:
        """Return a portable identity for the corpus and every index artifact.

        The database UUID is deliberately excluded because rebuilding identical
        data in CI creates a different UUID. A fingerprint must survive that move.
        """
        payload = {
            "corpus_hash": self.corpus_hash,
            "configuration_hash": self.configuration_hash,
            "embedding_model": self.embedding_model,
            "dimension": self.dimension,
            "normalized": self.normalized,
            "hnsw_parameters": self.hnsw_parameters,
            "bm25_artifact_hash": self.bm25_artifact_hash,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class DocumentEmbedding(Contract):
    document_id: UUID
    index_version_id: UUID
    values: tuple[float, ...]

    @model_validator(mode="after")
    def validate_dimension(self) -> "DocumentEmbedding":
        if len(self.values) != 384:
            raise ValueError("v1 document embeddings must contain exactly 384 values")
        return self
