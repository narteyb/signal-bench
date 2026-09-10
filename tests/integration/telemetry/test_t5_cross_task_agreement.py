# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import subprocess
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from signal_bench import __version__
from signal_bench.analysis.timing import inference_coverage, samples_for_inference
from signal_bench.ids import new_id
from signal_bench.schema import Result, Run, Target, Task, TelemetrySample
from signal_bench.telemetry import OrchestratorConfig, TelemetryOrchestrator
from tests.integration.telemetry._events import events_of_type, find_event, parse_events
from tests.unit.telemetry._programmable_source import (
    ProgrammableMockConfig,
    ProgrammableMockSource,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sqlalchemy.orm import Session

COVERAGE_AGREEMENT_TOLERANCE = 0.02
FAST_RATE_HZ = 20.0
FAST_DURATION_S = 5.0
SLOW_EXPECTED_HZ = 25.0
SLOW_ACTUAL_HZ = 23.0
SLOW_DURATION_S = 4.0


def test_healthy_cli_run_events_and_partial_decision_agree(tmp_path: Path) -> None:
    db_path = tmp_path / "healthy-cli.db"
    env = os.environ.copy()
    env["SIGNAL_BENCH_LOG_DEST"] = "stderr"
    env["SIGNAL_BENCH_LOG_LEVEL"] = "INFO"
    env.pop("SIGNAL_BENCH_PARTIAL_COVERAGE_THRESHOLD", None)

    result = subprocess.run(
        [
            "uv",
            "run",
            "signal-bench",
            "telemetry",
            "test",
            "--duration",
            "2",
            "--no-fnb58",
            "--quiet",
            "--output",
            "json",
            "--db",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    events = parse_events(result.stderr)
    assert events_of_type(events, "run_started")
    assert len(events_of_type(events, "source_started")) == 2
    assert len(events_of_type(events, "source_stopped")) == 2
    assert events_of_type(events, "run_completed")
    decision = find_event(events, "telemetry_partial_decided")
    assert decision["context"]["partial"] is False
    assert not [event for event in events if event.get("level") in {"WARNING", "ERROR"}]

    engine = create_engine(f"sqlite:///{db_path}")
    maker = sessionmaker(bind=engine)
    try:
        with maker() as session:
            run = session.scalar(select(Run).order_by(Run.started_at.desc()))
            assert run is not None
            assert run.telemetry_partial is False
            assert run.partial_reasons in (None, [])
            result_count = session.scalar(
                select(func.count()).select_from(Result).where(Result.run_id == run.run_id),
            )
            assert result_count == 0
    finally:
        engine.dispose()


def test_single_source_failure_events_partial_decision_and_timing_coverage_agree(
    telemetry_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="signal_bench.telemetry")
    source_a = ProgrammableMockSource(
        ProgrammableMockConfig(name="mock_a", sample_rate_hz=FAST_RATE_HZ),
    )
    source_b = ProgrammableMockSource(
        ProgrammableMockConfig(
            name="mock_b",
            sample_rate_hz=FAST_RATE_HZ,
            fail_after_n_samples=40,
        ),
    )

    run_id = _run_orchestrator_case(
        telemetry_session_factory,
        caplog=caplog,
        sources=[source_a, source_b],
        duration_s=FAST_DURATION_S,
    )
    events = _caplog_events(caplog)
    decision = find_event(events, "telemetry_partial_decided")
    expected = int(decision["context"]["expected_samples"]["mock_b"])
    _add_result_grid(
        telemetry_session_factory,
        run_id=run_id,
        count=expected,
        interval_s=FAST_DURATION_S / expected,
        duration_ms=(FAST_DURATION_S / expected) * 1000.0,
    )

    assert find_event(events, "source_disconnected")["source"] == "mock_b"
    run = _run_row(telemetry_session_factory, run_id)
    assert run.telemetry_partial is True
    assert run.partial_reasons is not None
    assert any("mock_b" in reason for reason in run.partial_reasons)
    assert decision["context"]["partial"] is True
    assert decision["context"]["per_source_coverage"]["mock_b"] == pytest.approx(0.4, abs=0.04)

    with telemetry_session_factory() as session:
        coverage_a = inference_coverage(session, run_id, "mock_a")
        coverage_b = inference_coverage(session, run_id, "mock_b")
    assert coverage_a.coverage_fraction >= 0.97
    assert coverage_a.coverage_fraction == pytest.approx(
        decision["context"]["per_source_coverage"]["mock_a"],
        abs=COVERAGE_AGREEMENT_TOLERANCE,
    )
    assert coverage_b.coverage_fraction == pytest.approx(
        decision["context"]["per_source_coverage"]["mock_b"],
        abs=COVERAGE_AGREEMENT_TOLERANCE,
    )
    assert coverage_b.covered_inferences < coverage_b.total_inferences // 2


def test_slow_source_near_threshold_is_observed_but_not_marked_partial(
    telemetry_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="signal_bench.telemetry")
    source_a = ProgrammableMockSource(
        ProgrammableMockConfig(name="mock_a", sample_rate_hz=SLOW_EXPECTED_HZ),
    )
    source_b = ProgrammableMockSource(
        ProgrammableMockConfig(name="mock_b", sample_rate_hz=SLOW_ACTUAL_HZ),
    )
    source_b.sample_rate_hz = SLOW_EXPECTED_HZ

    run_id = _run_orchestrator_case(
        telemetry_session_factory,
        caplog=caplog,
        sources=[source_a, source_b],
        duration_s=SLOW_DURATION_S,
    )
    events = _caplog_events(caplog)
    decision = find_event(events, "telemetry_partial_decided")
    expected = int(decision["context"]["expected_samples"]["mock_b"])
    _add_result_grid(
        telemetry_session_factory,
        run_id=run_id,
        count=expected,
        interval_s=SLOW_DURATION_S / expected,
        duration_ms=(SLOW_DURATION_S / expected) * 1000.0,
    )

    assert events_of_type(events, "source_disconnected") == []
    assert events_of_type(events, "sample_rate_below_threshold") == []
    assert decision["context"]["partial"] is False
    assert 0.88 <= decision["context"]["per_source_coverage"]["mock_b"] <= 0.96
    run = _run_row(telemetry_session_factory, run_id)
    assert run.telemetry_partial is False

    with telemetry_session_factory() as session:
        coverage_b = inference_coverage(session, run_id, "mock_b")
    assert coverage_b.coverage_fraction == pytest.approx(
        decision["context"]["per_source_coverage"]["mock_b"],
        abs=COVERAGE_AGREEMENT_TOLERANCE,
    )


def test_threshold_override_changes_policy_not_observed_coverage(
    telemetry_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_BENCH_PARTIAL_COVERAGE_THRESHOLD", "0.30")
    caplog.set_level(logging.INFO, logger="signal_bench.telemetry")
    source_a = ProgrammableMockSource(
        ProgrammableMockConfig(name="mock_a", sample_rate_hz=FAST_RATE_HZ),
    )
    source_b = ProgrammableMockSource(
        ProgrammableMockConfig(
            name="mock_b",
            sample_rate_hz=FAST_RATE_HZ,
            fail_after_n_samples=40,
        ),
    )

    run_id = _run_orchestrator_case(
        telemetry_session_factory,
        caplog=caplog,
        sources=[source_a, source_b],
        duration_s=FAST_DURATION_S,
    )
    events = _caplog_events(caplog)
    decision = find_event(events, "telemetry_partial_decided")
    expected = int(decision["context"]["expected_samples"]["mock_b"])
    _add_result_grid(
        telemetry_session_factory,
        run_id=run_id,
        count=expected,
        interval_s=FAST_DURATION_S / expected,
        duration_ms=(FAST_DURATION_S / expected) * 1000.0,
    )

    assert find_event(events, "source_disconnected")["source"] == "mock_b"
    assert decision["context"]["threshold_frac"] == 0.3
    assert decision["context"]["partial"] is False
    run = _run_row(telemetry_session_factory, run_id)
    assert run.telemetry_partial is False

    with telemetry_session_factory() as session:
        coverage_b = inference_coverage(session, run_id, "mock_b")
    assert coverage_b.coverage_fraction == pytest.approx(
        decision["context"]["per_source_coverage"]["mock_b"],
        abs=COVERAGE_AGREEMENT_TOLERANCE,
    )
    assert coverage_b.coverage_fraction > decision["context"]["threshold_frac"]


def test_per_inference_attribution_exposes_clustered_partial_gap(
    telemetry_session_factory: sessionmaker[Session],
) -> None:
    run_id = _create_synthetic_partial_run(telemetry_session_factory)

    with telemetry_session_factory() as session:
        early_samples = samples_for_inference(session, run_id, 10, "fnb58")
        silent_samples = samples_for_inference(
            session,
            run_id,
            90,
            "fnb58",
            include_bracketing=False,
            partial_run_aware=False,
        )
        report = inference_coverage(session, run_id, "fnb58")
        run = session.get(Run, run_id)
        assert run is not None
        assert run.telemetry_partial is True
        assert run.partial_reasons == ["fnb58: coverage=60%, threshold=90%, samples=60/100"]

        with pytest.warns(match="zero fnb58 samples"):
            samples_for_inference(
                session,
                run_id,
                90,
                "fnb58",
                include_bracketing=False,
                partial_run_aware=True,
            )

    assert early_samples
    assert silent_samples == []
    assert report.covered_inferences == 60
    assert report.total_inferences == 100
    assert report.coverage_fraction == pytest.approx(0.6)


def _run_orchestrator_case(
    session_factory: sessionmaker[Session],
    *,
    caplog: pytest.LogCaptureFixture,
    sources: Sequence[ProgrammableMockSource],
    duration_s: float,
) -> str:
    caplog.clear()

    async def _run() -> str:
        run_id = _create_run(session_factory)
        orchestrator = TelemetryOrchestrator(
            session_factory,
            OrchestratorConfig(batch_size=1, flush_interval_s=0.005),
        )
        await orchestrator.start_run(run_id, sources)
        await asyncio.sleep(duration_s)
        await orchestrator.stop_run()
        _finish_run(session_factory, run_id)
        return run_id

    return asyncio.run(_run())


def _caplog_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for record in caplog.records:
        if not hasattr(record, "event"):
            continue
        structured = cast("Any", record)
        events.append(
            {
                "event": structured.event,
                "source": structured.source,
                "level": record.levelname,
                "context": structured.context,
            },
        )
    return events


def _create_run(session_factory: sessionmaker[Session]) -> str:
    with session_factory() as session:
        target = Target(name=f"target-{new_id()}", kind="t5-integration")
        task = Task(name=f"task-{new_id()}", version="test")
        session.add_all([target, task])
        session.flush()
        run = Run(
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=dt.datetime.now(dt.UTC),
            status="running",
            corpus_tag="X",
            warmup_count=0,
            measurement_count=0,
            signal_bench_version=__version__,
        )
        session.add(run)
        session.commit()
        return run.run_id


def _finish_run(session_factory: sessionmaker[Session], run_id: str) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        run.status = "completed"
        run.finished_at = dt.datetime.now(dt.UTC)
        session.commit()


def _add_result_grid(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
    count: int,
    interval_s: float,
    duration_ms: float,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        for sequence in range(count):
            session.add(
                Result(
                    run_id=run_id,
                    sequence=sequence,
                    started_at=run.started_at + dt.timedelta(seconds=sequence * interval_s),
                    duration_ms=duration_ms,
                ),
            )
        run.measurement_count = count
        session.commit()


def _create_synthetic_partial_run(session_factory: sessionmaker[Session]) -> str:
    with session_factory() as session:
        target = Target(name=f"target-{new_id()}", kind="t5-integration")
        task = Task(name=f"task-{new_id()}", version="test")
        session.add_all([target, task])
        session.flush()
        run = Run(
            target_id=target.target_id,
            task_id=task.task_id,
            started_at=dt.datetime.now(dt.UTC),
            finished_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=1),
            status="completed",
            corpus_tag="X",
            warmup_count=0,
            measurement_count=100,
            signal_bench_version=__version__,
            telemetry_partial=True,
            telemetry_partial_sources=["fnb58"],
            partial_reasons=["fnb58: coverage=60%, threshold=90%, samples=60/100"],
        )
        session.add(run)
        session.flush()
        for sequence in range(100):
            session.add(
                Result(
                    run_id=run.run_id,
                    sequence=sequence,
                    started_at=run.started_at + dt.timedelta(seconds=sequence * 0.01),
                    duration_ms=5.0,
                ),
            )
        for sequence in range(60):
            session.add(
                TelemetrySample(
                    run_id=run.run_id,
                    timestamp=run.started_at + dt.timedelta(seconds=sequence * 0.01 + 0.002),
                    source="fnb58",
                    metric="power",
                    value=1.0,
                ),
            )
        session.commit()
        return run.run_id


def _run_row(session_factory: sessionmaker[Session], run_id: str) -> Run:
    with session_factory() as session:
        run = session.get(Run, run_id)
        assert run is not None
        session.expunge(run)
        return run
