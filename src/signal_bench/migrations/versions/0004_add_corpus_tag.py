# SPDX-License-Identifier: Apache-2.0
"""add corpus tag to runs

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

if TYPE_CHECKING:
    from collections.abc import Sequence


def _decode_extra(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return {}


def upgrade() -> None:
    """Add protocol corpus tags and mark legacy rows."""
    op.add_column(
        "runs",
        sa.Column("corpus_tag", sa.Text(), nullable=False, server_default="X"),
    )

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT run_id, extra FROM runs")).mappings()
    for row in rows:
        extra = _decode_extra(row["extra"])
        extra["pre_protocol"] = True
        connection.execute(
            sa.text("UPDATE runs SET extra = :extra WHERE run_id = :run_id"),
            {"extra": json.dumps(extra), "run_id": row["run_id"]},
        )

    with op.batch_alter_table("runs") as batch_op:
        batch_op.create_check_constraint(
            "ck_runs_corpus_tag",
            "corpus_tag IN ('X', 'N1', 'N2', 'N3', 'N4')",
        )
        batch_op.alter_column("corpus_tag", server_default=None)

    op.create_index("idx_runs_corpus_tag", "runs", ["corpus_tag"], unique=False)


def downgrade() -> None:
    """Remove protocol corpus tags from runs."""
    op.drop_index("idx_runs_corpus_tag", table_name="runs")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_constraint("ck_runs_corpus_tag", type_="check")
        batch_op.drop_column("corpus_tag")
