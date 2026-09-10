# SPDX-License-Identifier: Apache-2.0
"""Tests for Chart.js data preparation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from signal_bench.synth.chart_data import (
    build_chart_data,
    build_hardware_curve,
    build_variance_illustration,
    build_variance_strip,
    build_wh_comparison,
    write_chart_json_files,
)
from signal_bench.synth.matrix_data import CellData, MatrixData, RunData

if TYPE_CHECKING:
    from pathlib import Path


def _run(
    run_id: str,
    *,
    median_us: float,
    min_us: float | None = None,
    max_us: float | None = None,
    wh_per_1000: float = 0.001,
) -> RunData:
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
            "mean_us": median_us,
            "median_us": median_us,
            "p95_us": median_us * 1.1,
            "p99_us": median_us * 1.2,
            "stddev_us": median_us * 0.05,
            "variance_pct": 5.0,
            "min_us": min_us if min_us is not None else median_us * 0.9,
            "max_us": max_us if max_us is not None else median_us * 1.2,
        },
        energy_stats={
            "total_wh": wh_per_1000 / 1000,
            "avg_power_w": 5.0,
            "sample_count": 30,
            "duration_s": 30.0,
            "telemetry_coverage": 1.0,
            "wh_per_1000": wh_per_1000,
            "warnings": [],
            "min_power_w": 5.0,
            "max_power_w": 5.0,
        },
    )


def _cell(task: str, target: str, runs: list[RunData]) -> CellData:
    return CellData(task=task, target=target, status="ok" if runs else "no_data", runs=runs)


def _matrix(cells: list[CellData]) -> MatrixData:
    return MatrixData(
        schema_version=1,
        matrix_name="test-matrix",
        generated_at="2026-05-15T12:00:00Z",
        generated_from_runs=sum(len(cell.runs) for cell in cells),
        cells=cells,
    )


def _dataset(chart: dict[str, Any], label: str) -> dict[str, Any]:
    for dataset in chart["data"]["datasets"]:
        if dataset["label"] == label:
            return dataset
    msg = f"missing dataset {label}"
    raise AssertionError(msg)


def test_hardware_curve_uses_target_capability_order() -> None:
    chart = build_hardware_curve(
        _matrix(
            [
                _cell("kws", "modal", [_run("modal", median_us=10)]),
                _cell("kws", "f401re", [_run("f401re", median_us=1000)]),
                _cell("kws", "pi5", [_run("pi5", median_us=100)]),
            ],
        ),
    )

    assert chart["type"] == "line"
    assert chart["data"]["labels"] == ["F401RE", "Pi 5", "Modal A10G"]
    assert chart["options"]["scales"]["y"]["type"] == "logarithmic"


def test_hardware_curve_uses_median_of_run_medians() -> None:
    chart = build_hardware_curve(
        _matrix(
            [
                _cell(
                    "kws",
                    "pi5",
                    [
                        _run("run-1", median_us=100),
                        _run("run-2", median_us=102),
                        _run("run-3", median_us=350),
                    ],
                ),
            ],
        ),
    )

    assert _dataset(chart, "KWS")["data"] == [102.0]


def test_hardware_curve_omits_no_data_as_gap() -> None:
    chart = build_hardware_curve(
        _matrix(
            [
                _cell("kws", "f401re", []),
                _cell("kws", "pi5", [_run("run-1", median_us=100)]),
            ],
        ),
    )

    assert _dataset(chart, "KWS")["data"] == [None, 100.0]


def test_wh_comparison_uses_mwh_per_1000_and_log_axis() -> None:
    chart = build_wh_comparison(
        _matrix([_cell("kws", "pi5", [_run("run-1", median_us=100, wh_per_1000=0.002)])]),
    )

    assert chart["type"] == "bar"
    assert _dataset(chart, "KWS")["data"] == [2.0]
    assert chart["options"]["scales"]["y"]["type"] == "logarithmic"


def test_wh_comparison_uses_median_of_run_energy() -> None:
    chart = build_wh_comparison(
        _matrix(
            [
                _cell(
                    "ad",
                    "jetson",
                    [
                        _run("run-1", median_us=1, wh_per_1000=0.001),
                        _run("run-2", median_us=1, wh_per_1000=0.002),
                        _run("run-3", median_us=1, wh_per_1000=0.010),
                    ],
                ),
            ],
        ),
    )

    assert _dataset(chart, "AD")["data"] == [2.0]


def test_variance_illustration_preserves_repeat_spread() -> None:
    chart = build_variance_illustration(
        _matrix(
            [
                _cell(
                    "kws",
                    "pi5",
                    [
                        _run("run-1", median_us=100, min_us=90, max_us=130),
                        _run("run-2", median_us=110, min_us=100, max_us=150),
                    ],
                ),
            ],
        ),
    )

    points = chart["data"]["datasets"][0]["data"]
    assert points == [
        {
            "x": "Run 1",
            "y": 100,
            "yMin": 90,
            "yMax": 130,
            "runId": "run-1",
            "partial": False,
            "partialReasons": [],
            "partialInferenceWarnings": [],
        },
        {
            "x": "Run 2",
            "y": 110,
            "yMin": 100,
            "yMax": 150,
            "runId": "run-2",
            "partial": False,
            "partialReasons": [],
            "partialInferenceWarnings": [],
        },
    ]


def test_variance_illustration_can_select_non_default_cell() -> None:
    chart = build_variance_illustration(
        _matrix([_cell("ic", "f401re", [_run("run-1", median_us=500)])]),
        task="ic",
        target="f401re",
    )

    assert chart["data"]["datasets"][0]["label"] == "IC on F401RE"


def test_variance_illustration_handles_missing_cell() -> None:
    chart = build_variance_illustration(_matrix([]))

    assert chart["data"]["labels"] == []
    assert chart["data"]["datasets"][0]["data"] == []


def test_build_chart_data_returns_full_curve_and_tier1_charts() -> None:
    charts = build_chart_data(_matrix([_cell("kws", "pi5", [_run("run-1", median_us=100)])]))

    assert set(charts) == {
        "hardware-curve",
        "wh-comparison",
        "variance-illustration",
        "hardware-curve-tier1",
        "wh-comparison-tier1",
        "variance-strip-tier1",
    }


def test_write_chart_json_files(tmp_path: Path) -> None:
    paths = write_chart_json_files(
        _matrix([_cell("kws", "pi5", [_run("run-1", median_us=100)])]),
        tmp_path,
    )

    assert sorted(paths) == [
        "hardware-curve",
        "hardware-curve-tier1",
        "variance-illustration",
        "variance-strip-tier1",
        "wh-comparison",
        "wh-comparison-tier1",
    ]
    for path in paths.values():
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["type"] in {"line", "bar", "scatter"}


def test_empty_matrix_produces_minimal_valid_charts() -> None:
    charts = build_chart_data(_matrix([]))

    assert charts["hardware-curve"]["data"]["labels"] == []
    assert charts["wh-comparison"]["data"]["datasets"] == []
    assert charts["variance-illustration"]["data"]["datasets"][0]["data"] == []
    assert charts["hardware-curve-tier1"]["data"]["labels"] == []
    assert charts["wh-comparison-tier1"]["data"]["datasets"] == []
    assert charts["variance-strip-tier1"]["data"]["labels"] == []
    for dataset in charts["variance-strip-tier1"]["data"]["datasets"]:
        assert dataset["data"] == []


def test_hardware_curve_tier1_filters_to_tier1_targets() -> None:
    chart = build_hardware_curve(
        _matrix(
            [
                _cell("kws", "f401re", [_run("r1", median_us=1000)]),
                _cell("kws", "nano33", [_run("r2", median_us=900)]),
                _cell("kws", "esp32s3", [_run("r3", median_us=800)]),
                _cell("kws", "pi5", [_run("r4", median_us=100)]),
                _cell("kws", "modal", [_run("r5", median_us=10)]),
            ],
        ),
        tier="tier1",
    )

    assert chart["data"]["labels"] == [
        "F401RE",
        "Nano 33",
        "ESP32-S3",
        "Pi 5",
        "Hailo",
        "Jetson Orin Nano",
        "M1 Max",
    ]
    assert chart["future_tiers"]["labels"] == [
        "Pi 5",
        "Hailo",
        "Jetson Orin Nano",
        "M1 Max",
    ]
    assert _dataset(chart, "KWS")["data"] == [1000.0, 900.0, 800.0, None, None, None, None]


def test_wh_comparison_tier1_filters_to_tier1_targets() -> None:
    chart = build_wh_comparison(
        _matrix(
            [
                _cell("kws", "f401re", [_run("r1", median_us=100, wh_per_1000=0.001)]),
                _cell("kws", "modal", [_run("r2", median_us=10, wh_per_1000=0.005)]),
            ],
        ),
        tier="tier1",
    )

    assert chart["data"]["labels"] == ["F401RE"]


def test_hardware_curve_tier_none_equivalent_to_no_kwarg() -> None:
    matrix = _matrix(
        [
            _cell("kws", "f401re", [_run("r1", median_us=1000)]),
            _cell("kws", "modal", [_run("r2", median_us=10)]),
        ],
    )
    assert build_hardware_curve(matrix) == build_hardware_curve(matrix, tier=None)


def test_wh_comparison_tier_none_equivalent_to_no_kwarg() -> None:
    matrix = _matrix(
        [
            _cell("kws", "f401re", [_run("r1", median_us=100, wh_per_1000=0.001)]),
            _cell("kws", "modal", [_run("r2", median_us=10, wh_per_1000=0.005)]),
        ],
    )
    assert build_wh_comparison(matrix) == build_wh_comparison(matrix, tier=None)


def test_hardware_curve_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        build_hardware_curve(_matrix([]), tier="tier99")


def test_wh_comparison_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        build_wh_comparison(_matrix([]), tier="bogus")


def test_variance_strip_emits_three_dataset_layers() -> None:
    chart = build_variance_strip(
        _matrix(
            [
                _cell(
                    "kws",
                    "f401re",
                    [_run("r1", median_us=100), _run("r2", median_us=110)],
                ),
            ],
        ),
        tier="tier1",
    )

    assert chart["type"] == "scatter"
    labels = [ds["label"] for ds in chart["data"]["datasets"]]
    assert labels == ["Individual runs", "Cell mean", "±1 stddev"]
    roles = [ds["role"] for ds in chart["data"]["datasets"]]
    assert roles == ["runs", "mean", "stddev_band"]


def test_variance_strip_per_run_dots_carry_run_metadata() -> None:
    chart = build_variance_strip(
        _matrix(
            [_cell("kws", "f401re", [_run("r1", median_us=100), _run("r2", median_us=110)])],
        ),
        tier="tier1",
    )

    runs_ds = chart["data"]["datasets"][0]
    assert len(runs_ds["data"]) == 2
    assert runs_ds["data"][0] == {
        "x": "KWS / F401RE",
        "y": 100,
        "runId": "r1",
        "task": "kws",
        "target": "f401re",
        "partial": False,
        "partialReasons": [],
        "partialInferenceWarnings": [],
    }
    assert runs_ds["data"][1]["y"] == 110


def test_variance_strip_mean_and_stddev_band_match_cell_headline() -> None:
    chart = build_variance_strip(
        _matrix(
            [
                _cell(
                    "kws",
                    "f401re",
                    [
                        _run("r1", median_us=100),
                        _run("r2", median_us=110),
                        _run("r3", median_us=120),
                    ],
                ),
            ],
        ),
        tier="tier1",
    )

    mean = chart["data"]["datasets"][1]["data"][0]["y"]
    band = chart["data"]["datasets"][2]["data"][0]
    assert mean == pytest.approx(110.0)
    assert band["yMin"] == pytest.approx(mean - 10.0)
    assert band["yMax"] == pytest.approx(mean + 10.0)
    assert chart["meta"]["cells"][0]["nTotal"] == 3
    assert chart["meta"]["cells"][0]["mean"] == pytest.approx(110.0)
    assert chart["meta"]["cells"][0]["stddev"] == pytest.approx(10.0)


def test_variance_strip_single_run_cell_has_no_stddev_band() -> None:
    chart = build_variance_strip(
        _matrix([_cell("kws", "f401re", [_run("r1", median_us=100)])]),
        tier="tier1",
    )

    band = chart["data"]["datasets"][2]["data"][0]
    assert band["yMin"] is None
    assert band["yMax"] is None
    assert chart["meta"]["cells"][0]["stddev"] is None


def test_variance_strip_tier1_excludes_non_tier1_targets() -> None:
    chart = build_variance_strip(
        _matrix(
            [
                _cell("kws", "f401re", [_run("r1", median_us=100)]),
                _cell("kws", "pi5", [_run("r2", median_us=50)]),
                _cell("kws", "modal", [_run("r3", median_us=10)]),
            ],
        ),
        tier="tier1",
    )

    assert chart["data"]["labels"] == ["KWS / F401RE"]


def test_variance_strip_task_filter_narrows_to_one_task() -> None:
    chart = build_variance_strip(
        _matrix(
            [
                _cell("kws", "f401re", [_run("r1", median_us=100)]),
                _cell("ic", "f401re", [_run("r2", median_us=500)]),
                _cell("ad", "f401re", [_run("r3", median_us=300)]),
            ],
        ),
        tier="tier1",
        task="kws",
    )

    assert chart["data"]["labels"] == ["KWS / F401RE"]


def test_variance_strip_empty_matrix() -> None:
    chart = build_variance_strip(_matrix([]), tier="tier1")

    assert chart["data"]["labels"] == []
    for dataset in chart["data"]["datasets"]:
        assert dataset["data"] == []
    assert chart["meta"]["cells"] == []


def test_variance_strip_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        build_variance_strip(_matrix([]), tier="tier99")
