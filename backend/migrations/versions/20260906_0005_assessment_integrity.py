"""Add assessment integrity, structured facts, and terminal ledger state.

Revision ID: 20260906_0005
Revises: 20260827_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260906_0005"
down_revision = "20260827_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lab_runs",
        sa.Column("terminal_input_kinds", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "lab_runs",
        sa.Column(
            "input_integrity", sa.String(length=30), nullable=False, server_default="unverified"
        ),
    )
    op.add_column("lab_runs", sa.Column("input_integrity_reason", sa.String(length=80)))
    op.add_column("lab_runs", sa.Column("terminal_session_id", sa.String(length=80)))

    op.add_column("command_practice_states", sa.Column("eligible_at", sa.DateTime(timezone=True)))
    op.add_column("command_practice_states", sa.Column("last_help_at", sa.DateTime(timezone=True)))
    op.add_column(
        "command_practice_states",
        sa.Column("grading_policy_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        op.f("ix_command_practice_states_eligible_at"),
        "command_practice_states",
        ["eligible_at"],
        unique=False,
    )

    op.create_table(
        "assessment_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("technique_id", sa.String(length=120), nullable=False),
        sa.Column("challenge_version", sa.Integer(), nullable=False),
        sa.Column("grading_policy_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("window_type", sa.String(length=20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.String(length=40)),
        sa.Column("advancement_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("contaminated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assessment_windows_technique_id"),
        "assessment_windows",
        ["technique_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assessment_windows_closed_at"),
        "assessment_windows",
        ["closed_at"],
        unique=False,
    )
    op.create_index(
        "uq_assessment_windows_active_technique",
        "assessment_windows",
        ["technique_id"],
        unique=True,
        sqlite_where=sa.text("closed_at IS NULL AND window_type = 'assessment'"),
    )

    op.create_table(
        "help_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("disclosure_key", sa.String(length=120), nullable=False),
        sa.Column("technique_id", sa.String(length=120), nullable=False),
        sa.Column("challenge_version", sa.Integer(), nullable=False),
        sa.Column("window_id", sa.Integer()),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["window_id"], ["assessment_windows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("disclosure_key", name="uq_help_events_disclosure_key"),
    )
    op.create_index(op.f("ix_help_events_technique_id"), "help_events", ["technique_id"])
    op.create_index(op.f("ix_help_events_window_id"), "help_events", ["window_id"])

    with op.batch_alter_table("command_attempts") as batch_op:
        batch_op.add_column(sa.Column("window_id", sa.Integer()))
        batch_op.add_column(
            sa.Column(
                "attempt_type",
                sa.String(length=20),
                nullable=False,
                server_default="assessment",
            )
        )
        batch_op.add_column(sa.Column("recall_completed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("observation_completed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("structured_observation", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=30),
                nullable=False,
                server_default="verified",
            )
        )
        batch_op.add_column(
            sa.Column("grader_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("grading_policy_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_foreign_key(
            "fk_command_attempts_window_id_assessment_windows",
            "assessment_windows",
            ["window_id"],
            ["id"],
        )
        batch_op.create_index(op.f("ix_command_attempts_window_id"), ["window_id"])

    op.add_column(
        "mission_runs",
        sa.Column("structured_facts", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "mission_runs",
        sa.Column(
            "free_text_review_status",
            sa.String(length=30),
            nullable=False,
            server_default="not_assessed",
        ),
    )
    op.add_column(
        "mission_runs",
        sa.Column("grading_policy_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("mission_runs", "grading_policy_version")
    op.drop_column("mission_runs", "free_text_review_status")
    op.drop_column("mission_runs", "structured_facts")
    with op.batch_alter_table("command_attempts") as batch_op:
        batch_op.drop_index(op.f("ix_command_attempts_window_id"))
        batch_op.drop_constraint(
            "fk_command_attempts_window_id_assessment_windows", type_="foreignkey"
        )
        for name in (
            "grading_policy_version",
            "grader_version",
            "verification_status",
            "structured_observation",
            "observation_completed_at",
            "recall_completed_at",
            "attempt_type",
            "window_id",
        ):
            batch_op.drop_column(name)
    op.drop_index(op.f("ix_help_events_window_id"), table_name="help_events")
    op.drop_index(op.f("ix_help_events_technique_id"), table_name="help_events")
    op.drop_table("help_events")
    op.drop_index("uq_assessment_windows_active_technique", table_name="assessment_windows")
    op.drop_index(op.f("ix_assessment_windows_closed_at"), table_name="assessment_windows")
    op.drop_index(op.f("ix_assessment_windows_technique_id"), table_name="assessment_windows")
    op.drop_table("assessment_windows")
    op.drop_index(
        op.f("ix_command_practice_states_eligible_at"), table_name="command_practice_states"
    )
    op.drop_column("command_practice_states", "grading_policy_version")
    op.drop_column("command_practice_states", "last_help_at")
    op.drop_column("command_practice_states", "eligible_at")
    op.drop_column("lab_runs", "terminal_session_id")
    op.drop_column("lab_runs", "input_integrity_reason")
    op.drop_column("lab_runs", "input_integrity")
    op.drop_column("lab_runs", "terminal_input_kinds")
