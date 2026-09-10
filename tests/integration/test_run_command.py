# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from signal_bench.schema import Result, Run
from signal_bench.tasks import get_task
from signal_bench_cli.__main__ import main


def test_run_command_dispatches_task_to_mock_and_writes_run(tmp_path: Path) -> None:
    db_path = tmp_path / "signal-bench.db"

    result = CliRunner().invoke(
        main,
        [
            "run",
            "--task",
            "kws",
            "--target",
            "mock",
            "--runs",
            "5",
            "--corpus",
            "X",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Running kws on mock for 5 inferences" in result.output
    assert "Result: 5 inferences" in result.output
    assert "Output hash:" in result.output

    engine = create_engine(f"sqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)
    try:
        with session_factory() as session:
            run = session.scalar(select(Run).order_by(Run.started_at.desc()))
            assert run is not None
            assert run.status == "completed"
            assert run.model_name == "kws"
            assert run.model_hash == get_task("kws").metadata["model_hash"]
            assert run.quantization == "int8"
            assert run.extra is not None
            assert run.extra["target"] == "mock"
            rows = session.scalars(select(Result).where(Result.run_id == run.run_id)).all()
            assert len(rows) == 5
    finally:
        engine.dispose()


def test_run_command_rejects_unknown_task(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        [
            "run",
            "--task",
            "missing",
            "--target",
            "mock",
            "--runs",
            "1",
            "--corpus",
            "X",
            "--db",
            str(tmp_path / "signal-bench.db"),
        ],
    )

    assert result.exit_code == 3
    assert "Unknown task" in result.output
