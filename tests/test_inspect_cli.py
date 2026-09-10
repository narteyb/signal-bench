# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sqlite3

from click.testing import CliRunner

from signal_bench_cli.__main__ import main


def test_inspect_flags_independent_and_combined(tmp_path) -> None:
    db_path = tmp_path / "inspect.db"
    runner = CliRunner()
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
    with sqlite3.connect(db_path) as connection:
        session_date = connection.execute(
            "SELECT date(started_at) FROM runs LIMIT 1",
        ).fetchone()[0]

    for args in (
        ["--corpus", "X"],
        ["--target", "mock"],
        ["--task", "kws"],
        ["--session", session_date],
        ["--corpus", "X", "--target", "mock", "--task", "kws"],
    ):
        result = runner.invoke(main, ["inspect", "--db", str(db_path), *args])
        assert result.exit_code == 0, result.output
        assert "kws" in result.output


def test_inspect_empty_failure_view_is_clean(tmp_path) -> None:
    result = CliRunner().invoke(
        main,
        ["inspect", "--db", str(tmp_path / "empty.db"), "--failures"],
    )
    assert result.exit_code == 0, result.output
    assert "signal-bench failures" in result.output
