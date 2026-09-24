"""Record whether the learner opened the hidden command of a ladder step.

Revision ID: 20260924_0006
Revises: 20260906_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260924_0006"
down_revision = "20260906_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lab_runs",
        sa.Column("help_used", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("lab_runs", sa.Column("help_opened_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("lab_runs", "help_opened_at")
    op.drop_column("lab_runs", "help_used")
