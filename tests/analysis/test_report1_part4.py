"""Regression checks for retained-output precision and a fixed latency cell."""

import math

from scripts.report1_part4 import analyze, load_sessions, predictions


def test_zero_variance_pair_keeps_observed_ratio() -> None:
    _, pairs, _, _ = analyze(load_sessions())
    row = next(
        pair for pair in pairs
        if (pair["task"], pair["metric"], pair["first"], pair["second"])
        == ("ad", "latency", "f401re", "esp32s3")
    )
    assert math.isclose(row["ratio"], 8.136 / 11.723, rel_tol=1e-12)
    assert row["lower"] is row["upper"] is row["p_adjusted"] is row["hedges_g"] is None
    assert row["sesoi"] == "beyond ±10% in every session"


def test_anomaly_score_difference_uses_common_inputs() -> None:
    row = next(item for item in predictions() if item["task"] == "ad")
    assert row["inputs"] == 12
    assert row["matches"] == 1
    assert math.isclose(row["max_absolute_score_difference"], 3e-6, rel_tol=1e-9)
    assert math.isclose(row["max_relative_score_difference"], 2.6997468443164484e-7)
