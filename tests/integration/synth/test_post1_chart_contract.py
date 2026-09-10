# SPDX-License-Identifier: Apache-2.0
"""Post 1 chart contract checks for the Signal Reports renderer."""

from __future__ import annotations

from pathlib import Path

import yaml

POST_PATH = Path("content/posts/2026-05-28-tinyml-reality-check.md")
DATA_PATH = Path("content/signal-reports/2026-05-28-tinyml-reality-check-data.yml")

EXPECTED_VISUALIZATIONS = [
    "hardware_performance_curve",
    "wh_comparison",
    "variance_illustration",
]


def _front_matter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    marker = "---\n"
    assert text.startswith(marker)
    _, front_matter, _ = text.split(marker, maxsplit=2)
    loaded = yaml.safe_load(front_matter)
    assert isinstance(loaded, dict)
    return loaded


def test_post1_emits_ordered_signal_report_visualization_contract() -> None:
    front_matter = _front_matter(POST_PATH)

    assert front_matter["signal_report_visualizations"] == EXPECTED_VISUALIZATIONS
    assert "hardware_curve_tier1" not in POST_PATH.read_text(encoding="utf-8")


def test_post1_signal_report_data_uses_renderer_data_keys() -> None:
    data = yaml.safe_load(DATA_PATH.read_text(encoding="utf-8"))

    assert "hardware_curve" in data
    assert "energy_comparison_tier1" in data
    assert "variance_illustration" in data
    assert "hardware_curve_tier1" not in data
