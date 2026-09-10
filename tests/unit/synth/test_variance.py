# SPDX-License-Identifier: Apache-2.0
import math
import random

import pytest

from signal_bench.synth.variance import compute_variance


def test_compute_variance_normal_data_matches_expected_shape() -> None:
    random.seed(42)
    samples = [random.gauss(100, 10) for _ in range(100)]

    stats = compute_variance(samples, outlier_policy="none")

    assert stats.n_samples == 100
    assert stats.n_outliers == 0
    assert stats.mean == pytest.approx(100.58, abs=0.01)
    assert stats.median == pytest.approx(101.12, abs=0.01)
    assert stats.stddev == pytest.approx(8.82, abs=0.01)
    assert stats.variance_pct == pytest.approx(8.77, abs=0.01)


def test_constant_data_has_zero_stddev() -> None:
    stats = compute_variance([42, 42, 42, 42], outlier_policy="iqr")

    assert stats.mean == 42
    assert stats.median == 42
    assert stats.stddev == 0
    assert stats.variance_pct == 0
    assert stats.min == 42
    assert stats.max == 42


def test_percentiles_capture_latency_tail() -> None:
    samples = [10] * 95 + [20, 30, 40, 50, 60]

    stats = compute_variance(samples, outlier_policy="none")

    assert stats.median == 10
    assert stats.p95 > stats.median
    assert stats.p99 > stats.p95


def test_bimodal_data_keeps_median_between_modes() -> None:
    stats = compute_variance([10] * 50 + [30] * 50, outlier_policy="none")

    assert stats.mean == 20
    assert stats.median == 20
    assert stats.p95 == 30


def test_single_sample_returns_degenerate_stats() -> None:
    stats = compute_variance([7.5])

    assert stats.n_samples == 1
    assert stats.n_outliers == 0
    assert stats.mean == 7.5
    assert stats.stddev == 0
    assert math.isnan(stats.variance_pct)
    assert stats.min == 7.5
    assert stats.max == 7.5


def test_empty_samples_raise_value_error() -> None:
    with pytest.raises(ValueError, match="at least 1 sample"):
        compute_variance([])


def test_iqr_outlier_rejection_runs_before_stats() -> None:
    samples = [100, 101, 99, 100, 102, 98, 1000]

    stats = compute_variance(samples, outlier_policy="iqr")

    assert stats.n_samples == 6
    assert stats.n_outliers == 1
    assert stats.max == 102
    assert stats.mean == pytest.approx(100)


def test_none_policy_keeps_outliers_in_stats() -> None:
    samples = [100, 101, 99, 100, 102, 98, 1000]

    stats = compute_variance(samples, outlier_policy="none")

    assert stats.n_samples == 7
    assert stats.n_outliers == 0
    assert stats.max == 1000
    assert stats.mean > 200


def test_zero_mean_variance_pct_is_infinite() -> None:
    stats = compute_variance([-1, 0, 1], outlier_policy="none")

    assert stats.mean == 0
    assert math.isinf(stats.variance_pct)


def test_outlier_policy_that_removes_everything_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "signal_bench.synth.variance.apply_outlier_policy",
        lambda _samples, _policy: ([], [1.0]),
    )

    with pytest.raises(ValueError, match="removed every sample"):
        compute_variance([1.0])
