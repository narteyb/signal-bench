# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt
import math
import warnings
from typing import TYPE_CHECKING

import pytest

from signal_bench.analysis.exceptions import InferenceNotFound, PartialRunWarning, SourceNotInRun
from signal_bench.analysis.timing import (
    INTERPOLATION_GAP_MULTIPLE,
    clock_skew,
    inference_coverage,
    samples_for_inference,
    samples_for_run,
)
from signal_bench.schema import Result, Run, Target, Task, TelemetrySample

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

START = dt.datetime(2026, 5, 15, 12, 0, tzinfo=dt.UTC)


def _seed_run(  # noqa: PLR0913 - test fixture helper keeps setup readable.
    session: Session,
    *,
    run_id: str = "run-1",
    started_at: dt.datetime = START,
    finished_at: dt.datetime | None = START + dt.timedelta(seconds=90),
    result_offsets_s: list[float] | None = None,
    duration_ms: float = 40.0,
    telemetry_partial: bool = False,
) -> Run:
    target = Target(target_id=f"target-{run_id}", name=f"target-{run_id}", kind="test")
    task = Task(task_id=f"task-{run_id}", name=f"task-{run_id}", version="test")
    session.add_all([target, task])
    session.flush()
    offsets = result_offsets_s if result_offsets_s is not None else [0.0]
    run = Run(
        run_id=run_id,
        target_id=target.target_id,
        task_id=task.task_id,
        started_at=started_at,
        finished_at=finished_at,
        status="completed",
        corpus_tag="X",
        warmup_count=0,
        measurement_count=len(offsets),
        signal_bench_version="test",
        telemetry_partial=telemetry_partial,
    )
    session.add(run)
    session.flush()
    for sequence, offset_s in enumerate(offsets):
        session.add(
            Result(
                result_id=f"{run_id}-result-{sequence}",
                run_id=run_id,
                sequence=sequence,
                started_at=started_at + dt.timedelta(seconds=offset_s),
                duration_ms=duration_ms,
            ),
        )
    session.flush()
    return run


def _add_samples(  # noqa: PLR0913 - test fixture helper keeps setup readable.
    session: Session,
    run_id: str,
    offsets_s: list[float],
    *,
    source: str = "ina219",
    metric: str = "power",
    values: list[float] | None = None,
) -> None:
    for index, offset_s in enumerate(offsets_s):
        session.add(
            TelemetrySample(
                run_id=run_id,
                timestamp=START + dt.timedelta(seconds=offset_s),
                source=source,
                metric=metric,
                value=(values[index] if values is not None else float(index)),
            ),
        )
    session.flush()


def _offsets(samples: list[TelemetrySample]) -> list[float]:
    return [
        round((sample.timestamp.replace(tzinfo=dt.UTC) - START).total_seconds(), 3)
        for sample in samples
    ]


def test_samples_for_inference_happy_path_returns_boundary_and_interior_samples(
    session: Session,
) -> None:
    _seed_run(session, result_offsets_s=[index * 0.05 for index in range(1000)])
    _add_samples(session, "run-1", [index * 0.02 for index in range(4501)])

    samples = samples_for_inference(session, "run-1", 0, "ina219", include_bracketing=True)

    assert _offsets(samples) == [0.0, 0.02, 0.04]


def test_shorter_than_sample_period_returns_brackets_and_interpolated_boundaries(
    session: Session,
) -> None:
    _seed_run(session, result_offsets_s=[0.105], duration_ms=5.0)
    _add_samples(session, "run-1", [0.10, 0.12], values=[1.0, 2.0])

    bracketed = samples_for_inference(session, "run-1", 0, "ina219")
    interpolated = samples_for_inference(
        session,
        "run-1",
        0,
        "ina219",
        interpolate_at_boundaries=True,
    )

    assert _offsets(bracketed) == [0.1, 0.12]
    assert _offsets(interpolated) == [0.1, 0.105, 0.11, 0.12]
    values_by_offset = {
        offset: sample.value
        for offset, sample in zip(_offsets(interpolated), interpolated, strict=True)
    }
    assert values_by_offset[0.105] == pytest.approx(1.25)
    assert values_by_offset[0.11] == pytest.approx(1.5)


def test_longer_than_sample_period_returns_expected_interior_span(session: Session) -> None:
    _seed_run(session, result_offsets_s=[0.1], duration_ms=200.0)
    _add_samples(session, "run-1", [index * 0.02 for index in range(21)])

    samples = samples_for_inference(session, "run-1", 0, "ina219")

    assert len(samples) == 11
    assert _offsets(samples) == pytest.approx(
        [round(0.1 + index * 0.02, 2) for index in range(11)],
    )


def test_inference_at_start_has_no_before_bracket(session: Session) -> None:
    _seed_run(session, result_offsets_s=[0.0], duration_ms=50.0)
    _add_samples(session, "run-1", [0.0, 0.02, 0.04, 0.06])

    samples = samples_for_inference(session, "run-1", 0, "ina219")

    assert _offsets(samples) == [0.0, 0.02, 0.04, 0.06]


def test_inference_at_end_has_no_after_bracket(session: Session) -> None:
    _seed_run(
        session,
        result_offsets_s=[0.95],
        duration_ms=50.0,
        finished_at=START + dt.timedelta(seconds=1),
    )
    _add_samples(session, "run-1", [0.94, 0.96, 0.98, 1.0])

    samples = samples_for_inference(session, "run-1", 0, "ina219")

    assert _offsets(samples) == [0.94, 0.96, 0.98, 1.0]


def test_gap_larger_than_interpolation_threshold_suppresses_synthetic_boundaries(
    session: Session,
) -> None:
    _seed_run(session, result_offsets_s=[0.12], duration_ms=10.0)
    _add_samples(session, "run-1", [0.0, 0.02, 0.04, 0.10, 0.20, 0.22, 0.24])

    samples = samples_for_inference(
        session,
        "run-1",
        0,
        "ina219",
        interpolate_at_boundaries=True,
    )

    assert INTERPOLATION_GAP_MULTIPLE == 2.0
    assert _offsets(samples) == [0.1, 0.2]


def test_missing_inference_raises(session: Session) -> None:
    _seed_run(session, result_offsets_s=[0.0])
    _add_samples(session, "run-1", [0.0])

    with pytest.raises(InferenceNotFound, match="99"):
        samples_for_inference(session, "run-1", 99, "ina219")


def test_missing_source_raises_with_available_sources(session: Session) -> None:
    _seed_run(session, result_offsets_s=[0.0])
    _add_samples(session, "run-1", [0.0], source="fnb58")

    with pytest.raises(SourceNotInRun, match="fnb58"):
        samples_for_inference(session, "run-1", 0, "ina219")


def test_partial_run_aware_warning_is_opt_in(session: Session) -> None:
    _seed_run(session, result_offsets_s=[0.105], duration_ms=5.0, telemetry_partial=True)
    _add_samples(session, "run-1", [0.0, 0.2])

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        samples_for_inference(session, "run-1", 0, "ina219", partial_run_aware=False)
    assert captured == []

    with pytest.warns(PartialRunWarning, match="zero ina219 samples"):
        samples_for_inference(session, "run-1", 0, "ina219", partial_run_aware=True)


def test_samples_for_run_trims_with_offsets(session: Session) -> None:
    _seed_run(session, finished_at=START + dt.timedelta(seconds=1))
    _add_samples(session, "run-1", [-0.1, 0.0, 0.25, 0.75, 1.1])

    samples = samples_for_run(session, "run-1", "ina219", start_offset_s=0.2, end_offset_s=-0.2)

    assert _offsets(samples) == [0.25, 0.75]


def test_inference_coverage_reports_missing_every_tenth_inference(session: Session) -> None:
    offsets = [index * 0.01 for index in range(1000)]
    _seed_run(session, result_offsets_s=offsets, duration_ms=5.0)
    _add_samples(
        session,
        "run-1",
        [offset + 0.002 for index, offset in enumerate(offsets) if index % 10 != 0],
    )

    report = inference_coverage(session, "run-1", "ina219")

    assert report.total_inferences == 1000
    assert report.covered_inferences == 900
    assert report.missing_inferences == 100
    assert report.coverage_fraction == pytest.approx(0.9)
    assert report.details[0].covered is False
    assert report.details[1].covered is True


def test_clock_skew_stable_case(session: Session) -> None:
    _seed_run(session)
    offsets = [index * 0.1 for index in range(20)]
    _add_samples(session, "run-1", offsets, source="source_a", metric="tick")
    _add_samples(session, "run-1", offsets, source="source_b", metric="tick")

    report = clock_skew(session, "run-1", "source_a", "source_b")

    assert report.drift_pattern == "stable"
    assert report.mean_drift_ms == pytest.approx(0.0)
    assert report.max_abs_drift_ms < 10.0
    assert report.n_pairs == 20


def test_clock_skew_monotonic_case(session: Session) -> None:
    _seed_run(session)
    offsets_a = [index * 0.01 for index in range(40)]
    offsets_b = [offset + index * 0.0001 for index, offset in enumerate(offsets_a)]
    _add_samples(session, "run-1", offsets_a, source="source_a", metric="tick")
    _add_samples(session, "run-1", offsets_b, source="source_b", metric="tick")

    report = clock_skew(session, "run-1", "source_a", "source_b")

    assert report.drift_pattern == "monotonic_a_ahead"
    assert report.mean_drift_ms > 0.0


def test_clock_skew_jittery_case(session: Session) -> None:
    _seed_run(session)
    offsets_a = [index * 0.1 for index in range(20)]
    offsets_b = [
        offset + (0.005 if index % 2 == 0 else -0.004) for index, offset in enumerate(offsets_a)
    ]
    _add_samples(session, "run-1", offsets_a, source="source_a", metric="tick")
    _add_samples(session, "run-1", offsets_b, source="source_b", metric="tick")

    report = clock_skew(session, "run-1", "source_a", "source_b")

    assert report.drift_pattern == "jittery"
    assert math.isclose(report.max_abs_drift_ms, 5.0, abs_tol=0.001)
