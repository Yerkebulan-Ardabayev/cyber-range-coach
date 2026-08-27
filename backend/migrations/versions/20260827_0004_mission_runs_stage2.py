"""Add Stage 2 investigation mission runs.

Revision ID: 20260827_0004
Revises: 20260827_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260827_0004"
down_revision = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mission_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("mission_id", sa.String(length=120), nullable=False),
        sa.Column("mission_version", sa.Integer(), nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("data_variant", sa.String(length=120), nullable=False),
        sa.Column("declared_artifact", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("grader_status", sa.String(length=30), nullable=False),
        sa.Column("grader_reason", sa.Text(), nullable=True),
        sa.Column("explanation_accepted", sa.Boolean(), nullable=False),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_mission_run_idempotency_key"),
    )
    op.create_index(
        op.f("ix_mission_runs_completed_at"),
        "mission_runs",
        ["completed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mission_runs_mission_id"),
        "mission_runs",
        ["mission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mission_runs_mission_id"), table_name="mission_runs")
    op.drop_index(op.f("ix_mission_runs_completed_at"), table_name="mission_runs")
    op.drop_table("mission_runs")
