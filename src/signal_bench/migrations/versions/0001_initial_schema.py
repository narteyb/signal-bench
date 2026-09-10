# SPDX-License-Identifier: Apache-2.0
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial signal-bench schema."""
    op.create_table(
        "targets",
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("cpu", sa.Text(), nullable=True),
        sa.Column("accelerator", sa.Text(), nullable=True),
        sa.Column("ram_mb", sa.Integer(), nullable=True),
        sa.Column("storage_mb", sa.Integer(), nullable=True),
        sa.Column("os_name", sa.Text(), nullable=True),
        sa.Column("os_version", sa.Text(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("target_id"),
        sa.UniqueConstraint("name", "kind", name="uq_targets_name_kind"),
    )
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("family", sa.Text(), nullable=True),
        sa.Column("yaml_path", sa.Text(), nullable=True),
        sa.Column("yaml_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("task_id"),
        sa.UniqueConstraint("name", "version", name="uq_tasks_name_version"),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("warmup_count", sa.Integer(), nullable=False),
        sa.Column("measurement_count", sa.Integer(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=True),
        sa.Column("signal_bench_version", sa.Text(), nullable=False),
        sa.Column("runtime_name", sa.Text(), nullable=True),
        sa.Column("runtime_version", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("model_hash", sa.Text(), nullable=True),
        sa.Column("quantization", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["targets.target_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)
    op.create_index(
        "ix_runs_target_id_started_at",
        "runs",
        ["target_id", "started_at"],
        unique=False,
    )
    op.create_index("ix_runs_task_id_started_at", "runs", ["task_id", "started_at"], unique=False)
    op.create_table(
        "results",
        sa.Column("result_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("first_token_ms", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("throughput_unit", sa.Text(), nullable=True),
        sa.Column("throughput_value", sa.Float(), nullable=True),
        sa.Column("accuracy_value", sa.Float(), nullable=True),
        sa.Column("wh_per_inference", sa.Float(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_results_run_id_sequence"),
    )
    op.create_index("ix_results_run_id", "results", ["run_id"], unique=False)
    op.create_table(
        "telemetry_samples",
        sa.Column("sample_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("sample_id"),
    )
    op.create_index(
        "ix_telemetry_samples_run_id_source_metric",
        "telemetry_samples",
        ["run_id", "source", "metric"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_samples_run_id_timestamp",
        "telemetry_samples",
        ["run_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the initial signal-bench schema."""
    op.drop_index("ix_telemetry_samples_run_id_timestamp", table_name="telemetry_samples")
    op.drop_index("ix_telemetry_samples_run_id_source_metric", table_name="telemetry_samples")
    op.drop_table("telemetry_samples")
    op.drop_index("ix_results_run_id", table_name="results")
    op.drop_table("results")
    op.drop_index("ix_runs_task_id_started_at", table_name="runs")
    op.drop_index("ix_runs_target_id_started_at", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_table("runs")
    op.drop_table("tasks")
    op.drop_table("targets")
