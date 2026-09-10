# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from click.testing import CliRunner

from signal_bench_cli.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path


def _alembic(db_path: Path) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_corpus_tag_migration_fresh_legacy_and_downgrade(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.db"
    command.upgrade(_alembic(fresh), "head")
    with sqlite3.connect(fresh) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
    assert "corpus_tag" in columns
    command.downgrade(_alembic(fresh), "0003")
    with sqlite3.connect(fresh) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        columns_after_downgrade = [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
    assert "failures" not in tables
    assert "corpus_tag" not in columns_after_downgrade

    legacy = tmp_path / "legacy.db"
    command.upgrade(_alembic(legacy), "0003")
    with sqlite3.connect(legacy) as connection:
        connection.execute("INSERT INTO targets(target_id, name, kind) VALUES('t', 'mock', 'mock')")
        connection.execute("INSERT INTO tasks(task_id, name, version) VALUES('task', 'kws', 'v')")
        connection.execute(
            "INSERT INTO runs("
            "run_id, target_id, task_id, started_at, status, warmup_count, "
            "measurement_count, signal_bench_version, extra"
            ") VALUES('r', 't', 'task', '2026-05-18', 'completed', 0, 1, 'x', ?)",
            (json.dumps({"kind": "benchmark"}),),
        )
    command.upgrade(_alembic(legacy), "head")
    with sqlite3.connect(legacy) as connection:
        corpus, extra = connection.execute(
            "SELECT corpus_tag, extra FROM runs WHERE run_id = 'r'",
        ).fetchone()
    assert corpus == "X"
    assert json.loads(extra)["pre_protocol"] is True


def test_corpus_tag_check_rejects_invalid_and_accepts_allowlist(tmp_path: Path) -> None:
    db_path = tmp_path / "checks.db"
    command.upgrade(_alembic(db_path), "head")
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO targets(target_id, name, kind) VALUES('t', 'mock', 'mock')")
        connection.execute("INSERT INTO tasks(task_id, name, version) VALUES('task', 'kws', 'v')")
        for corpus in ["X", "N1", "N2", "N3", "N4"]:
            connection.execute(
                "INSERT INTO runs("
                "run_id, target_id, task_id, started_at, status, corpus_tag, "
                "warmup_count, measurement_count, signal_bench_version"
                ") VALUES(?, 't', 'task', '2026-05-18', 'completed', ?, 0, 1, 'x')",
                (f"r-{corpus}", corpus),
            )
        with pytest.raises(sqlite3.IntegrityError, match="ck_runs_corpus_tag"):
            connection.execute(
                "INSERT INTO runs("
                "run_id, target_id, task_id, started_at, status, corpus_tag, "
                "warmup_count, measurement_count, signal_bench_version"
                ") VALUES('bad', 't', 'task', '2026-05-18', 'completed', 'invalid', 0, 1, 'x')",
            )


def test_run_requires_corpus_and_inspect_filters_by_corpus(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"
    runner = CliRunner()

    missing = runner.invoke(
        main,
        ["run", "--task", "kws", "--target", "mock", "--runs", "1", "--db", str(db_path)],
    )
    assert missing.exit_code == 2
    assert "Missing option '--corpus'" in missing.output

    created = runner.invoke(
        main,
        [
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "1",
            "--corpus",
            "X",
            "--db",
            str(db_path),
        ],
    )
    assert created.exit_code == 0, created.output

    inspected = runner.invoke(main, ["inspect", "--db", str(db_path), "--corpus", "X"])
    assert inspected.exit_code == 0, inspected.output
    assert "X" in inspected.output
    assert "kws" in inspected.output


def test_spot_check_lists_pre_protocol_representatives(tmp_path: Path) -> None:
    db_path = tmp_path / "spot.db"
    command.upgrade(_alembic(db_path), "0003")
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO targets(target_id, name, kind) VALUES('t', 'mock', 'mock')")
        connection.execute("INSERT INTO tasks(task_id, name, version) VALUES('task', 'kws', 'v')")
        connection.execute(
            "INSERT INTO runs("
            "run_id, target_id, task_id, started_at, status, warmup_count, "
            "measurement_count, signal_bench_version, extra"
            ") VALUES('legacy', 't', 'task', '2026-05-18', 'completed', 0, 1, 'x', ?)",
            (json.dumps({"kind": "benchmark"}),),
        )
    command.upgrade(_alembic(db_path), "head")

    result = CliRunner().invoke(main, ["spot-check", "--db", str(db_path), "--pre-protocol"])

    assert result.exit_code == 0, result.output
    assert "legacy" in result.output
    assert "mock" in result.output
