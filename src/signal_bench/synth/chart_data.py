# SPDX-License-Identifier: Apache-2.0
"""Chart.js data preparation for Post 1 matrix exports.

Produces structural Chart.js v4 JSON for the full seven-target curve and for
Post 1's Tier 1 MCU subset. Visual vocabulary (colors, fonts, theme
application) is locked in ``docs/chart-vocabulary.md`` and applied
consumer-side by a downstream blog renderer. The algorithmic contract
(aggregation, target ordering, output files) is in
``docs/chart-data-spec.md``.

Builders accept an optional ``tier`` keyword argument that restricts the
output to a named hardware subset. ``tier=None`` (the default) preserves the
full seven-target behavior locked in T3.5. ``tier="tier1"`` restricts to the
three MCU-class targets (F401RE, Nano 33, ESP32-S3) used in Post 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from signal_bench.synth._partial import (
    cell_detail,
    cell_headline,
    filter_non_partial,
    repeat_quarantined,
)

if TYPE_CHECKING:
    from signal_bench.synth.matrix_data import CellData, MatrixData, RunData

TARGET_ORDER = ("f401re", "nano33", "esp32s3", "pi5", "hailo", "jetson", "m1max", "modal")
TIER_1_TARGETS: tuple[str, ...] = ("f401re", "nano33", "esp32s3")
POST1_FUTURE_TARGETS: tuple[str, ...] = ("pi5", "hailo", "jetson", "m1max")
TARGET_LABELS = {
    "f401re": "F401RE",
    "nano33": "Nano 33",
    "esp32s3": "ESP32-S3",
    "pi5": "Pi 5",
    "hailo": "Hailo",
    "jetson": "Jetson Orin Nano",
    "m1max": "M1 Max",
    "modal": "Modal A10G",
}
TASK_ORDER = ("kws", "ic", "ad")
TASK_LABELS = {"kws": "KWS", "ic": "IC", "ad": "AD"}
DEFAULT_CHART_OUTPUT_DIR = Path("data/charts")

ChartConfig = dict[str, Any]


def build_chart_data(matrix_data: MatrixData) -> dict[str, ChartConfig]:
    """Build all Chart.js configs from exported matrix data.

    Returns the full-curve set (legacy, hardware-curve / wh-comparison /
    variance-illustration) plus the Post 1 Tier 1 variants
    (hardware-curve-tier1 / wh-comparison-tier1 / variance-strip-tier1).
    """
    return {
        "hardware-curve": build_hardware_curve(matrix_data),
        "wh-comparison": build_wh_comparison(matrix_data),
        "variance-illustration": build_variance_illustration(matrix_data),
        "hardware-curve-tier1": build_hardware_curve(matrix_data, tier="tier1"),
        "wh-comparison-tier1": build_wh_comparison(matrix_data, tier="tier1"),
        "variance-strip-tier1": build_variance_strip(matrix_data, tier="tier1"),
    }


def write_chart_json_files(
    matrix_data: MatrixData,
    output_dir: str | Path = DEFAULT_CHART_OUTPUT_DIR,
) -> dict[str, Path]:
    """Write the three canonical chart JSON files and return their paths."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, chart in build_chart_data(matrix_data).items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(chart, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = path
    return written


def build_hardware_curve(
    matrix_data: MatrixData,
    *,
    tier: str | None = None,
) -> ChartConfig:
    """Return a Chart.js line chart: target capability vs median latency.

    Args:
        matrix_data: Matrix export from T3.4.
        tier: Optional hardware tier filter. ``None`` (default) produces the
            full seven-target curve. ``"tier1"`` restricts to the three MCU
            targets (F401RE, Nano 33, ESP32-S3); see ``TIER_1_TARGETS``.

    """
    target_ids = _target_ids(matrix_data, tier=tier)
    future_ids = POST1_FUTURE_TARGETS if tier == "tier1" and target_ids else ()

    chart: ChartConfig = {
        "type": "line",
        "data": {
            "labels": [
                *(TARGET_LABELS[target] for target in target_ids),
                *(TARGET_LABELS[target] for target in future_ids),
            ],
            "datasets": [
                {
                    "label": TASK_LABELS.get(task, task),
                    "data": [
                        _cell_latency_headline(_find_cell(matrix_data, task=task, target=target))
                        for target in target_ids
                    ]
                    + [None for _target in future_ids],
                    "futureTiers": [TARGET_LABELS[target] for target in future_ids],
                    "spanGaps": False,
                    "tension": 0.25,
                }
                for task in _task_ids(matrix_data)
            ],
        },
        "options": {
            "responsive": True,
            "plugins": {"legend": {"position": "top"}},
            "scales": {
                "y": {
                    "type": "logarithmic",
                    "title": {"display": True, "text": "Median latency (us, log scale)"},
                }
            },
        },
    }
    if future_ids:
        chart["future_tiers"] = {
            "labels": [TARGET_LABELS[target] for target in future_ids],
            "note": "future tiers are axis-only; no data points",
        }
    return chart


def build_wh_comparison(
    matrix_data: MatrixData,
    *,
    tier: str | None = None,
) -> ChartConfig:
    """Return a Chart.js grouped bar chart: target vs mWh/1000 inferences.

    Args:
        matrix_data: Matrix export from T3.4.
        tier: Optional hardware tier filter. ``None`` (default) produces the
            full seven-target comparison. ``"tier1"`` restricts to the three
            MCU targets (F401RE, Nano 33, ESP32-S3); see ``TIER_1_TARGETS``.

    """
    return {
        "type": "bar",
        "data": {
            "labels": _target_labels(matrix_data, tier=tier),
            "datasets": [
                {
                    "label": TASK_LABELS.get(task, task),
                    "data": [
                        _cell_wh_headline_mwh(_find_cell(matrix_data, task=task, target=target))
                        for target in _target_ids(matrix_data, tier=tier)
                    ],
                }
                for task in _task_ids(matrix_data)
            ],
        },
        "options": {
            "responsive": True,
            "plugins": {"legend": {"position": "top"}},
            "scales": {
                "y": {
                    "type": "logarithmic",
                    "title": {
                        "display": True,
                        "text": "mWh per 1000 inferences (log scale)",
                    },
                }
            },
        },
    }


def build_variance_illustration(
    matrix_data: MatrixData,
    *,
    task: str = "kws",
    target: str = "pi5",
) -> ChartConfig:
    """Return a Chart.js bar chart preserving per-run latency spread."""
    cell = _find_cell(matrix_data, task=task, target=target)
    runs = _runs_with_latency(cell) if cell is not None else []
    data = []
    for index, run in enumerate(runs, start=1):
        latency_stats = run.latency_stats
        if latency_stats is None:
            continue
        label = f"Run {index}"
        data.append(
            {
                "x": label,
                "y": latency_stats["median_us"],
                "yMin": latency_stats["min_us"],
                "yMax": latency_stats["max_us"],
                "runId": run.run_id,
                "partial": run.telemetry_partial,
                "partialReasons": list(run.partial_reasons),
                "partialInferenceWarnings": list(run.partial_inference_warnings),
            },
        )

    chart_label = f"{TASK_LABELS.get(task, task)} on {TARGET_LABELS.get(target, target)}"
    detail = cell_detail(runs)
    non_partial_with_latency = [
        run for run in filter_non_partial(runs) if run.latency_stats is not None
    ]
    return {
        "type": "bar",
        "data": {
            "labels": [point["x"] for point in data],
            "datasets": [
                {
                    "label": chart_label,
                    "data": data,
                }
            ],
        },
        "meta": {
            "nTotal": detail.n_total,
            "nPartial": detail.n_partial,
            "headlineBasis": detail.headline_basis,
            "partialInferenceCount": detail.partial_inference_count,
            "mean": cell_headline(runs, "latency_us", statistic="mean"),
            "stddev": (
                cell_headline(runs, "latency_us", statistic="stddev")
                if len(non_partial_with_latency) > 1
                else None
            ),
        },
        "options": {
            "responsive": True,
            "plugins": {"legend": {"display": True}},
            "scales": {
                "y": {"title": {"display": True, "text": "Median latency with min/max spread (us)"}}
            },
        },
    }


def build_variance_strip(
    matrix_data: MatrixData,
    *,
    tier: str | None = None,
    task: str | None = None,
) -> ChartConfig:
    """Return a Chart.js strip-plot config preserving per-run variance.

    For each (target, task) cell, emits three semantic dataset layers:

    - ``Individual runs``: scatter points, one per run, at the cell's
      categorical x position. Carries ``runId`` plus partial-telemetry
      flags so the consumer can render dim dots and partial-telemetry
      annotations.
    - ``Cell mean``: one point per cell at the arithmetic mean of the
      cell's run latencies (non-partial runs only).
    - ``±1 stddev``: one point per cell carrying ``yMin``/``yMax`` for the
      sample-stddev band (``statistics.stdev`` with ``ddof=1`` via
      ``cell_headline``). Emits ``None`` for ``yMin``/``yMax`` when the
      cell has fewer than two non-partial runs with latency.

    Cells are ordered task-major (TASK_ORDER), target-minor (TARGET_ORDER).

    Args:
        matrix_data: Matrix export from T3.4.
        tier: Optional hardware tier filter. ``None`` = all targets;
            ``"tier1"`` = MCU subset (F401RE, Nano 33, ESP32-S3).
        task: Optional task filter. ``None`` = all tasks present in the
            matrix; otherwise restrict to the named task ("kws", "ic", or
            "ad"). Unknown task names produce an empty plot, matching the
            ``_find_cell`` lookup miss semantics.

    """
    target_ids = _target_ids(matrix_data, tier=tier)
    all_task_ids = _task_ids(matrix_data)
    task_ids = all_task_ids if task is None else [task] if task in all_task_ids else []

    run_points: list[dict[str, Any]] = []
    mean_points: list[dict[str, Any]] = []
    band_points: list[dict[str, Any]] = []
    cell_meta: list[dict[str, Any]] = []
    labels: list[str] = []

    for task_id in task_ids:
        for target_id in target_ids:
            cell = _find_cell(matrix_data, task=task_id, target=target_id)
            task_label = TASK_LABELS.get(task_id, task_id)
            target_label = TARGET_LABELS.get(target_id, target_id)
            label = f"{task_label} / {target_label}"
            labels.append(label)

            runs = _runs_with_latency(cell) if cell is not None else []
            non_partial_with_latency = [
                run for run in filter_non_partial(runs) if run.latency_stats is not None
            ]
            for run in runs:
                latency_stats = run.latency_stats
                if latency_stats is None:
                    continue
                run_points.append(
                    {
                        "x": label,
                        "y": latency_stats["median_us"],
                        "runId": run.run_id,
                        "task": task_id,
                        "target": target_id,
                        "partial": run.telemetry_partial,
                        "partialReasons": list(run.partial_reasons),
                        "partialInferenceWarnings": list(run.partial_inference_warnings),
                    },
                )

            mean = cell_headline(runs, "latency_us", statistic="mean")
            stddev = (
                cell_headline(runs, "latency_us", statistic="stddev")
                if len(non_partial_with_latency) > 1
                else None
            )
            mean_points.append(
                {"x": label, "y": mean, "task": task_id, "target": target_id},
            )
            band_points.append(
                {
                    "x": label,
                    "yMin": (mean - stddev) if (mean is not None and stddev is not None) else None,
                    "yMax": (mean + stddev) if (mean is not None and stddev is not None) else None,
                    "task": task_id,
                    "target": target_id,
                },
            )

            detail = cell_detail(runs)
            cell_meta.append(
                {
                    "task": task_id,
                    "target": target_id,
                    "label": label,
                    "nTotal": detail.n_total,
                    "nPartial": detail.n_partial,
                    "headlineBasis": detail.headline_basis,
                    "partialInferenceCount": detail.partial_inference_count,
                    "mean": mean,
                    "stddev": stddev,
                },
            )

    return {
        "type": "scatter",
        "data": {
            "labels": labels,
            "datasets": [
                {"label": "Individual runs", "role": "runs", "data": run_points},
                {"label": "Cell mean", "role": "mean", "data": mean_points},
                {"label": "±1 stddev", "role": "stddev_band", "data": band_points},
            ],
        },
        "meta": {"cells": cell_meta},
        "options": {
            "responsive": True,
            "plugins": {"legend": {"display": True}},
            "scales": {
                "y": {
                    "type": "logarithmic",
                    "title": {"display": True, "text": "Latency (us, log scale)"},
                }
            },
        },
    }


def _task_ids(matrix_data: MatrixData) -> list[str]:
    present = {cell.task for cell in matrix_data.cells}
    ordered = [task for task in TASK_ORDER if task in present]
    extras = sorted(present - set(TASK_ORDER))
    return ordered + extras


def _target_ids(matrix_data: MatrixData, *, tier: str | None = None) -> list[str]:
    present = {cell.target for cell in matrix_data.cells}
    if tier is not None:
        present = present & set(_tier_targets(tier))
    ordered = [target for target in TARGET_ORDER if target in present]
    extras = sorted(present - set(TARGET_ORDER))
    return ordered + extras


def _target_labels(matrix_data: MatrixData, *, tier: str | None = None) -> list[str]:
    return [TARGET_LABELS.get(target, target) for target in _target_ids(matrix_data, tier=tier)]


def _tier_targets(tier: str) -> tuple[str, ...]:
    if tier == "tier1":
        return TIER_1_TARGETS
    msg = f"unknown tier: {tier!r}; expected None or 'tier1'"
    raise ValueError(msg)


def _find_cell(matrix_data: MatrixData, *, task: str, target: str) -> CellData | None:
    for cell in matrix_data.cells:
        if cell.task == task and cell.target == target:
            return cell
    return None


def _cell_latency_headline(cell: CellData | None) -> float | None:
    return cell_headline(_runs_with_latency(cell), "latency_us")


def _cell_wh_headline_mwh(cell: CellData | None) -> float | None:
    return cell_headline(_runs_with_energy(cell), "wh_per_1000_mwh")


def _runs_with_latency(cell: CellData | None) -> list[RunData]:
    if cell is None:
        return []
    return [
        run for run in cell.runs if run.latency_stats is not None and not repeat_quarantined(run)
    ]


def _runs_with_energy(cell: CellData | None) -> list[RunData]:
    if cell is None:
        return []
    return [run for run in cell.runs if run.energy_stats is not None]
