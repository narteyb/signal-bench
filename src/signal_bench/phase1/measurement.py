# SPDX-License-Identifier: Apache-2.0
"""Phase 1 telemetry ingestion and joules-per-token computation."""

from __future__ import annotations

import asyncio
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Self

from signal_bench.phase1.runtime import GenerationResult
from signal_bench.telemetry.base import TelemetrySample, TelemetrySource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PowerSeries = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class EnergySummary:
    """Integrated energy summary for a single power source."""

    source: str
    metric: str
    sample_count: int
    total_j: float
    avg_power_w: float
    duration_s: float
    joules_per_token: float
    telemetry_coverage: float


@dataclass(frozen=True, slots=True)
class CrossCheckResult:
    """Dual-meter cross-check result."""

    compared: bool
    source_a: str
    source_b: str
    delta_j: float | None
    relative_delta: float | None
    threshold: float
    flagged: bool
    reason: str


@dataclass(frozen=True, slots=True)
class MeasurementSummary:
    """Run-level measurement summary."""

    primary_source: str
    total_tokens_out: int
    run_duration_s: float
    energy: EnergySummary | None
    cross_check: CrossCheckResult
    source_sample_counts: dict[str, int] = field(default_factory=dict)


class TelemetryRecorder:
    """Collect telemetry source samples in memory for one host slice run."""

    def __init__(self: Self, sources: Sequence[TelemetrySource]) -> None:
        self._sources = tuple(sources)
        self._samples: list[TelemetrySample] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

    @property
    def samples(self: Self) -> tuple[TelemetrySample, ...]:
        """Return captured samples."""
        return tuple(self._samples)

    async def start(self: Self) -> None:
        """Start all configured telemetry sources."""
        if self._running:
            return
        for source in self._sources:
            await source.start()
        self._running = True
        self._tasks = [asyncio.create_task(self._pump(source)) for source in self._sources]

    async def stop(self: Self) -> None:
        """Stop sources and finish the in-memory capture."""
        if not self._running:
            return
        for source in self._sources:
            await source.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._running = False

    async def _pump(self: Self, source: TelemetrySource) -> None:
        async for sample in source.samples():
            self._samples.append(sample)


def summarize_measurement(
    samples: Sequence[TelemetrySample],
    results: Sequence[GenerationResult],
    *,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    primary_source: str,
    cross_check_sources: tuple[str, str] | None = None,
    power_metric: str = "power",
    divergence_threshold: float = 0.10,
) -> MeasurementSummary:
    """Compute joules/token and optional dual-meter cross-check."""
    total_tokens = sum(max(result.tokens_out, 0) for result in results)
    duration_s = max((finished_at - started_at).total_seconds(), 0.0)
    power = power_series_by_source(samples, started_at=started_at)
    counts = {source: len(series) for source, series in power.items()}

    primary_series = power.get(primary_source, ())
    energy = None
    if len(primary_series) >= 2 and total_tokens > 0 and duration_s > 0:
        energy = _energy_summary(
            primary_source,
            power_metric,
            primary_series,
            run_duration_s=duration_s,
            total_tokens=total_tokens,
        )

    cross_check = compare_dual_meter(
        power,
        sources=cross_check_sources,
        threshold=divergence_threshold,
    )
    return MeasurementSummary(
        primary_source=primary_source,
        total_tokens_out=total_tokens,
        run_duration_s=duration_s,
        energy=energy,
        cross_check=cross_check,
        source_sample_counts=counts,
    )


def power_series_by_source(
    samples: Sequence[TelemetrySample],
    *,
    started_at: dt.datetime,
) -> dict[str, PowerSeries]:
    """Extract sorted power series from grouped or scalar telemetry samples."""
    by_source: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for sample in samples:
        values = object.__getattribute__(sample, "values")
        power = _extract_power(values)
        if power is None:
            continue
        timestamp = _as_utc(sample.timestamp)
        offset_s = (timestamp - _as_utc(started_at)).total_seconds()
        if offset_s < 0:
            continue
        by_source[sample.source_name].append((offset_s, power))
    return {
        source: tuple(sorted(series, key=lambda item: item[0]))
        for source, series in by_source.items()
    }


def compare_dual_meter(
    power_by_source: Mapping[str, PowerSeries],
    *,
    sources: tuple[str, str] | None,
    threshold: float,
) -> CrossCheckResult:
    """Compare integrated energy between two power sources."""
    if sources is None:
        return CrossCheckResult(False, "", "", None, None, threshold, False, "not_configured")
    source_a, source_b = sources
    series_a = power_by_source.get(source_a, ())
    series_b = power_by_source.get(source_b, ())
    if len(series_a) < 2 or len(series_b) < 2:
        return CrossCheckResult(
            False,
            source_a,
            source_b,
            None,
            None,
            threshold,
            False,
            "insufficient_samples",
        )
    energy_a = integrate_joules(series_a)
    energy_b = integrate_joules(series_b)
    delta = energy_b - energy_a
    denominator = max(abs(energy_a), abs(energy_b), 1e-9)
    relative = abs(delta) / denominator
    flagged = relative > threshold
    return CrossCheckResult(
        True,
        source_a,
        source_b,
        delta,
        relative,
        threshold,
        flagged,
        "divergent" if flagged else "ok",
    )


def integrate_joules(series: Sequence[tuple[float, float]]) -> float:
    """Integrate a sorted `(seconds, watts)` power series."""
    if len(series) < 2:
        return 0.0
    total = 0.0
    for (t0, p0), (t1, p1) in pairwise(series):
        if t1 <= t0:
            continue
        total += ((max(p0, 0.0) + max(p1, 0.0)) / 2.0) * (t1 - t0)
    return total


def _energy_summary(
    source: str,
    metric: str,
    series: PowerSeries,
    *,
    run_duration_s: float,
    total_tokens: int,
) -> EnergySummary:
    total_j = integrate_joules(series)
    sample_duration = max(series[-1][0] - series[0][0], 0.0)
    return EnergySummary(
        source=source,
        metric=metric,
        sample_count=len(series),
        total_j=total_j,
        avg_power_w=total_j / sample_duration if sample_duration > 0 else math.nan,
        duration_s=sample_duration,
        joules_per_token=total_j / total_tokens,
        telemetry_coverage=min(sample_duration / run_duration_s, 1.0),
    )


def _extract_power(values: Mapping[str, float]) -> float | None:
    if "power" in values:
        return float(values["power"])
    if "power_w" in values:
        return float(values["power_w"])
    if "voltage" in values and "current" in values:
        return float(values["voltage"]) * float(values["current"])
    if "voltage_v" in values and "current_ma" in values:
        return float(values["voltage_v"]) * float(values["current_ma"]) / 1000.0
    return None


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)
