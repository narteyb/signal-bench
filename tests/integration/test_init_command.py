# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from click.testing import CliRunner
from sqlalchemy import create_engine, inspect, text

from signal_bench_cli.__main__ import main

EXPECTED_TABLES = {
    "failures",
    "targets",
    "tasks",
    "runs",
    "results",
    "telemetry_samples",
}


def _row_count(db_path: Path, table: str) -> int:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
    finally:
        engine.dispose()


def test_init_creates_database_with_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "signal-bench.db"
    result = CliRunner().invoke(main, ["init", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert db_path.exists()

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES | {"alembic_version"}
        for table in EXPECTED_TABLES:
            assert _row_count(db_path, table) == 0
    finally:
        engine.dispose()


def test_init_adds_telemetry_partial_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "signal-bench.db"
    result = CliRunner().invoke(main, ["init", "--db", str(db_path)])

    assert result.exit_code == 0, result.output

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        columns = {column["name"]: column for column in inspect(engine).get_columns("runs")}
        assert "telemetry_partial" in columns
        assert "telemetry_partial_sources" in columns
        assert columns["telemetry_partial"]["nullable"] is False
    finally:
        engine.dispose()


def test_init_existing_db_without_force_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "signal-bench.db"
    first = CliRunner().invoke(main, ["init", "--db", str(db_path)])
    second = CliRunner().invoke(main, ["init", "--db", str(db_path)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 1
    assert "Database already exists" in second.output
    assert "--force" in second.output


def test_init_force_recreates(tmp_path: Path) -> None:
    db_path = tmp_path / "signal-bench.db"
    first = CliRunner().invoke(main, ["init", "--db", str(db_path)])
    second = CliRunner().invoke(main, ["init", "--db", str(db_path), "--force"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert db_path.exists()
