"""separate Linux SSH endpoint from relay source

Revision ID: 20260821_0002
Revises: 20260820_0001
Create Date: 2026-08-21 13:31:00
"""

import sqlalchemy as sa
from alembic import op

revision = "20260821_0002"
down_revision = "20260820_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("linux_hosts", sa.Column("relay_source_ip", sa.String(length=45)))


def downgrade() -> None:
    op.drop_column("linux_hosts", "relay_source_ip")
