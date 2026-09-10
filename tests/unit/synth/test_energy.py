# SPDX-License-Identifier: Apache-2.0
"""Tests for run-level energy metric computation."""

from __future__ import annotations

import math

import pytest

from signal_bench.synth.energy import EnergyStats, compute_energy, wh_per_1000


def test_constant_one_watt_for_sixty_seconds() -> None:
    stats = compute_energy([(0.0, 1.0), (60.0, 1.0)])

    assert stats.total_j == pytest.approx(60.0)
    assert stats.total_wh == pytest.approx(60.0 / 3600.0)
    assert stats.avg_power_w == pytest.approx(1.0)
    assert stats.duration_s == pytest.approx(60.0)


def test_wh_per_1000_for_constant_five_watts() -> None:
    stats = compute_energy([(0.0, 5.0), (30.0, 5.0)])

    assert stats.total_j == pytest.approx(150.0)
    assert wh_per_1000(stats, 100) == pytest.approx(0.4166666667)


def test_linearly_ramping_power_uses_trapezoid_rule() -> None:
    stats = compute_energy([(0.0, 0.0), (10.0, 10.0)])

    assert stats.total_j == pytest.approx(50.0)
    assert stats.avg_power_w == pytest.approx(5.0)


def test_zero_power_samples_produce_zero_energy() -> None:
    stats = compute_energy([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])

    assert stats.total_j == 0.0
    assert stats.total_wh == 0.0
    assert wh_per_1000(stats, 100) == 0.0


def test_zero_inferences_return_infinity() -> None:
    stats = compute_energy([(0.0, 1.0), (1.0, 1.0)])

    assert math.isinf(wh_per_1000(stats, 0))


def test_negative_inference_count_raises() -> None:
    stats = compute_energy([(0.0, 1.0), (1.0, 1.0)])

    with pytest.raises(ValueError, match="inference_count"):
        wh_per_1000(stats, -1)


def test_single_sample_raises() -> None:
    with pytest.raises(ValueError, match="at least 2 samples"):
        compute_energy([(0.0, 1.0)])


def test_short_sample_count_adds_warning() -> None:
    stats = compute_energy([(0.0, 1.0), (1.0, 1.0)])

    assert stats.warnings == ("energy estimate uses fewer than 10 power samples",)


def test_negative_power_is_clamped_with_warning() -> None:
    stats = compute_energy([(0.0, -1.0), (10.0, 3.0)])

    assert stats.total_j == pytest.approx(15.0)
    assert stats.min_power_w == 0.0
    assert "clamped 1 negative power sample" in stats.warnings[0]


def test_telemetry_coverage_defaults_to_full_sample_span() -> None:
    stats = compute_energy([(0.0, 2.0), (10.0, 2.0)])

    assert stats.telemetry_coverage == pytest.approx(1.0)


def test_telemetry_coverage_uses_run_duration_when_provided() -> None:
    stats = compute_energy([(0.0, 2.0), (10.0, 2.0)], run_duration_s=20.0)

    assert stats.telemetry_coverage == pytest.approx(0.5)


def test_telemetry_coverage_caps_at_one_with_warning() -> None:
    stats = compute_energy([(0.0, 2.0), (20.0, 2.0)], run_duration_s=10.0)

    assert stats.telemetry_coverage == pytest.approx(1.0)
    assert "coverage capped" in stats.warnings[-1]


def test_invalid_run_duration_raises() -> None:
    with pytest.raises(ValueError, match="run_duration_s"):
        compute_energy([(0.0, 1.0), (1.0, 1.0)], run_duration_s=0.0)


def test_non_increasing_timestamps_raise() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        compute_energy([(0.0, 1.0), (0.0, 1.0)])


def test_non_finite_samples_raise() -> None:
    with pytest.raises(ValueError, match="finite"):
        compute_energy([(0.0, 1.0), (math.inf, 1.0)])


def test_wh_per_1000_rejects_negative_energy_stats() -> None:
    stats = EnergyStats(
        total_j=-1.0,
        total_wh=-1.0 / 3600.0,
        sample_count=2,
        duration_s=1.0,
        avg_power_w=-1.0,
        min_power_w=-1.0,
        max_power_w=-1.0,
        telemetry_coverage=1.0,
    )

    with pytest.raises(ValueError, match="non-negative"):
        wh_per_1000(stats, 100)
