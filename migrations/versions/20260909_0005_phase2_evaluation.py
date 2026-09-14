"""Add benchmark metadata and online evaluation records.

Revision ID: 20260909_0005
Revises: 20260909_0004
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0005"
down_revision: str | None = "20260909_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "queries",
        sa.Column("metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "eval_query_results",
        sa.Column("judge_records", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "eval_query_results", sa.Column("scifact_gold_label", sa.String(length=32), nullable=True)
    )
    op.create_table(
        "judge_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("judge_configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("rendered_prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("cache_key", name="pk_judge_cache"),
    )
    op.create_table(
        "online_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("answer_record", sa.JSON(), nullable=False),
        sa.Column("judge_records", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_online_evaluations"),
        sa.UniqueConstraint("trace_id", name="uq_online_evaluations_trace_id"),
    )


def downgrade() -> None:
    op.drop_table("online_evaluations")
    op.drop_table("judge_cache")
    op.drop_column("eval_query_results", "scifact_gold_label")
    op.drop_column("eval_query_results", "judge_records")
    op.drop_column("queries", "metadata")
