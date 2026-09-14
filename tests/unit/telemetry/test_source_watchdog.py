# SPDX-License-Identifier: Apache-2.0
"""Tests for cadence-aware telemetry source watchdog timing."""

import pytest

from signal_bench.telemetry.orchestrator import _source_disconnect_threshold


@pytest.mark.parametrize(
    ("sample_rate_hz", "expected_threshold_s"),
    [(8.0, 2.0), (0.2, 12.5), (0.0, 2.0)],
)
def test_source_disconnect_threshold_respects_source_cadence(
    sample_rate_hz: float,
    expected_threshold_s: float,
) -> None:
    assert _source_disconnect_threshold(sample_rate_hz) == pytest.approx(expected_threshold_s)
