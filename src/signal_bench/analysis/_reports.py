# SPDX-License-Identifier: Apache-2.0
"""Dataclass report types for telemetry timing analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt


@dataclass(frozen=True, slots=True)
class InferenceCoverageDetail:
    """Coverage diagnostic for one inference window."""

    inference_id: int
    started_at: dt.datetime
    completed_at: dt.datetime
    sample_count: int
    covered: bool


@dataclass(frozen=True, slots=True)
class InferenceCoverageReport:
    """Per-run source coverage across inference windows."""

    run_id: str
    source: str
    total_inferences: int
    covered_inferences: int
    missing_inferences: int
    coverage_fraction: float
    min_samples_per_inference: int
    details: tuple[InferenceCoverageDetail, ...]


@dataclass(frozen=True, slots=True)
class ClockSkewReport:
    """Post-hoc timestamp drift report for two telemetry sources."""

    run_id: str
    source_a: str
    source_b: str
    mean_drift_ms: float
    median_drift_ms: float
    max_abs_drift_ms: float
    drift_pattern: str
    n_pairs: int
