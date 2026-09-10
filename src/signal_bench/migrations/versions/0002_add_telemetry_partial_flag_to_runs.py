# SPDX-License-Identifier: Apache-2.0
"""add telemetry partial flag to runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add telemetry partial tracking fields to runs."""
    op.add_column(
        "runs",
        sa.Column(
            "telemetry_partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "runs",
        sa.Column("telemetry_partial_sources", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove telemetry partial tracking fields from runs."""
    op.drop_column("runs", "telemetry_partial_sources")
    op.drop_column("runs", "telemetry_partial")
