# SPDX-License-Identifier: Apache-2.0
"""Outlier detection policies for synthesis statistics."""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

OutlierPolicy = Literal["iqr", "zscore", "none"]
MIN_OUTLIER_SAMPLES = 4
ZSCORE_THRESHOLD = 3.0


def apply_outlier_policy(
    samples: Sequence[float],
    policy: OutlierPolicy = "iqr",
) -> tuple[list[float], list[float]]:
    """Return `(clean_samples, outliers)` for the selected policy."""
    values = _validate_samples(samples)
    if policy == "iqr":
        return iqr_outliers(values)
    if policy == "zscore":
        return zscore_outliers(values)
    if policy == "none":
        return none_outliers(values)
    msg = f"unknown outlier policy: {policy}"
    raise ValueError(msg)


def iqr_outliers(samples: Sequence[float]) -> tuple[list[float], list[float]]:
    """Reject samples outside Q1 - 1.5*IQR and Q3 + 1.5*IQR."""
    values = _validate_samples(samples)
    if len(values) < MIN_OUTLIER_SAMPLES:
        return values, []

    q1 = _percentile(values, 25)
    q3 = _percentile(values, 75)
    iqr = q3 - q1
    if iqr == 0:
        return values, []

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    clean = [value for value in values if lower <= value <= upper]
    outliers = [value for value in values if value < lower or value > upper]
    return clean, outliers


def zscore_outliers(samples: Sequence[float]) -> tuple[list[float], list[float]]:
    """Reject samples whose absolute z-score is greater than 3."""
    values = _validate_samples(samples)
    if len(values) < MIN_OUTLIER_SAMPLES:
        return values, []

    mean = statistics.fmean(values)
    stddev = statistics.stdev(values)
    if stddev == 0:
        return values, []

    clean = [value for value in values if abs((value - mean) / stddev) <= ZSCORE_THRESHOLD]
    outliers = [value for value in values if abs((value - mean) / stddev) > ZSCORE_THRESHOLD]
    return clean, outliers


def none_outliers(samples: Sequence[float]) -> tuple[list[float], list[float]]:
    """Keep all samples."""
    return _validate_samples(samples), []


def _validate_samples(samples: Sequence[float]) -> list[float]:
    values = [float(sample) for sample in samples]
    if any(not math.isfinite(value) for value in values):
        msg = "samples must be finite numbers"
        raise ValueError(msg)
    return values


def _percentile(samples: Sequence[float], percentile: float) -> float:
    if not samples:
        msg = "percentile requires at least 1 sample"
        raise ValueError(msg)
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * percentile / 100
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    lower_value = ordered[lower_index]
    upper_value = ordered[upper_index]
    fraction = position - lower_index
    return lower_value + (upper_value - lower_value) * fraction
