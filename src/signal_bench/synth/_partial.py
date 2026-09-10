# SPDX-License-Identifier: Apache-2.0
"""Partial-run filtering and per-cell aggregation helpers."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

MetricName = Literal["latency_us", "latency_ms", "wh_per_1000", "wh_per_1000_mwh"]
StatisticName = Literal["median", "mean", "stddev", "iqr"]
MIN_IQR_VALUES = 2
T = TypeVar("T", bound="PartialRun")


class PartialRun(Protocol):
    """Run-like object used by partial-aware aggregation helpers."""

    @property
    def run_id(self) -> str:
        """Run identifier."""

    @property
    def latency_stats(self) -> Mapping[str, object] | None:
        """Latency summary fields for this run."""

    @property
    def energy_stats(self) -> Mapping[str, object] | None:
        """Energy summary fields for this run."""

    @property
    def telemetry_partial(self) -> bool:
        """Whether telemetry for this run is partial."""

    @property
    def partial_reasons(self) -> Sequence[str]:
        """Reasons this run is marked partial."""

    @property
    def partial_inference_warnings(self) -> Sequence[dict[str, Any]]:
        """Per-inference warning payloads for partial rows."""

    @property
    def warnings(self) -> Sequence[str]:
        """General run warnings."""


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Per-run row for detail tables and variance chart output."""

    run_id: str
    latency_ms: float | None
    wh_per_1000: float | None
    partial: bool
    partial_reasons: list[str]
    partial_inference_warnings: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CellDetailReport:
    """All exported runs for one cell plus partial-aware counts."""

    runs: list[RunSummary]
    n_total: int
    n_partial: int
    headline_basis: int
    partial_inference_count: int


def filter_non_partial(runs: Sequence[T]) -> list[T]:
    """Return runs eligible for headline aggregates."""
    return [run for run in runs if not run.telemetry_partial and not repeat_quarantined(run)]


def repeat_quarantined(run: PartialRun) -> bool:
    """Return whether a run is excluded from published repeat/headline sets."""
    return any(warning.startswith("repeat stats quarantined: ") for warning in run.warnings)


def cell_headline(
    runs: Sequence[PartialRun],
    metric: MetricName,
    *,
    statistic: StatisticName = "median",
) -> float | None:
    """Compute a headline statistic over non-partial runs."""
    values = [_metric_value(run, metric) for run in filter_non_partial(runs)]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return _statistic(numeric, statistic)


def cell_detail(runs: Sequence[PartialRun]) -> CellDetailReport:
    """Return all run-level details for a cell, including partial markers."""
    summaries = [
        RunSummary(
            run_id=run.run_id,
            latency_ms=_metric_value(run, "latency_ms"),
            wh_per_1000=_metric_value(run, "wh_per_1000"),
            partial=run.telemetry_partial,
            partial_reasons=list(run.partial_reasons),
            partial_inference_warnings=list(run.partial_inference_warnings),
        )
        for run in runs
    ]
    n_partial = sum(1 for run in runs if run.telemetry_partial)
    partial_inference_count = sum(len(run.partial_inference_warnings) for run in runs)
    return CellDetailReport(
        runs=summaries,
        n_total=len(runs),
        n_partial=n_partial,
        headline_basis=len(filter_non_partial(runs)),
        partial_inference_count=partial_inference_count,
    )


def _metric_value(run: PartialRun, metric: MetricName) -> float | None:
    if metric == "latency_us":
        latency_stats = run.latency_stats
        if latency_stats is None or latency_stats.get("median_us") is None:
            return None
        value = latency_stats["median_us"]
        if not isinstance(value, int | float | str):
            return None
        return float(value)
    if metric == "latency_ms":
        latency_us = _metric_value(run, "latency_us")
        return None if latency_us is None else latency_us / 1000.0
    if metric == "wh_per_1000":
        energy_stats = run.energy_stats
        if energy_stats is None or energy_stats.get("wh_per_1000") is None:
            return None
        value = energy_stats["wh_per_1000"]
        if not isinstance(value, int | float | str):
            return None
        return float(value)
    if metric == "wh_per_1000_mwh":
        wh = _metric_value(run, "wh_per_1000")
        return None if wh is None else wh * 1000.0
    msg = f"unknown headline metric: {metric}"
    raise ValueError(msg)


def _statistic(values: list[float], statistic: StatisticName) -> float:
    if statistic == "median":
        return float(statistics.median(values))
    if statistic == "mean":
        return float(statistics.mean(values))
    if statistic == "stddev":
        return float(statistics.stdev(values)) if len(values) > 1 else 0.0
    if statistic == "iqr":
        if len(values) < MIN_IQR_VALUES:
            return 0.0
        quartiles = statistics.quantiles(values, n=4, method="inclusive")
        return float(quartiles[2] - quartiles[0])
    msg = f"unknown headline statistic: {statistic}"
    raise ValueError(msg)
