# SPDX-License-Identifier: Apache-2.0
"""create failures table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create first-class protocol failure records."""
    op.create_table(
        "failures",
        sa.Column("failure_id", sa.Text(), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("corpus_tag", sa.Text(), nullable=False),
        sa.Column("failure_mode", sa.Text(), nullable=False),
        sa.Column("diagnostic_signature", sa.Text(), nullable=False),
        sa.Column("error_log_uri", sa.Text(), nullable=True),
        sa.Column("toolchain_versions", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "corpus_tag IN ('X', 'N1', 'N2', 'N3', 'N4')",
            name="ck_failures_corpus_tag",
        ),
        sa.CheckConstraint(
            "failure_mode IN ("
            "'activation_memory_overflow', "
            "'flash_memory_overflow', "
            "'quantization_conversion_error', "
            "'toolchain_version_skew', "
            "'accuracy_gate_rejected'"
            ")",
            name="ck_failures_failure_mode",
        ),
        sa.ForeignKeyConstraint(["target_id"], ["targets.target_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("failure_id"),
    )
    op.create_index(
        "idx_failures_target_task",
        "failures",
        ["target_id", "task_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop first-class protocol failure records."""
    op.drop_index("idx_failures_target_task", table_name="failures")
    op.drop_table("failures")
