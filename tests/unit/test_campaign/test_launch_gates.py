# SPDX-License-Identifier: Apache-2.0
"""Exercise the actual launch-tier runner's preflight and completion paths."""
# ruff: noqa: T201, PLR0913 -- emit reviewable refusal evidence and parametrize gates

import argparse
import copy
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signal_bench.campaign.launch_gates import validate_boundary
from signal_bench.schema import Base, Result, Run, Target, Task, TelemetrySample

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "launch_runner", ROOT / "scripts/run_launch_tier_cell.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
BOUNDARY = {
    "board": "f401re",
    "shunt_rail": "5v_positive_high_side",
    "interface_inside_boundary": True,
    "usb_vbus": "connected_metered",
    "input_pin": "e5v",
    "jumpers": {"jp5": "e5v"},
}


@pytest.fixture
def prepared(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        target = Target(name="f401re", kind="mcu")
        task = Task(name="kws", version="test")
        session.add_all([target, task])
        session.flush()
        run = Run(
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=dt.datetime.now(dt.UTC),
            status="running",
            corpus_tag="X",
            warmup_count=0,
            measurement_count=999,
            signal_bench_version="test",
            extra={"campaign_id": "test", "boundary_state": {"power_boundary": BOUNDARY}},
        )
        session.add(run)
        session.commit()
        run_id = run.run_id
    yield factory, run_id
    engine.dispose()


def populate(factory, run_id, *, count=20, missing=None, received=170, error=False, temp=35.0):
    stamp = dt.datetime.now(dt.UTC)
    with factory() as session:
        for i in range(count):
            session.add(
                Result(
                    run_id=run_id,
                    sequence=i,
                    started_at=stamp,
                    duration_ms=1500.0,
                    extra={"error": "ERR" if error and i == 0 else None},
                )
            )
        metrics = {
            "ina219": ("voltage", "current", "power"),
            "fnb58": ("voltage", "current", "power"),
            "bme280": ("temperature", "humidity", "pressure"),
        }
        for source, names in metrics.items():
            n = received if source == "ina219" else 200
            for i in range(n):
                for metric in names:
                    if (source, metric) == missing:
                        continue
                    session.add(
                        TelemetrySample(
                            run_id=run_id,
                            timestamp=stamp + dt.timedelta(seconds=i / 10),
                            source=source,
                            metric=metric,
                            value=temp if metric == "temperature" else 1.0,
                        )
                    )
        session.commit()


def finish(prepared, duration=30.0, expected=None):
    factory, run_id = prepared
    runner._finish_run(
        factory,
        run_id,
        [],
        duration_s=duration,
        expected_samples=expected or dict.fromkeys(("ina219", "bme280", "fnb58"), 200),
        capture_duration_s=30.0,
    )
    with factory() as session:
        run = session.get(Run, run_id)
        return run.status, run.extra["acceptance"], run.measurement_count


@pytest.mark.parametrize(
    ("case", "duration", "count", "received", "missing", "gate"),
    [
        ("short_duration", 29.999, 20, 170, None, "duration:"),
        ("too_few_successes", 30.0, 19, 170, None, "iterations:"),
        ("below_coverage_no_grace", 30.0, 20, 169, None, "coverage: ina219"),
        ("missing_temperature", 30.0, 20, 170, ("bme280", "temperature"), "ambient:"),
        ("missing_humidity", 30.0, 20, 170, ("bme280", "humidity"), "ambient:"),
    ],
)
def test_completion_refuses_actuals(prepared, case, duration, count, received, missing, gate):
    populate(*prepared, count=count, received=received, missing=missing)
    status, acceptance, actual_count = finish(prepared, duration)
    assert status == "rejected"
    assert any(reason.startswith(gate) for reason in acceptance["reasons"])
    assert actual_count == count
    print(json.dumps({"case": case, "status": status, **acceptance}, sort_keys=True))


def test_exact_floors_and_out_of_old_band_are_accepted(prepared):
    populate(*prepared, temp=35.0)
    status, acceptance, count = finish(prepared)
    assert status == "completed"
    assert acceptance["coverage"]["ina219"]["fraction"] == 0.85
    assert count == 20
    assert acceptance["reasons"] == []
    print(
        json.dumps({"case": "positive_85pct_30s_20_successes_35C", "status": status, **acceptance})
    )


@pytest.mark.parametrize("source", ["ina219", "fnb58", "bme280"])
def test_each_instrument_required(prepared, source):
    populate(*prepared)
    expected = dict.fromkeys(("ina219", "fnb58", "bme280"), 200)
    expected[source] = 1000
    status, acceptance, _ = finish(prepared, expected=expected)
    assert status == "rejected"
    assert any(reason.startswith(f"coverage: {source}") for reason in acceptance["reasons"])
    print(json.dumps({"case": f"low_coverage_{source}", "status": status, **acceptance}))


def test_error_rows_are_not_successes(prepared):
    populate(*prepared, error=True)
    status, acceptance, count = finish(prepared)
    assert status == "rejected"
    assert count == 19
    assert acceptance["iteration_errors"] == 1


@pytest.mark.parametrize("key", list(BOUNDARY))
def test_each_boundary_field_required(key):
    value = copy.deepcopy(BOUNDARY)
    del value[key]
    with pytest.raises(ValueError, match="boundary:"):
        validate_boundary(value, "f401re")


@pytest.mark.parametrize(
    "vbus", ["isolated or routed", "USB power excluded", "connected_unmetered"]
)
def test_ambiguous_or_unmetered_boundary_refused(vbus):
    value = copy.deepcopy(BOUNDARY)
    value["usb_vbus"] = vbus
    with pytest.raises(ValueError, match="boundary:"):
        validate_boundary(value, "f401re")


def test_boundary_rechecked_at_completion(prepared):
    populate(*prepared)
    factory, run_id = prepared
    with factory() as session:
        run = session.get(Run, run_id)
        run.extra = {"boundary_state": {"power_boundary": "isolated or routed"}}
        session.commit()
    status, acceptance, _ = finish(prepared)
    assert status == "rejected"
    assert any(reason.startswith("boundary:") for reason in acceptance["reasons"])
    print(json.dumps({"case": "incomplete_boundary_at_completion", "status": status, **acceptance}))


def test_real_cli_refuses_missing_boundary(tmp_path):
    db = tmp_path / "must-not-exist.db"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_launch_tier_cell.py"),
            "--target",
            "f401re",
            "--serial-port",
            "/no/hardware",
            "--campaign-id",
            "negative",
            "--db",
            str(db),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--boundary-json" in result.stderr
    assert not db.exists()
    print(
        json.dumps(
            {
                "case": "real_cli_missing_boundary",
                "exit_code": result.returncode,
                "stderr": result.stderr,
                "database_created": db.exists(),
            }
        )
    )


def test_campaign_boundary_change_refused_before_hardware(prepared):
    factory, _ = prepared
    value = copy.deepcopy(BOUNDARY)
    value["usb_vbus"] = "disconnected"
    args = argparse.Namespace(
        db=Path(factory.kw["bind"].url.database),
        campaign_id="test",
        target="f401re",
        structured_boundary=value,
    )
    with pytest.raises(SystemExit, match="campaign stopped"):
        runner._check_campaign_boundary(args)


@pytest.mark.asyncio
async def test_measurement_exception_retains_results_and_duration(monkeypatch):
    class Adapter:
        async def prepare(self, _run_id) -> None:
            pass

        async def measure(self, _task, _iterations) -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(error=None, duration_us=100)
            message = "injected serial failure"
            raise RuntimeError(message)

        async def teardown(self) -> None:
            pass

    class Telemetry:
        async def start_run(self, _run_id, _sources) -> None:
            pass

        async def stop_run(self) -> SimpleNamespace:
            return SimpleNamespace(expected_samples={}, partial=True, failed_sources=[])

    monkeypatch.setattr(runner, "_mark_measurement_started", lambda *_args: None)
    monkeypatch.setattr(runner, "_telemetry_sources", lambda _args: [])
    results, duration, state, error = await runner._capture(
        Adapter(), Telemetry(), None, "test", None, None, 20
    )
    assert len(results) == 1
    assert duration >= 0
    assert "injected serial failure" in error
    assert state.partial


@pytest.mark.parametrize(
    ("case", "duration", "count", "received", "missing", "exit_code"),
    [
        ("short_duration", 29.999, 20, 170, None, 2),
        ("too_few_iterations", 30.0, 19, 170, None, 2),
        ("low_coverage", 30.0, 20, 169, None, 2),
        ("ambient_absent", 30.0, 20, 170, ("bme280", "temperature"), 2),
        ("positive_control", 30.0, 20, 170, None, 0),
    ],
)
def test_main_execution_path_refusals(
    tmp_path, monkeypatch, case, duration, count, received, missing, exit_code
):
    """Replace hardware only; execute real CLI, run creation, completion and JSON output."""
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps(BOUNDARY))
    db = tmp_path / "cli.db"
    output = tmp_path / "records"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--target",
            "f401re",
            "--task",
            "kws",
            "--serial-port",
            "/hardware-fixture",
            "--campaign-id",
            "negative-fixture",
            "--boundary-json",
            str(boundary),
            "--db",
            str(db),
            "--output-root",
            str(output),
            "--skip-upload",
            "--skip-state-preflight",
            "--physical-routing-verified",
            "--fnb58-address",
            "hardware-fixture",
        ],
    )
    monkeypatch.setattr(
        runner, "_run_command", lambda _command: {"returncode": 0, "output": "fixture"}
    )
    monkeypatch.setattr(runner, "_toolchain_manifest", lambda *_args: {"fixture": True})
    monkeypatch.setattr(runner, "_state_preflight", lambda _args: {"fixture": True})

    class Adapter:
        async def prepare(self, _run_id) -> None:
            pass

        async def measure(self, _task, iterations) -> AsyncIterator[SimpleNamespace]:
            for i in range(iterations):
                yield SimpleNamespace(
                    error=None,
                    duration_us=1_000_000,
                    iter_id=i,
                    timestamp=dt.datetime.now(dt.UTC),
                    output={},
                )

        async def teardown(self) -> None:
            pass

    monkeypatch.setattr(runner, "_adapter", lambda *_args, **_kwargs: Adapter())

    async def capture(_adapter, _telemetry, factory, run_id, _args, _task, _iterations) -> tuple:
        populate(factory, run_id, count=0, missing=missing, received=received)
        results = [
            SimpleNamespace(
                error=None,
                duration_us=1_000_000,
                iter_id=i,
                timestamp=dt.datetime.now(dt.UTC),
                output={},
            )
            for i in range(count)
        ]
        state = SimpleNamespace(
            expected_samples=dict.fromkeys(("ina219", "fnb58", "bme280"), 200),
            capture_duration_s=30.0,
            partial=False,
        )
        return results, duration, state, None

    monkeypatch.setattr(runner, "_capture", capture)
    actual_exit = runner.main()
    assert actual_exit == exit_code
    record = json.loads(next(output.glob("*.json")).read_text())
    assert record["status"] == ("completed" if exit_code == 0 else "rejected")
    assert record["acceptance"]["accepted"] == (exit_code == 0)
    print(
        json.dumps(
            {
                "execution_path_case": case,
                "exit_code": actual_exit,
                "acceptance": record["acceptance"],
                "hardware": "injected fixture",
            }
        )
    )
