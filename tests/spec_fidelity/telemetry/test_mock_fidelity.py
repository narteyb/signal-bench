# SPDX-License-Identifier: Apache-2.0
"""Spec-fidelity tests for MockTelemetrySource.

These tests verify the TelemetrySource contract from Architecture INV-02 and
the ABC contract in signal_bench.telemetry.base.
"""

from __future__ import annotations

import time

from signal_bench.telemetry import MockTelemetrySource, TelemetrySample, TelemetrySource


class TestMockTelemetrySourceFidelity:
    """Architecture-facing fidelity checks for the deterministic mock source."""

    def test_implements_telemetry_source_contract(self) -> None:
        """TelemetrySource contract: source_name and sample_rate_hz are class-level values."""
        assert issubclass(MockTelemetrySource, TelemetrySource)
        assert isinstance(MockTelemetrySource.source_name, str)
        assert MockTelemetrySource.source_name == "mock"
        assert isinstance(MockTelemetrySource.sample_rate_hz, float)
        assert MockTelemetrySource.sample_rate_hz > 0

    def test_default_rate_matches_class_var(self) -> None:
        """TelemetrySource contract: default sampling rate matches the public class value."""
        source = MockTelemetrySource()

        assert source.sample_rate_hz == MockTelemetrySource.sample_rate_hz

    def test_emits_three_metrics_by_default(self) -> None:
        """INV-02 fidelity: mock defaults emit power-vector voltage, current, and power."""
        source = MockTelemetrySource()

        assert set(source._metrics) == {"voltage_v", "current_ma", "power_w"}

    def test_sample_returns_typed_telemetry_samples(self) -> None:
        """TelemetrySource contract: sample() returns TelemetrySample instances."""
        source = MockTelemetrySource()
        source.open()
        time.sleep(0.35)

        samples = source.sample()

        assert samples
        assert all(isinstance(sample, TelemetrySample) for sample in samples)

    def test_sample_timestamps_are_monotonic(self) -> None:
        """TelemetrySource contract: buffered sample timestamps never move backward."""
        source = MockTelemetrySource(rate_hz=20.0)
        source.open()
        time.sleep(0.35)

        samples = source.sample()
        timestamps = [sample.timestamp for sample in samples]

        assert timestamps == sorted(timestamps)

    def test_value_ranges_within_documented_bounds(self) -> None:
        """Mock spec: values stay in deterministic +/-0.1 ranges around documented bases."""
        source = MockTelemetrySource(rate_hz=10.0)
        source.open()
        time.sleep(0.35)

        samples = source.sample()
        by_metric: dict[str, list[float]] = {}
        for sample in samples:
            by_metric.setdefault(sample.metric, []).append(sample.value)

        assert all(4.9 <= value <= 5.1 for value in by_metric["voltage_v"])
        assert all(199.9 <= value <= 200.1 for value in by_metric["current_ma"])
        assert all(0.9 <= value <= 1.1 for value in by_metric["power_w"])
