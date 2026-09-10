# SPDX-License-Identifier: Apache-2.0
"""SQLAlchemy schema for signal-bench."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from signal_bench.ids import new_id

CORPUS_TAGS = ("X", "N1", "N2", "N3", "N4")
ACTIVE_CORPUS_TAGS = ("X", "N1", "N3", "N4")
FAILURE_MODES = (
    "activation_memory_overflow",
    "flash_memory_overflow",
    "quantization_conversion_error",
    "toolchain_version_skew",
    "accuracy_gate_rejected",
)


class Base(DeclarativeBase):
    """Base class for all signal-bench ORM models."""


class Target(Base):
    """Benchmark target device or runtime host."""

    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("name", "kind", name="uq_targets_name_kind"),)

    target_id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    cpu: Mapped[str | None] = mapped_column(Text)
    accelerator: Mapped[str | None] = mapped_column(Text)
    ram_mb: Mapped[int | None] = mapped_column(Integer)
    storage_mb: Mapped[int | None] = mapped_column(Integer)
    os_name: Mapped[str | None] = mapped_column(Text)
    os_version: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    runs: Mapped[list[Run]] = relationship(back_populates="target")
    failures: Mapped[list[Failure]] = relationship(back_populates="target")


class Task(Base):
    """Benchmark task definition."""

    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_tasks_name_version"),)

    task_id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str | None] = mapped_column(Text)
    yaml_path: Mapped[str | None] = mapped_column(Text)
    yaml_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
    )

    runs: Mapped[list[Run]] = relationship(back_populates="task")
    failures: Mapped[list[Failure]] = relationship(back_populates="task")


class Run(Base):
    """Single benchmark run for one target and one task."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_target_id_started_at", "target_id", "started_at"),
        Index("ix_runs_task_id_started_at", "task_id", "started_at"),
        Index("ix_runs_status", "status"),
        Index("idx_runs_corpus_tag", "corpus_tag"),
        CheckConstraint(
            "corpus_tag IN ('X', 'N1', 'N2', 'N3', 'N4')",
            name="ck_runs_corpus_tag",
        ),
    )

    run_id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    target_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("targets.target_id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tasks.task_id", ondelete="RESTRICT"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_tag: Mapped[str] = mapped_column(Text, nullable=False)
    warmup_count: Mapped[int] = mapped_column(Integer, nullable=False)
    measurement_count: Mapped[int] = mapped_column(Integer, nullable=False)
    git_sha: Mapped[str | None] = mapped_column(Text)
    signal_bench_version: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_name: Mapped[str | None] = mapped_column(Text)
    runtime_version: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    model_hash: Mapped[str | None] = mapped_column(Text)
    quantization: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    telemetry_partial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )
    telemetry_partial_sources: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    partial_reasons: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    target: Mapped[Target] = relationship(back_populates="runs")
    task: Mapped[Task] = relationship(back_populates="runs")
    results: Mapped[list[Result]] = relationship(back_populates="run")
    telemetry_samples: Mapped[list[TelemetrySample]] = relationship(back_populates="run")


class Failure(Base):
    """Failed protocol cell attempt recorded outside the successful runs table."""

    __tablename__ = "failures"
    __table_args__ = (
        Index("idx_failures_target_task", "target_id", "task_id"),
        CheckConstraint(
            "corpus_tag IN ('X', 'N1', 'N2', 'N3', 'N4')",
            name="ck_failures_corpus_tag",
        ),
        CheckConstraint(
            "failure_mode IN ("
            "'activation_memory_overflow', "
            "'flash_memory_overflow', "
            "'quantization_conversion_error', "
            "'toolchain_version_skew', "
            "'accuracy_gate_rejected'"
            ")",
            name="ck_failures_failure_mode",
        ),
    )

    failure_id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    target_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("targets.target_id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tasks.task_id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_tag: Mapped[str] = mapped_column(Text, nullable=False)
    failure_mode: Mapped[str] = mapped_column(Text, nullable=False)
    diagnostic_signature: Mapped[str] = mapped_column(Text, nullable=False)
    error_log_uri: Mapped[str | None] = mapped_column(Text)
    toolchain_versions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    target: Mapped[Target] = relationship(back_populates="failures")
    task: Mapped[Task] = relationship(back_populates="failures")


class Result(Base):
    """Single measured result in a run."""

    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_results_run_id_sequence"),
        Index("ix_results_run_id", "run_id"),
    )

    result_id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    first_token_ms: Mapped[float | None] = mapped_column(Float)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    throughput_unit: Mapped[str | None] = mapped_column(Text)
    throughput_value: Mapped[float | None] = mapped_column(Float)
    accuracy_value: Mapped[float | None] = mapped_column(Float)
    wh_per_inference: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    run: Mapped[Run] = relationship(back_populates="results")


class TelemetrySample(Base):
    """Telemetry value sampled during a run."""

    __tablename__ = "telemetry_samples"
    __table_args__ = (
        Index("ix_telemetry_samples_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_telemetry_samples_run_id_source_metric", "run_id", "source", "metric"),
    )

    sample_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[Run] = relationship(back_populates="telemetry_samples")
