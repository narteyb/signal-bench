# SPDX-License-Identifier: Apache-2.0
"""Persist experiment measurements into the signal-bench schema."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import signal_bench
from experiments.lib.measurement import InferenceMeasurement, utc_now
from signal_bench.ids import new_id
from signal_bench.schema import Result, Run, Target, Task


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """Target metadata to upsert before a run."""

    name: str
    kind: str
    cpu: str | None
    accelerator: str | None
    ram_mb: int | None
    storage_mb: int | None
    os_name: str | None
    os_version: str | None
    extra: dict[str, Any] | None


class ExperimentWriter:
    """Creates schema rows for Experiment 01."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        """Run Alembic migrations for the experiment database."""
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")
        command.upgrade(cfg, "head")

    def upsert_target(self, spec: TargetSpec, model_hash: str | None = None) -> Target:
        """Create or update a target row by (name, kind)."""
        with self.session_factory() as session:
            target = session.scalar(
                select(Target).where(Target.name == spec.name, Target.kind == spec.kind),
            )
            extra = dict(spec.extra or {})
            if model_hash is not None:
                extra["model_hash"] = model_hash
            if target is None:
                target = Target(target_id=new_id(), name=spec.name, kind=spec.kind)
                session.add(target)
            target.cpu = spec.cpu
            target.accelerator = spec.accelerator
            target.ram_mb = spec.ram_mb
            target.storage_mb = spec.storage_mb
            target.os_name = spec.os_name
            target.os_version = spec.os_version
            target.extra = extra
            session.commit()
            session.refresh(target)
            return target

    def upsert_task(self, config_path: Path) -> Task:
        """Create or update the experiment task row."""
        yaml_hash = sha256_file(config_path)
        with self.session_factory() as session:
            task = session.scalar(
                select(Task).where(
                    Task.name == "llm-nemoclaw-baseline-v1",
                    Task.version == "1",
                ),
            )
            if task is None:
                task = Task(
                    task_id=new_id(),
                    name="llm-nemoclaw-baseline-v1",
                    version="1",
                )
                session.add(task)
            task.family = "llm"
            task.yaml_path = str(config_path)
            task.yaml_hash = yaml_hash
            session.commit()
            session.refresh(task)
            return task

    def create_run(
        self,
        *,
        target_id: str,
        task_id: str,
        warmup_count: int,
        measurement_count: int,
        runtime_name: str,
        runtime_version: str,
        model_name: str,
        model_hash: str,
        quantization: str | None,
        notes: str,
        extra: dict[str, Any],
    ) -> Run:
        """Create a running Run row."""
        with self.session_factory() as session:
            run = Run(
                run_id=new_id(),
                target_id=target_id,
                task_id=task_id,
                started_at=utc_now(),
                status="running",
                corpus_tag="X",
                warmup_count=warmup_count,
                measurement_count=measurement_count,
                git_sha=git_sha(),
                signal_bench_version=signal_bench.__version__,
                runtime_name=runtime_name,
                runtime_version=runtime_version,
                model_name=model_name,
                model_hash=model_hash,
                quantization=quantization,
                notes=notes,
                telemetry_partial=False,
                telemetry_partial_sources=None,
                extra=extra,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def add_results(self, run_id: str, measurements: list[InferenceMeasurement]) -> None:
        """Persist measurements as Result rows."""
        with self.session_factory() as session:
            for sequence, measurement in enumerate(measurements, start=1):
                session.add(
                    Result(
                        result_id=f"{run_id}-{sequence:04d}",
                        run_id=run_id,
                        sequence=sequence,
                        started_at=measurement.started_at,
                        duration_ms=measurement.duration_ms,
                        first_token_ms=measurement.first_token_ms,
                        tokens_in=measurement.tokens_in,
                        tokens_out=measurement.tokens_out,
                        throughput_unit="tok/s",
                        throughput_value=measurement.throughput_value,
                        accuracy_value=None,
                        wh_per_inference=None,
                        extra=measurement.extra,
                    ),
                )
            session.commit()

    def complete_run(self, run_id: str, extra_update: dict[str, Any] | None = None) -> None:
        """Mark a run completed and optionally merge extra JSON fields."""
        with self.session_factory() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise RuntimeError(f"Run {run_id} disappeared before completion")
            if extra_update:
                merged = dict(run.extra or {})
                merged.update(extra_update)
                run.extra = merged
            run.status = "completed"
            run.finished_at = utc_now()
            session.commit()


def make_engine(db_path: Path) -> Engine:
    """Create a SQLAlchemy engine for a signal-bench SQLite database."""
    return create_engine(f"sqlite:///{db_path}")


def session_factory_for(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker for the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def sha256_file(path: Path) -> str:
    """Return SHA256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha() -> str | None:
    """Return current git SHA if available."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    return result.stdout.strip() if result.returncode == 0 else None
