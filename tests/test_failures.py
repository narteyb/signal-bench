# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from signal_bench.orchestrator import (
    CellSpec,
    Orchestrator,
    OrchestratorConfig,
    ProtocolGateRejected,
)
from signal_bench.schema import Failure
from signal_bench_cli.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path


def _alembic(db_path: Path) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_failures_table_created_constrained_and_fk_enforced(tmp_path: Path) -> None:
    db_path = tmp_path / "failures.db"
    command.upgrade(_alembic(db_path), "head")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert "failures" in tables

        with pytest.raises(sqlite3.IntegrityError, match="ck_failures_failure_mode"):
            connection.execute(
                "INSERT INTO failures("
                "failure_id, attempted_at, target_id, task_id, model_name, model_version, "
                "corpus_tag, failure_mode, diagnostic_signature, toolchain_versions"
                ") VALUES('f', '2026-05-18', 'missing', 'missing', 'm', 'v', 'N4', "
                "'bad_mode', 'sig', '{}')",
            )

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                "INSERT INTO failures("
                "failure_id, attempted_at, target_id, task_id, model_name, model_version, "
                "corpus_tag, failure_mode, diagnostic_signature, toolchain_versions"
                ") VALUES('f2', '2026-05-18', 'missing', 'missing', 'm', 'v', 'N4', "
                "'activation_memory_overflow', 'sig', '{}')",
            )


def test_accuracy_gate_rejection_writes_failure_and_inspect_view(tmp_path: Path) -> None:
    db_path = tmp_path / "gate.db"
    lineage = tmp_path / "lineage.json"
    lineage.write_text(
        """
        {
          "derived_from": "tinyml-kws-ds-cnn-ref-v1",
          "prep_method": "quantization-aware-training",
          "prep_params": {"target_dtype": "int8"},
          "accuracy_retention": {
            "metric": "top1",
            "canonical": 0.943,
            "variant": 0.900,
            "delta_pp": -3.0
          },
          "prep_pipeline_uri": "variant-pipeline://model-prep/v1/kws"
        }
        """,
        encoding="utf-8",
    )

    orchestrator = Orchestrator(OrchestratorConfig(db_path=db_path, archive_root=tmp_path))
    try:
        with pytest.raises(ProtocolGateRejected, match="accuracy gate"):
            asyncio.run(
                orchestrator.run_cell(
                    CellSpec("kws", "mock", 1, "N3", model_lineage_path=lineage),
                ),
            )
    finally:
        orchestrator.close()

    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            failures = session.scalars(select(Failure)).all()
            assert len(failures) == 1
            assert failures[0].failure_mode == "accuracy_gate_rejected"
            assert failures[0].context is not None
            assert failures[0].context["model_lineage"]["accuracy_retention"]["delta_pp"] == -3.0
    finally:
        engine.dispose()

    inspected = CliRunner().invoke(main, ["inspect", "--db", str(db_path), "--failures"])
    assert inspected.exit_code == 0, inspected.output
    assert "accuracy_gate_rejected" in inspected.output
