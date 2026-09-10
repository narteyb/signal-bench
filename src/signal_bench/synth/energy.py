# SPDX-License-Identifier: Apache-2.0
"""Energy metrics for Phase 5 telemetry samples."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PowerSample = tuple[float, float]
MIN_INTEGRATION_SAMPLES = 2
LOW_SAMPLE_WARNING_COUNT = 10


@dataclass(frozen=True, slots=True)
class EnergyStats:
    """Run-level energy summary from power telemetry samples."""

    total_j: float
    total_wh: float
    sample_count: int
    duration_s: float
    avg_power_w: float
    min_power_w: float
    max_power_w: float
    telemetry_coverage: float
    warnings: tuple[str, ...] = ()


def compute_energy(
    power_samples: Sequence[PowerSample],
    *,
    run_duration_s: float | None = None,
) -> EnergyStats:
    """Compute run-level energy with trapezoidal integration.

    `power_samples` must be sorted `(t_seconds, power_watts)` pairs where
    `t_seconds` is relative to run start. If `run_duration_s` is provided,
    `telemetry_coverage` is the sampled time span divided by that run duration.
    Negative power values are clamped to zero with a warning.
    """
    samples, warnings = _clean_samples(power_samples)
    if len(samples) < MIN_INTEGRATION_SAMPLES:
        msg = "trapezoidal integration requires at least 2 samples"
        raise ValueError(msg)

    _validate_strictly_increasing(samples)
    first_t = samples[0][0]
    last_t = samples[-1][0]
    duration_s = last_t - first_t
    if duration_s <= 0:
        msg = "sample duration must be positive"
        raise ValueError(msg)

    if len(samples) < LOW_SAMPLE_WARNING_COUNT:
        warnings.append("energy estimate uses fewer than 10 power samples")

    coverage_denominator = duration_s
    if run_duration_s is not None:
        if not math.isfinite(run_duration_s) or run_duration_s <= 0:
            msg = "run_duration_s must be a finite positive number"
            raise ValueError(msg)
        coverage_denominator = run_duration_s

    raw_coverage = duration_s / coverage_denominator
    telemetry_coverage = min(raw_coverage, 1.0)
    if raw_coverage > 1.0:
        warnings.append("telemetry span exceeds run duration; coverage capped at 1.0")

    total_j = _trapezoidal_energy_j(samples)
    if total_j < 0:
        msg = "total energy cannot be negative"
        raise ValueError(msg)

    powers = [power_w for _, power_w in samples]
    total_wh = total_j / 3600.0
    return EnergyStats(
        total_j=total_j,
        total_wh=total_wh,
        sample_count=len(samples),
        duration_s=duration_s,
        avg_power_w=total_j / duration_s,
        min_power_w=min(powers),
        max_power_w=max(powers),
        telemetry_coverage=telemetry_coverage,
        warnings=tuple(warnings),
    )


def wh_per_1000(stats: EnergyStats, inference_count: int) -> float:
    """Return watt-hours per 1000 inferences for a run-level energy total."""
    if inference_count < 0:
        msg = "inference_count must be non-negative"
        raise ValueError(msg)
    if stats.total_j < 0 or stats.total_wh < 0:
        msg = "energy totals must be non-negative"
        raise ValueError(msg)
    if inference_count == 0:
        return math.inf
    return stats.total_wh / inference_count * 1000.0


def _clean_samples(samples: Sequence[PowerSample]) -> tuple[list[PowerSample], list[str]]:
    cleaned: list[PowerSample] = []
    warnings: list[str] = []
    negative_count = 0

    for timestamp_s, power_w in samples:
        timestamp = float(timestamp_s)
        power = float(power_w)
        if not math.isfinite(timestamp) or not math.isfinite(power):
            msg = "power samples must contain finite timestamps and power values"
            raise ValueError(msg)
        if power < 0:
            negative_count += 1
            power = 0.0
        cleaned.append((timestamp, power))

    if negative_count:
        warnings.append(f"clamped {negative_count} negative power sample(s) to 0 W")
    return cleaned, warnings


def _validate_strictly_increasing(samples: Sequence[PowerSample]) -> None:
    for (t0, _), (t1, _) in pairwise(samples):
        if t1 <= t0:
            msg = "power sample timestamps must be strictly increasing"
            raise ValueError(msg)


def _trapezoidal_energy_j(samples: Sequence[PowerSample]) -> float:
    total_j = 0.0
    for (t0, p0), (t1, p1) in pairwise(samples):
        dt = t1 - t0
        avg_power_w = (p0 + p1) / 2.0
        total_j += avg_power_w * dt
    return total_j
