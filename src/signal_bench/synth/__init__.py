# SPDX-License-Identifier: Apache-2.0
"""Synthesis tooling for Post 1 reports."""

from signal_bench.synth._partial import (
    CellDetailReport,
    RunSummary,
    cell_detail,
    cell_headline,
    filter_non_partial,
)
from signal_bench.synth.chart_data import (
    TIER_1_TARGETS,
    build_chart_data,
    build_hardware_curve,
    build_variance_illustration,
    build_variance_strip,
    build_wh_comparison,
    write_chart_json_files,
)
from signal_bench.synth.energy import EnergyStats, compute_energy, wh_per_1000
from signal_bench.synth.exporter import export_matrix
from signal_bench.synth.matrix_config import (
    DEFAULT_KNOWN_TARGETS,
    MatrixCell,
    MatrixConfig,
    MatrixConfigError,
    load_matrix_config,
)
from signal_bench.synth.matrix_data import CellData, MatrixData, RunData
from signal_bench.synth.outlier import apply_outlier_policy
from signal_bench.synth.report import (
    cell_status,
    find_latency_outliers,
    render_markdown_report,
    status_counts,
)
from signal_bench.synth.variance import VarianceStats, compute_variance

__all__ = [
    "DEFAULT_KNOWN_TARGETS",
    "TIER_1_TARGETS",
    "CellData",
    "CellDetailReport",
    "EnergyStats",
    "MatrixCell",
    "MatrixConfig",
    "MatrixConfigError",
    "MatrixData",
    "RunData",
    "RunSummary",
    "VarianceStats",
    "apply_outlier_policy",
    "build_chart_data",
    "build_hardware_curve",
    "build_variance_illustration",
    "build_variance_strip",
    "build_wh_comparison",
    "cell_detail",
    "cell_headline",
    "cell_status",
    "compute_energy",
    "compute_variance",
    "export_matrix",
    "filter_non_partial",
    "find_latency_outliers",
    "load_matrix_config",
    "render_markdown_report",
    "status_counts",
    "wh_per_1000",
    "write_chart_json_files",
]
