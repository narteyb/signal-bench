# SPDX-License-Identifier: Apache-2.0
import time

import pytest

from signal_bench.telemetry import MockTelemetrySource


def test_mock_source_is_available() -> None:
    assert MockTelemetrySource().is_available() is True


def test_mock_source_samples_at_configured_rate() -> None:
    source = MockTelemetrySource(rate_hz=10.0)
    source.open()
    time.sleep(1.05)

    samples = source.sample()

    assert len(samples) >= 30
    by_metric = {sample.metric: sample.value for sample in samples}
    assert 4.9 <= by_metric["voltage_v"] <= 5.1
    assert 199.9 <= by_metric["current_ma"] <= 200.1
    assert 0.9 <= by_metric["power_w"] <= 1.1


def test_mock_source_fail_after_raises() -> None:
    source = MockTelemetrySource(fail_after=0.2)
    source.open()
    time.sleep(0.25)

    with pytest.raises(RuntimeError, match="configured to fail"):
        source.sample()


def test_mock_source_close_is_idempotent() -> None:
    source = MockTelemetrySource()
    source.open()
    source.close()
    source.close()

    assert source.sample() == []
