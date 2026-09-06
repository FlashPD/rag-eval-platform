"""Dataset and index contracts."""

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


class DocumentEmbedding(Contract):
    document_id: UUID
    index_version_id: UUID
    values: tuple[float, ...]

    @model_validator(mode="after")
    def validate_dimension(self) -> "DocumentEmbedding":
        if len(self.values) != 384:
            raise ValueError("v1 document embeddings must contain exactly 384 values")
        return self
