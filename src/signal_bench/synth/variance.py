# SPDX-License-Identifier: Apache-2.0
"""Variance statistics for Phase 5 measurement samples."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from signal_bench.synth.outlier import OutlierPolicy, _percentile, apply_outlier_policy

MIN_VARIANCE_SAMPLES = 2


@dataclass(frozen=True, slots=True)
class VarianceStats:
    """Statistical summary after optional outlier removal."""

    n_samples: int
    n_outliers: int
    mean: float
    median: float
    p95: float
    p99: float
    stddev: float
    variance_pct: float
    min: float
    max: float


def compute_variance(
    samples: Sequence[float],
    outlier_policy: OutlierPolicy = "iqr",
) -> VarianceStats:
    """Compute hardcoded Post 1 variance metrics for post-warmup samples.

    The caller is responsible for removing warmup samples before calling this
    function. Outlier detection runs before stats are computed. `stddev` is
    sample standard deviation (`ddof=1`). `variance_pct` is coefficient of
    variation: `100 * stddev / abs(mean)`. For a single sample it is `nan`; for
    a zero mean with at least two samples it is `inf`.
    """
    if not samples:
        msg = "compute_variance requires at least 1 sample, got 0"
        raise ValueError(msg)

    clean, outliers = apply_outlier_policy(samples, outlier_policy)
    if not clean:
        msg = "outlier policy removed every sample"
        raise ValueError(msg)

    n_samples = len(clean)
    mean = statistics.fmean(clean)
    median = statistics.median(clean)
    p95 = _percentile(clean, 95)
    p99 = _percentile(clean, 99)
    stddev = statistics.stdev(clean) if n_samples >= MIN_VARIANCE_SAMPLES else 0.0
    variance_pct = _variance_pct(mean, stddev, n_samples)

    return VarianceStats(
        n_samples=n_samples,
        n_outliers=len(outliers),
        mean=mean,
        median=median,
        p95=p95,
        p99=p99,
        stddev=stddev,
        variance_pct=variance_pct,
        min=min(clean),
        max=max(clean),
    )


def _variance_pct(mean: float, stddev: float, n_samples: int) -> float:
    if n_samples < MIN_VARIANCE_SAMPLES:
        return math.nan
    if mean == 0:
        return math.inf
    return 100 * stddev / abs(mean)
