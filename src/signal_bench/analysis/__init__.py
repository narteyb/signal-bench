# SPDX-License-Identifier: Apache-2.0
"""Analysis helpers for benchmark telemetry and result data."""

from signal_bench.analysis._reports import (
    ClockSkewReport,
    InferenceCoverageDetail,
    InferenceCoverageReport,
)
from signal_bench.analysis.exceptions import InferenceNotFound, PartialRunWarning, SourceNotInRun
from signal_bench.analysis.timing import (
    clock_skew,
    inference_coverage,
    samples_for_inference,
    samples_for_run,
)

__all__ = [
    "ClockSkewReport",
    "InferenceCoverageDetail",
    "InferenceCoverageReport",
    "InferenceNotFound",
    "PartialRunWarning",
    "SourceNotInRun",
    "clock_skew",
    "inference_coverage",
    "samples_for_inference",
    "samples_for_run",
]
