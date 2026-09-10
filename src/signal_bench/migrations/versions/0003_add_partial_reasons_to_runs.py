# SPDX-License-Identifier: Apache-2.0
"""add partial reasons to runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add telemetry partial decision reasons to runs."""
    op.add_column(
        "runs",
        sa.Column("partial_reasons", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove telemetry partial decision reasons from runs."""
    op.drop_column("runs", "partial_reasons")
