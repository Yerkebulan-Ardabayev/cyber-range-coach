"""Add Stage 1 command recall state and attempt tables.

Revision ID: 20260827_0003
Revises: 20260821_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260827_0003"
down_revision = "20260821_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "command_practice_states",
        sa.Column("technique_id", sa.String(length=120), nullable=False),
        sa.Column("challenge_version", sa.Integer(), nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("practice_cycle", sa.Integer(), nullable=False),
        sa.Column("current_help_levels", sa.JSON(), nullable=False),
        sa.Column("interval_index", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_in_session", sa.Boolean(), nullable=False),
        sa.Column("draft_answer", sa.Text(), nullable=False),
        sa.Column("draft_observation_answer", sa.Text(), nullable=False),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recalled_without_help_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recalled_with_help_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_interpreted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_in_environment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_variant_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("technique_id"),
    )
    op.create_index(
        op.f("ix_command_practice_states_next_due_at"),
        "command_practice_states",
        ["next_due_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_command_practice_states_retry_in_session"),
        "command_practice_states",
        ["retry_in_session"],
        unique=False,
    )
    op.create_table(
        "command_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("technique_id", sa.String(length=120), nullable=False),
        sa.Column("challenge_version", sa.Integer(), nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("practice_cycle", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shell", sa.String(length=30), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("observation_answer", sa.Text(), nullable=False),
        sa.Column("revealed_help", sa.JSON(), nullable=False),
        sa.Column("error_kind", sa.String(length=40), nullable=True),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False),
        sa.Column("observation_correct", sa.Boolean(), nullable=False),
        sa.Column("dont_remember", sa.Boolean(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_command_attempt_idempotency_key"),
    )
    op.create_index(
        op.f("ix_command_attempts_completed_at"),
        "command_attempts",
        ["completed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_command_attempts_technique_id"),
        "command_attempts",
        ["technique_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_command_attempts_technique_id"), table_name="command_attempts")
    op.drop_index(op.f("ix_command_attempts_completed_at"), table_name="command_attempts")
    op.drop_table("command_attempts")
    op.drop_index(
        op.f("ix_command_practice_states_retry_in_session"),
        table_name="command_practice_states",
    )
    op.drop_index(
        op.f("ix_command_practice_states_next_due_at"),
        table_name="command_practice_states",
    )
    op.drop_table("command_practice_states")
