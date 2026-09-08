"""SQLAlchemy persistence models for the platform core."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DatasetRow(TimestampMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("name", "version", "split"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    split: Mapped[str] = mapped_column(String(50), nullable=False)
    license_name: Mapped[str] = mapped_column(String(200), nullable=False)


class CorpusVersionRow(TimestampMixin, Base):
    __tablename__ = "corpus_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "content_hash"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DocumentRow(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("corpus_version_id", "external_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    corpus_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("corpus_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)


class QueryRow(TimestampMixin, Base):
    __tablename__ = "queries"
    __table_args__ = (UniqueConstraint("dataset_id", "external_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class QrelRow(TimestampMixin, Base):
    __tablename__ = "qrels"
    __table_args__ = (
        UniqueConstraint("query_id", "document_id"),
        CheckConstraint("relevance >= 0", name="relevance_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)


class IndexVersionRow(TimestampMixin, Base):
    __tablename__ = "index_versions"
    __table_args__ = (
        UniqueConstraint("corpus_version_id", "configuration_hash"),
        CheckConstraint("dimension = 384", name="dimension_supported"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    corpus_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("corpus_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    corpus_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized: Mapped[bool] = mapped_column(nullable=False)
    hnsw_parameters: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    bm25_artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    total_document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedded_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="building", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentEmbeddingRow(TimestampMixin, Base):
    __tablename__ = "document_embeddings"
    __table_args__ = (
        UniqueConstraint("document_id", "index_version_id"),
        Index(
            "ix_document_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    index_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(384).with_variant(JSON(), "sqlite"), nullable=False
    )


class EvalRunRow(TimestampMixin, Base):
    __tablename__ = "eval_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    completed_queries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_queries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    git_commit: Mapped[str | None] = mapped_column(String(64))
    image_digest: Mapped[str | None] = mapped_column(String(255))
    index_fingerprints: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalRunVariantRow(Base):
    __tablename__ = "eval_run_variants"
    __table_args__ = (UniqueConstraint("eval_run_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    eval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EvalQueryResultRow(TimestampMixin, Base):
    __tablename__ = "eval_query_results"
    __table_args__ = (
        UniqueConstraint("eval_run_id", "variant", "query_id"),
        Index("ix_eval_query_results_run_variant", "eval_run_id", "variant"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    eval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_id: Mapped[UUID] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant: Mapped[str] = mapped_column(String(100), nullable=False)
    ranked_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stage_timings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    generation_record: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    deterministic_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    judge_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    token_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8), nullable=False, default=Decimal("0")
    )


class JobRow(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        Index("ix_jobs_claimable", "status", "available_at", "created_at"),
        Index("ix_jobs_expired_lease", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_by: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
