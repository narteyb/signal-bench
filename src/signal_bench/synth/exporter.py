# SPDX-License-Identifier: Apache-2.0
"""Export benchmark DB rows to matrix YAML data."""

from __future__ import annotations

import datetime as dt
import warnings as py_warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import select

from signal_bench.analysis.exceptions import PartialRunWarning, SourceNotInRun
from signal_bench.analysis.timing import samples_for_inference, samples_for_run
from signal_bench.schema import Result, Run, Target, Task
from signal_bench.synth.energy import EnergyStats, compute_energy, wh_per_1000
from signal_bench.synth.matrix_data import CellData, MatrixData, RunData
from signal_bench.synth.variance import VarianceStats, compute_variance

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from signal_bench.synth.matrix_config import MatrixConfig
    from signal_bench.synth.outlier import OutlierPolicy

DEFAULT_OUTPUT_PATH = Path("data/matrices/post-1-data.yml")
DEFAULT_POWER_SOURCE = "fnb58"
DEFAULT_POWER_METRIC = "power"
MIN_POWER_SAMPLES = 2


def export_matrix(  # noqa: PLR0913 - public API exposes pipeline configuration knobs.
    matrix_config: MatrixConfig,
    db_session: Session,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    *,
    generated_at: dt.datetime | None = None,
    power_source: str = DEFAULT_POWER_SOURCE,
    power_metric: str = DEFAULT_POWER_METRIC,
    outlier_policy: OutlierPolicy = "iqr",
) -> MatrixData:
    """Export configured matrix cells from SQLite-backed ORM rows to YAML data."""
    generated = _isoformat_utc(generated_at or dt.datetime.now(dt.UTC))
    cells: list[CellData] = []

    for cell in matrix_config.cells:
        runs = _query_runs(db_session, task_name=cell.task, target_name=cell.target)
        run_data = [
            _build_run_data(
                db_session,
                run,
                power_source=power_source,
                power_metric=power_metric,
                outlier_policy=outlier_policy,
            )
            for run in runs
        ]
        required_runs = cell.required_runs or matrix_config.defaults.required_runs
        coverage = _run_coverage(run_data, required_runs=required_runs)
        cells.append(
            CellData(
                task=cell.task,
                target=cell.target,
                status=_cell_export_status(
                    has_runs=bool(run_data),
                    missing_run_count=coverage["missing_run_count"],
                ),
                runs=run_data,
                required_runs=required_runs,
                eligible_run_count=coverage["eligible_run_count"],
                missing_run_count=coverage["missing_run_count"],
                extra_run_count=coverage["extra_run_count"],
                ineligible_run_count=coverage["ineligible_run_count"],
                coverage_warnings=coverage["coverage_warnings"],
            ),
        )

    matrix_data = MatrixData(
        schema_version=1,
        matrix_name=matrix_config.name,
        generated_at=generated,
        generated_from_runs=sum(len(cell.runs) for cell in cells),
        cells=cells,
    )

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(matrix_data.to_dict(), handle, sort_keys=False)

    return matrix_data


def _run_coverage(run_data: list[RunData], *, required_runs: int) -> dict[str, Any]:
    eligible_count = sum(_is_repeat_eligible(run) for run in run_data)
    missing_count = max(required_runs - eligible_count, 0)
    extra_count = max(eligible_count - required_runs, 0)
    ineligible_count = len(run_data) - eligible_count
    warnings: list[str] = []
    if missing_count:
        warnings.append(
            f"repeat coverage incomplete: required {required_runs}, "
            f"eligible {eligible_count}, missing {missing_count}",
        )
    if ineligible_count:
        warnings.append(f"{ineligible_count} run(s) are not eligible for repeat coverage")
    if extra_count:
        warnings.append(f"{extra_count} extra eligible run(s) beyond required repeat coverage")
    return {
        "eligible_run_count": eligible_count,
        "missing_run_count": missing_count,
        "extra_run_count": extra_count,
        "ineligible_run_count": ineligible_count,
        "coverage_warnings": warnings,
    }


def _cell_export_status(*, has_runs: bool, missing_run_count: int) -> str:
    if not has_runs:
        return "no_data"
    if missing_run_count:
        return "incomplete"
    return "ok"


def _is_repeat_eligible(run: RunData) -> bool:
    repeat_quarantined = any(
        warning.startswith("repeat stats quarantined: ") for warning in run.warnings
    )
    return (
        run.status == "completed"
        and run.duration_s is not None
        and not run.telemetry_partial
        and not repeat_quarantined
    )


def _energy_quarantined(run: Run) -> bool:
    return bool((run.extra or {}).get("energy_quarantined"))


def _energy_quarantine_reason(run: Run) -> str:
    reason = (run.extra or {}).get("energy_quarantine_reason")
    if reason:
        return str(reason)
    return "energy excluded by run metadata"


def _repeat_quarantined(run: Run) -> bool:
    return bool((run.extra or {}).get("repeat_quarantined"))


def _repeat_quarantine_reason(run: Run) -> str:
    reason = (run.extra or {}).get("repeat_quarantine_reason")
    if reason:
        return str(reason)
    return "run excluded from published repeat set by run metadata"


def _query_runs(db_session: Session, *, task_name: str, target_name: str) -> list[Run]:
    statement = (
        select(Run)
        .join(Task, Run.task_id == Task.task_id)
        .join(Target, Run.target_id == Target.target_id)
        .where(Task.name == task_name, Target.name == target_name)
        .order_by(Run.started_at)
    )
    runs = list(db_session.scalars(statement))
    if target_name in {"esp32s3", "f401re", "nano33"}:
        return [
            run
            for run in runs
            if run.corpus_tag != "N3" or (run.extra or {}).get("protocol") == "n3"
        ]
    return runs


def _build_run_data(
    db_session: Session,
    run: Run,
    *,
    power_source: str,
    power_metric: str,
    outlier_policy: OutlierPolicy,
) -> RunData:
    warnings: list[str] = []
    duration_s = _run_duration_s(run)
    if duration_s is None:
        warnings.append("run has no finished_at timestamp")

    latency_stats = _latency_stats(
        db_session,
        run,
        outlier_policy=outlier_policy,
        warnings=warnings,
    )
    measured_result_count = max(len(_query_results(db_session, run.run_id)) - run.warmup_count, 0)
    energy_quarantined = _energy_quarantined(run)
    repeat_quarantined = _repeat_quarantined(run)
    energy_stats = None
    if energy_quarantined:
        warnings.append(f"energy stats quarantined: {_energy_quarantine_reason(run)}")
    else:
        energy_stats = _energy_stats(
            db_session,
            run,
            duration_s=duration_s,
            # Energy integrates the full run interval, so normalize by every
            # post-warmup inference in that interval. IQR filtering is a
            # latency-summary policy and must not change this denominator.
            inference_count=measured_result_count,
            power_source=power_source,
            power_metric=power_metric,
            warnings=warnings,
        )
    if repeat_quarantined:
        warnings.append(f"repeat stats quarantined: {_repeat_quarantine_reason(run)}")

    return RunData(
        run_id=run.run_id,
        started_at=_isoformat_utc(run.started_at),
        status=run.status,
        duration_s=duration_s,
        iterations=run.measurement_count,
        warmup_iterations=run.warmup_count,
        model_hash=run.model_hash,
        quantization=run.quantization,
        telemetry_partial=run.telemetry_partial,
        telemetry_partial_sources=list(run.telemetry_partial_sources or []),
        partial_reasons=list(run.partial_reasons or []),
        partial_inference_warnings=(
            []
            if energy_quarantined or repeat_quarantined
            else _partial_inference_warnings(
                db_session,
                run,
                power_source=power_source,
            )
        ),
        latency_stats=latency_stats,
        energy_stats=energy_stats,
        warnings=warnings,
    )


def _latency_stats(
    db_session: Session,
    run: Run,
    *,
    outlier_policy: OutlierPolicy,
    warnings: list[str],
) -> dict[str, Any] | None:
    results = _query_results(db_session, run.run_id)
    measured = results[run.warmup_count :]
    if not measured:
        warnings.append("run has no measured Result rows after warmup exclusion")
        return None

    stats = compute_variance(
        [result.duration_ms * 1000.0 for result in measured],
        outlier_policy=outlier_policy,
    )
    return _variance_to_latency_dict(stats)


def _query_results(db_session: Session, run_id: str) -> list[Result]:
    statement = select(Result).where(Result.run_id == run_id).order_by(Result.sequence)
    return list(db_session.scalars(statement))


def _partial_inference_warnings(
    db_session: Session,
    run: Run,
    *,
    power_source: str,
) -> list[dict[str, Any]]:
    if not run.telemetry_partial:
        return []
    results = _query_results(db_session, run.run_id)[run.warmup_count :]
    warnings_metadata: list[dict[str, Any]] = []
    for result in results:
        with py_warnings.catch_warnings(record=True) as captured:
            py_warnings.simplefilter("always", PartialRunWarning)
            try:
                samples_for_inference(
                    db_session,
                    run.run_id,
                    result.sequence,
                    power_source,
                    include_bracketing=True,
                    interpolate_at_boundaries=False,
                    partial_run_aware=True,
                )
            except SourceNotInRun:
                return []
        if any(issubclass(item.category, PartialRunWarning) for item in captured):
            warnings_metadata.append(
                {
                    "inference_id": result.sequence,
                    "source": power_source,
                },
            )
    return warnings_metadata


def _energy_stats(  # noqa: PLR0913 - mirrors the data needed for one run summary.
    db_session: Session,
    run: Run,
    *,
    duration_s: float | None,
    inference_count: int,
    power_source: str,
    power_metric: str,
    warnings: list[str],
) -> dict[str, Any] | None:
    if duration_s is None:
        warnings.append("energy stats unavailable for incomplete run")
        return None

    try:
        power_samples = _query_power_samples(
            db_session,
            run,
            power_source=power_source,
            power_metric=power_metric,
        )
    except SourceNotInRun:
        power_samples = []
    if len(power_samples) < MIN_POWER_SAMPLES:
        warnings.append("energy stats unavailable: fewer than 2 power samples")
        return None

    stats = compute_energy(power_samples, run_duration_s=duration_s)
    return _energy_to_dict(stats, inference_count)


def _query_power_samples(
    db_session: Session,
    run: Run,
    *,
    power_source: str,
    power_metric: str,
) -> list[tuple[float, float]]:
    return [
        (_relative_seconds(sample.timestamp, run.started_at), sample.value)
        for sample in samples_for_run(db_session, run.run_id, power_source)
        if sample.metric == power_metric
    ]


def _variance_to_latency_dict(stats: VarianceStats) -> dict[str, Any]:
    return {
        "n_samples": stats.n_samples,
        "n_outliers": stats.n_outliers,
        "mean_us": stats.mean,
        "median_us": stats.median,
        "p95_us": stats.p95,
        "p99_us": stats.p99,
        "stddev_us": stats.stddev,
        "variance_pct": stats.variance_pct,
        "min_us": stats.min,
        "max_us": stats.max,
    }


def _energy_to_dict(stats: EnergyStats, inference_count: int) -> dict[str, Any]:
    return {
        "total_wh": stats.total_wh,
        "avg_power_w": stats.avg_power_w,
        "sample_count": stats.sample_count,
        "duration_s": stats.duration_s,
        "telemetry_coverage": stats.telemetry_coverage,
        "wh_per_1000": wh_per_1000(stats, inference_count),
        "warnings": list(stats.warnings),
        "min_power_w": stats.min_power_w,
        "max_power_w": stats.max_power_w,
    }


def _run_duration_s(run: Run) -> float | None:
    if run.finished_at is None:
        return None
    duration_s = _relative_seconds(run.finished_at, run.started_at)
    return max(duration_s, 0.0)


def _relative_seconds(timestamp: dt.datetime, started_at: dt.datetime) -> float:
    return (_as_utc(timestamp) - _as_utc(started_at)).total_seconds()


def _isoformat_utc(value: dt.datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)
