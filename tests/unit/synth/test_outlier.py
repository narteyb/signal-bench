# SPDX-License-Identifier: Apache-2.0
import pytest

from signal_bench.synth.outlier import (
    apply_outlier_policy,
    iqr_outliers,
    none_outliers,
    zscore_outliers,
)


def test_iqr_rejects_one_obvious_outlier() -> None:
    clean, outliers = iqr_outliers([10, 10, 11, 11, 12, 12, 100])

    assert clean == [10.0, 10.0, 11.0, 11.0, 12.0, 12.0]
    assert outliers == [100.0]


def test_iqr_constant_data_rejects_nothing() -> None:
    clean, outliers = iqr_outliers([5, 5, 5, 5, 5])

    assert clean == [5.0, 5.0, 5.0, 5.0, 5.0]
    assert outliers == []


def test_iqr_skips_less_than_four_samples() -> None:
    clean, outliers = iqr_outliers([1, 100, 1000])

    assert clean == [1.0, 100.0, 1000.0]
    assert outliers == []


def test_zscore_rejects_extreme_outlier() -> None:
    clean, outliers = zscore_outliers([10] * 20 + [1000])

    assert clean == [10.0] * 20
    assert outliers == [1000.0]


def test_none_policy_keeps_everything() -> None:
    clean, outliers = none_outliers([1, 2, 1000])

    assert clean == [1.0, 2.0, 1000.0]
    assert outliers == []


def test_apply_outlier_policy_dispatches() -> None:
    clean, outliers = apply_outlier_policy([1, 1, 1, 100], "none")

    assert clean == [1.0, 1.0, 1.0, 100.0]
    assert outliers == []


def test_apply_outlier_policy_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="unknown outlier policy"):
        apply_outlier_policy([1, 2, 3], "bad")  # type: ignore[arg-type]


def test_outlier_policies_reject_non_finite_samples() -> None:
    with pytest.raises(ValueError, match="finite"):
        iqr_outliers([1, float("nan")])
