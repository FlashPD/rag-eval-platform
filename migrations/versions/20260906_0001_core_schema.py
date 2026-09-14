"""Create the core dataset and evaluation schema.

Revision ID: 20260906_0001
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("split", sa.String(length=50), nullable=False),
        sa.Column("license_name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.UniqueConstraint("name", "version", "split", name="uq_datasets_name"),
    )
    op.create_table(
        "corpus_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_corpus_versions_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_corpus_versions"),
        sa.UniqueConstraint("dataset_id", "content_hash", name="uq_corpus_versions_dataset_id"),
    )
    op.create_index("ix_corpus_versions_dataset_id", "corpus_versions", ["dataset_id"])
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["corpus_version_id"],
            ["corpus_versions.id"],
            name="fk_documents_corpus_version_id_corpus_versions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint(
            "corpus_version_id", "external_id", name="uq_documents_corpus_version_id"
        ),
    )
    op.create_index("ix_documents_corpus_version_id", "documents", ["corpus_version_id"])
    op.create_table(
        "queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_queries_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_queries"),
        sa.UniqueConstraint("dataset_id", "external_id", name="uq_queries_dataset_id"),
    )
    op.create_index("ix_queries_dataset_id", "queries", ["dataset_id"])
    op.create_table(
        "qrels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("relevance", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("relevance >= 0", name="ck_qrels_relevance_nonnegative"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_qrels_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["query_id"], ["queries.id"], name="fk_qrels_query_id_queries", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qrels"),
        sa.UniqueConstraint("query_id", "document_id", name="uq_qrels_query_id"),
    )
    op.create_index("ix_qrels_document_id", "qrels", ["document_id"])
    op.create_index("ix_qrels_query_id", "qrels", ["query_id"])
    op.create_table(
        "index_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("corpus_version_id", sa.Uuid(), nullable=False),
        sa.Column("corpus_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("normalized", sa.Boolean(), nullable=False),
        sa.Column("hnsw_parameters", sa.JSON(), nullable=False),
        sa.Column("bm25_artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("total_document_count", sa.Integer(), nullable=False),
        sa.Column("embedded_document_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state", sa.String(length=32), server_default="building", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("dimension = 384", name="ck_index_versions_dimension_supported"),
        sa.ForeignKeyConstraint(
            ["corpus_version_id"],
            ["corpus_versions.id"],
            name="fk_index_versions_corpus_version_id_corpus_versions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_index_versions_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_index_versions"),
        sa.UniqueConstraint(
            "corpus_version_id",
            "configuration_hash",
            name="uq_index_versions_corpus_version_id",
        ),
    )
    op.create_index("ix_index_versions_corpus_version_id", "index_versions", ["corpus_version_id"])
    op.create_index("ix_index_versions_dataset_id", "index_versions", ["dataset_id"])
    op.create_index("ix_index_versions_state", "index_versions", ["state"])
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("completed_queries", sa.Integer(), nullable=False),
        sa.Column("total_queries", sa.Integer(), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("image_digest", sa.String(length=255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_runs"),
    )
    op.create_index("ix_eval_runs_state", "eval_runs", ["state"])
    op.create_table(
        "eval_run_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_runs.id"],
            name="fk_eval_run_variants_eval_run_id_eval_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_run_variants"),
        sa.UniqueConstraint("eval_run_id", "name", name="uq_eval_run_variants_eval_run_id"),
    )
    op.create_index("ix_eval_run_variants_eval_run_id", "eval_run_variants", ["eval_run_id"])
    op.create_table(
        "eval_query_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.Uuid(), nullable=False),
        sa.Column("variant", sa.String(length=100), nullable=False),
        sa.Column("ranked_document_ids", sa.JSON(), nullable=False),
        sa.Column("stage_timings", sa.JSON(), nullable=False),
        sa.Column("generation_record", sa.JSON(), nullable=True),
        sa.Column("deterministic_scores", sa.JSON(), nullable=False),
        sa.Column("judge_scores", sa.JSON(), nullable=False),
        sa.Column("token_cost_usd", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_runs.id"],
            name="fk_eval_query_results_eval_run_id_eval_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["queries.id"],
            name="fk_eval_query_results_query_id_queries",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_query_results"),
        sa.UniqueConstraint(
            "eval_run_id", "variant", "query_id", name="uq_eval_query_results_eval_run_id"
        ),
    )
    op.create_index("ix_eval_query_results_eval_run_id", "eval_query_results", ["eval_run_id"])
    op.create_index("ix_eval_query_results_query_id", "eval_query_results", ["query_id"])
    op.create_index(
        "ix_eval_query_results_run_variant", "eval_query_results", ["eval_run_id", "variant"]
    )


def downgrade() -> None:
    op.drop_table("eval_query_results")
    op.drop_table("eval_run_variants")
    op.drop_table("eval_runs")
    op.drop_table("index_versions")
    op.drop_table("qrels")
    op.drop_table("queries")
    op.drop_table("documents")
    op.drop_table("corpus_versions")
    op.drop_table("datasets")
