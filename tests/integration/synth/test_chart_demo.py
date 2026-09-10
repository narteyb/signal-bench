# SPDX-License-Identifier: Apache-2.0
"""Generate a standalone Chart.js demo from synthetic matrix data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signal_bench.synth.chart_data import TARGET_ORDER, TASK_ORDER, build_chart_data
from signal_bench.synth.matrix_data import CellData, MatrixData, RunData


def _run(run_id: str, *, latency_us: float, wh_per_1000: float) -> RunData:
    return RunData(
        run_id=run_id,
        started_at="2026-05-15T12:00:00Z",
        status="completed",
        duration_s=30.0,
        iterations=100,
        warmup_iterations=10,
        model_hash="hash",
        quantization="int8",
        telemetry_partial=False,
        telemetry_partial_sources=[],
        latency_stats={
            "n_samples": 100,
            "n_outliers": 0,
            "mean_us": latency_us,
            "median_us": latency_us,
            "p95_us": latency_us * 1.15,
            "p99_us": latency_us * 1.25,
            "stddev_us": latency_us * 0.05,
            "variance_pct": 5.0,
            "min_us": latency_us * 0.9,
            "max_us": latency_us * 1.3,
        },
        energy_stats={
            "total_wh": wh_per_1000 / 1000,
            "avg_power_w": 5.0,
            "sample_count": 300,
            "duration_s": 30.0,
            "telemetry_coverage": 1.0,
            "wh_per_1000": wh_per_1000,
            "warnings": [],
            "min_power_w": 4.8,
            "max_power_w": 5.2,
        },
    )


def _synthetic_full_matrix() -> MatrixData:
    cells: list[CellData] = []
    for task_index, task in enumerate(TASK_ORDER, start=1):
        for target_index, target in enumerate(TARGET_ORDER, start=1):
            latency_us = float(100_000 / target_index * task_index)
            wh_per_1000 = float(0.05 * task_index * (8 - target_index))
            cells.append(
                CellData(
                    task=task,
                    target=target,
                    status="ok",
                    runs=[
                        _run(f"{task}-{target}-1", latency_us=latency_us, wh_per_1000=wh_per_1000),
                        _run(
                            f"{task}-{target}-2",
                            latency_us=latency_us * 1.05,
                            wh_per_1000=wh_per_1000 * 1.1,
                        ),
                        _run(
                            f"{task}-{target}-3",
                            latency_us=latency_us * 1.4,
                            wh_per_1000=wh_per_1000 * 1.5,
                        ),
                    ],
                ),
            )
    return MatrixData(
        schema_version=1,
        matrix_name="synthetic-demo",
        generated_at="2026-05-15T12:00:00Z",
        generated_from_runs=sum(len(cell.runs) for cell in cells),
        cells=cells,
    )


def test_chart_demo_html_is_generated() -> None:
    chart_data = build_chart_data(_synthetic_full_matrix())
    template_path = Path("tests/integration/synth/_demo.html.template")
    output_path = Path("tests/integration/synth/_demo.html")
    html = template_path.read_text(encoding="utf-8").replace(
        "__CHART_JSON__",
        json.dumps(chart_data),
    )
    output_path.write_text(html, encoding="utf-8")

    assert output_path.exists()
    assert "https://cdn.jsdelivr.net/npm/chart.js" in html
    assert "hardware-curve" in html
    assert _chart_types(chart_data) == {
        "hardware-curve": "line",
        "wh-comparison": "bar",
        "variance-illustration": "bar",
        "hardware-curve-tier1": "line",
        "wh-comparison-tier1": "bar",
        "variance-strip-tier1": "scatter",
    }


def _chart_types(chart_data: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {name: str(config["type"]) for name, config in chart_data.items()}
