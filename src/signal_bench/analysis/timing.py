# SPDX-License-Identifier: Apache-2.0
"""Telemetry sample alignment helpers for inference windows."""

from __future__ import annotations

import datetime as dt
import statistics
import warnings
from bisect import bisect_left
from itertools import pairwise
from typing import TYPE_CHECKING

from sqlalchemy import distinct, select

from signal_bench.analysis._reports import (
    ClockSkewReport,
    InferenceCoverageDetail,
    InferenceCoverageReport,
)
from signal_bench.analysis.exceptions import InferenceNotFound, PartialRunWarning, SourceNotInRun
from signal_bench.schema import Result, Run, TelemetrySample

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

INTERPOLATION_GAP_MULTIPLE = 2.0
STABLE_MEAN_DRIFT_MS = 1.0
STABLE_MAX_DRIFT_MS = 10.0
STABLE_STDEV_DRIFT_MS = 1.0
MONOTONIC_TOLERANCE_MS = 0.25
MIN_GAPS_FOR_PERIOD_INFERENCE = 2


def samples_for_inference(  # noqa: PLR0913 - public helper mirrors AD-06's explicit knobs.
    db_session: Session,
    run_id: str,
    inference_id: int,
    source: str,
    *,
    include_bracketing: bool = True,
    interpolate_at_boundaries: bool = False,
    partial_run_aware: bool = False,
) -> list[TelemetrySample]:
    """Return telemetry samples relevant to one inference window.

    The window is ``Result.started_at`` through
    ``Result.started_at + Result.duration_ms``. Returned timestamps use the
    persisted telemetry capture timestamp. For sources without an independent
    device clock, the capture timestamp is the host-side read/notification time.

    With ``include_bracketing=True``, the result includes samples inside the
    window plus the nearest source sample at or before the start boundary and at
    or after the end boundary. With ``interpolate_at_boundaries=True``,
    synthetic boundary samples are inserted when adjacent samples are close
    enough to support linear interpolation.

    If ``partial_run_aware=True``, a ``PartialRunWarning`` is emitted when the
    inference window itself contains zero samples for the requested source.
    """
    result = _get_result(db_session, run_id, inference_id)
    run = result.run or _get_run(db_session, run_id)
    start, end = _result_window(result)
    source_samples = _query_source_samples(db_session, run_id, source)
    selected = _samples_in_window(source_samples, start, end)

    if partial_run_aware and run.telemetry_partial and not selected:
        warnings.warn(
            (
                f"run {run_id} inference {inference_id} has zero {source} "
                "samples inside the inference window"
            ),
            PartialRunWarning,
            stacklevel=2,
        )

    if include_bracketing:
        selected = _with_bracketing(source_samples, selected, start, end)

    if interpolate_at_boundaries:
        selected = _with_boundary_interpolation(source_samples, selected, start, end)

    return _sort_samples(selected)


def samples_for_run(
    db_session: Session,
    run_id: str,
    source: str,
    *,
    start_offset_s: float = 0.0,
    end_offset_s: float = 0.0,
) -> list[TelemetrySample]:
    """Return all source samples for a run, optionally trimmed from run bounds."""
    run = _get_run(db_session, run_id)
    source_samples = _query_source_samples(db_session, run_id, source)
    start = _as_utc(run.started_at) + dt.timedelta(seconds=start_offset_s)
    end = _as_utc(run.finished_at) + dt.timedelta(seconds=end_offset_s) if run.finished_at else None
    return [
        sample
        for sample in source_samples
        if _as_utc(sample.timestamp) >= start and (end is None or _as_utc(sample.timestamp) <= end)
    ]


def inference_coverage(
    db_session: Session,
    run_id: str,
    source: str,
    *,
    min_samples_per_inference: int = 1,
) -> InferenceCoverageReport:
    """Return per-inference source coverage diagnostics for one run."""
    if min_samples_per_inference < 1:
        msg = "min_samples_per_inference must be at least 1"
        raise ValueError(msg)
    results = _query_results(db_session, run_id)
    _query_source_samples(db_session, run_id, source)
    details: list[InferenceCoverageDetail] = []

    for result in results:
        start, end = _result_window(result)
        count = _count_samples_in_window(db_session, run_id, source, start, end)
        covered = count >= min_samples_per_inference
        details.append(
            InferenceCoverageDetail(
                inference_id=result.sequence,
                started_at=start,
                completed_at=end,
                sample_count=count,
                covered=covered,
            ),
        )

    covered_count = sum(1 for detail in details if detail.covered)
    total = len(details)
    return InferenceCoverageReport(
        run_id=run_id,
        source=source,
        total_inferences=total,
        covered_inferences=covered_count,
        missing_inferences=total - covered_count,
        coverage_fraction=covered_count / total if total else 0.0,
        min_samples_per_inference=min_samples_per_inference,
        details=tuple(details),
    )


def clock_skew(
    db_session: Session,
    run_id: str,
    source_a: str,
    source_b: str,
) -> ClockSkewReport:
    """Return nearest-neighbor timestamp drift statistics between two sources."""
    timestamps_a = _source_timestamps(db_session, run_id, source_a)
    timestamps_b = _source_timestamps(db_session, run_id, source_b)
    if not timestamps_a or not timestamps_b:
        return ClockSkewReport(
            run_id=run_id,
            source_a=source_a,
            source_b=source_b,
            mean_drift_ms=0.0,
            median_drift_ms=0.0,
            max_abs_drift_ms=0.0,
            drift_pattern="stable",
            n_pairs=0,
        )

    drifts = [_nearest_drift_ms(timestamp, timestamps_b) for timestamp in timestamps_a]
    mean = statistics.fmean(drifts)
    median = statistics.median(drifts)
    max_abs = max(abs(drift) for drift in drifts)
    return ClockSkewReport(
        run_id=run_id,
        source_a=source_a,
        source_b=source_b,
        mean_drift_ms=mean,
        median_drift_ms=median,
        max_abs_drift_ms=max_abs,
        drift_pattern=_drift_pattern(drifts),
        n_pairs=len(drifts),
    )


def _get_run(db_session: Session, run_id: str) -> Run:
    run = db_session.get(Run, run_id)
    if run is None:
        msg = f"run_id {run_id!r} not found"
        raise InferenceNotFound(msg)
    return run


def _get_result(db_session: Session, run_id: str, inference_id: int) -> Result:
    statement = select(Result).where(Result.run_id == run_id, Result.sequence == inference_id)
    result = db_session.scalar(statement)
    if result is None:
        msg = f"inference_id {inference_id!r} not found for run_id {run_id!r}"
        raise InferenceNotFound(msg)
    return result


def _query_results(db_session: Session, run_id: str) -> list[Result]:
    _get_run(db_session, run_id)
    statement = select(Result).where(Result.run_id == run_id).order_by(Result.sequence)
    return list(db_session.scalars(statement))


def _query_source_samples(db_session: Session, run_id: str, source: str) -> list[TelemetrySample]:
    statement = (
        select(TelemetrySample)
        .where(TelemetrySample.run_id == run_id, TelemetrySample.source == source)
        .order_by(TelemetrySample.timestamp, TelemetrySample.metric, TelemetrySample.sample_id)
    )
    samples = list(db_session.scalars(statement))
    if not samples:
        available = _available_sources(db_session, run_id)
        msg = f"source {source!r} not present for run_id {run_id!r}; available sources: {available}"
        raise SourceNotInRun(msg)
    return samples


def _available_sources(db_session: Session, run_id: str) -> list[str]:
    statement = (
        select(distinct(TelemetrySample.source))
        .where(TelemetrySample.run_id == run_id)
        .order_by(TelemetrySample.source)
    )
    return list(db_session.scalars(statement))


def _source_timestamps(db_session: Session, run_id: str, source: str) -> list[dt.datetime]:
    samples = _query_source_samples(db_session, run_id, source)
    seen: set[dt.datetime] = set()
    timestamps: list[dt.datetime] = []
    for sample in samples:
        timestamp = _as_utc(sample.timestamp)
        if timestamp not in seen:
            seen.add(timestamp)
            timestamps.append(timestamp)
    return timestamps


def _result_window(result: Result) -> tuple[dt.datetime, dt.datetime]:
    start = _as_utc(result.started_at)
    end = start + dt.timedelta(milliseconds=result.duration_ms)
    return start, end


def _samples_in_window(
    samples: list[TelemetrySample],
    start: dt.datetime,
    end: dt.datetime,
) -> list[TelemetrySample]:
    return [sample for sample in samples if start <= _as_utc(sample.timestamp) <= end]


def _with_bracketing(
    source_samples: list[TelemetrySample],
    selected: list[TelemetrySample],
    start: dt.datetime,
    end: dt.datetime,
) -> list[TelemetrySample]:
    samples_by_key = {_sample_key(sample): sample for sample in selected}
    before = _nearest_at_or_before(source_samples, start)
    after = _nearest_at_or_after(source_samples, end)
    if before is not None:
        samples_by_key.update({_sample_key(sample): sample for sample in before})
    if after is not None:
        samples_by_key.update({_sample_key(sample): sample for sample in after})
    return list(samples_by_key.values())


def _with_boundary_interpolation(
    source_samples: list[TelemetrySample],
    selected: list[TelemetrySample],
    start: dt.datetime,
    end: dt.datetime,
) -> list[TelemetrySample]:
    interpolated = list(selected)
    expected_gap_s = _expected_gap_s(source_samples)
    for boundary in (start, end):
        if _has_timestamp_for_all_metrics(selected, boundary):
            continue
        interpolated.extend(_interpolate_boundary(source_samples, boundary, expected_gap_s))
    return interpolated


def _interpolate_boundary(
    source_samples: list[TelemetrySample],
    boundary: dt.datetime,
    expected_gap_s: float | None,
) -> list[TelemetrySample]:
    before = _nearest_at_or_before(source_samples, boundary)
    after = _nearest_at_or_after(source_samples, boundary)
    if before is None or after is None:
        return []

    before_by_metric = {sample.metric: sample for sample in before}
    after_by_metric = {sample.metric: sample for sample in after}
    synthetic: list[TelemetrySample] = []
    for metric, before_sample in before_by_metric.items():
        after_sample = after_by_metric.get(metric)
        if after_sample is None:
            continue
        if before_sample.timestamp == after_sample.timestamp:
            continue
        gap_s = (_as_utc(after_sample.timestamp) - _as_utc(before_sample.timestamp)).total_seconds()
        if expected_gap_s is not None and gap_s > INTERPOLATION_GAP_MULTIPLE * expected_gap_s:
            continue
        synthetic.append(
            TelemetrySample(
                run_id=before_sample.run_id,
                timestamp=boundary,
                source=before_sample.source,
                metric=metric,
                value=_linear_value(before_sample, after_sample, boundary),
            ),
        )
    return synthetic


def _nearest_at_or_before(
    samples: list[TelemetrySample],
    timestamp: dt.datetime,
) -> list[TelemetrySample] | None:
    timestamps = sorted({_as_utc(sample.timestamp) for sample in samples})
    index = bisect_left(timestamps, timestamp)
    chosen = (
        timestamps[index] if index < len(timestamps) and timestamps[index] == timestamp else None
    )
    if chosen is None and index > 0:
        chosen = timestamps[index - 1]
    if chosen is None:
        return None
    return [sample for sample in samples if _as_utc(sample.timestamp) == chosen]


def _nearest_at_or_after(
    samples: list[TelemetrySample],
    timestamp: dt.datetime,
) -> list[TelemetrySample] | None:
    timestamps = sorted({_as_utc(sample.timestamp) for sample in samples})
    index = bisect_left(timestamps, timestamp)
    if index >= len(timestamps):
        return None
    chosen = timestamps[index]
    return [sample for sample in samples if _as_utc(sample.timestamp) == chosen]


def _count_samples_in_window(
    db_session: Session,
    run_id: str,
    source: str,
    start: dt.datetime,
    end: dt.datetime,
) -> int:
    statement = select(TelemetrySample).where(
        TelemetrySample.run_id == run_id,
        TelemetrySample.source == source,
        TelemetrySample.timestamp >= start,
        TelemetrySample.timestamp <= end,
    )
    timestamps = {_as_utc(sample.timestamp) for sample in db_session.scalars(statement)}
    return len(timestamps)


def _has_timestamp_for_all_metrics(samples: list[TelemetrySample], timestamp: dt.datetime) -> bool:
    return any(_as_utc(sample.timestamp) == timestamp for sample in samples)


def _expected_gap_s(samples: list[TelemetrySample]) -> float | None:
    timestamps = sorted({_as_utc(sample.timestamp) for sample in samples})
    gaps = [(right - left).total_seconds() for left, right in pairwise(timestamps) if right > left]
    if len(gaps) < MIN_GAPS_FOR_PERIOD_INFERENCE:
        return None
    return statistics.median(gaps)


def _linear_value(before: TelemetrySample, after: TelemetrySample, timestamp: dt.datetime) -> float:
    start = _as_utc(before.timestamp)
    end = _as_utc(after.timestamp)
    total_s = (end - start).total_seconds()
    if total_s <= 0:
        return before.value
    fraction = (_as_utc(timestamp) - start).total_seconds() / total_s
    return before.value + (after.value - before.value) * fraction


def _nearest_drift_ms(timestamp: dt.datetime, candidates: list[dt.datetime]) -> float:
    index = bisect_left(candidates, timestamp)
    nearest: dt.datetime | None = None
    if index < len(candidates):
        nearest = candidates[index]
    if index > 0:
        previous = candidates[index - 1]
        if nearest is None or abs(previous - timestamp) <= abs(nearest - timestamp):
            nearest = previous
    if nearest is None:
        return 0.0
    return (nearest - timestamp).total_seconds() * 1000.0


def _drift_pattern(drifts: list[float]) -> str:
    mean = statistics.fmean(drifts)
    max_abs = max(abs(drift) for drift in drifts)
    stdev = statistics.pstdev(drifts) if len(drifts) > 1 else 0.0
    if (
        abs(mean) < STABLE_MEAN_DRIFT_MS
        and max_abs < STABLE_MAX_DRIFT_MS
        and stdev < STABLE_STDEV_DRIFT_MS
    ):
        return "stable"

    deltas = [right - left for left, right in pairwise(drifts)]
    if (
        deltas
        and all(delta >= -MONOTONIC_TOLERANCE_MS for delta in deltas)
        and drifts[-1] > drifts[0]
    ):
        return "monotonic_a_ahead"
    if (
        deltas
        and all(delta <= MONOTONIC_TOLERANCE_MS for delta in deltas)
        and drifts[-1] < drifts[0]
    ):
        return "monotonic_b_ahead"
    return "jittery"


def _sort_samples(samples: list[TelemetrySample]) -> list[TelemetrySample]:
    return sorted(samples, key=lambda sample: (_as_utc(sample.timestamp), sample.metric))


def _sample_key(sample: TelemetrySample) -> tuple[int | None, dt.datetime, str, str, float]:
    return (
        sample.sample_id,
        _as_utc(sample.timestamp),
        sample.source,
        sample.metric,
        sample.value,
    )


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)
