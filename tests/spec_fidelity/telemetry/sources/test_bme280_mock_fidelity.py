# SPDX-License-Identifier: Apache-2.0
"""Spec-fidelity tests for MockBME280Source.

These checks lock the T7.4 source contract for the mocked BME280 lab
environment source: canonical metric names, source naming, unit hints, and
realistic default rate.
"""

from __future__ import annotations

import pytest

from signal_bench.telemetry import TelemetrySample, TelemetrySource
from signal_bench.telemetry.sources import MockBME280Config, MockBME280Source


async def _first_sample(source: MockBME280Source) -> TelemetrySample:
    await source.start()
    try:
        async for sample in source.samples():
            return sample
    finally:
        await source.stop()
    pytest.fail("mock BME280 source did not emit a sample")


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


class TestMockBME280SourceFidelity:
    """Architecture-facing fidelity checks for the mocked BME280 source."""

    def test_implements_telemetry_source_contract(self) -> None:
        """TelemetrySource contract: mock BME280 is a concrete async source."""
        assert issubclass(MockBME280Source, TelemetrySource)
        assert isinstance(MockBME280Source.source_name, str)
        assert MockBME280Source.source_name == "mock_bme280_lab"
        assert isinstance(MockBME280Source.sample_rate_hz, float)
        assert MockBME280Source.sample_rate_hz == 1.0

    def test_default_config_uses_mock_identity_prefix(self) -> None:
        """T7.4 fidelity: placeholder sources use a mock_* source_name prefix."""
        config = MockBME280Config()

        assert config.name == "mock_bme280_lab"
        assert config.name.startswith("mock_")

    @pytest.mark.asyncio
    async def test_emits_canonical_environment_metrics(self) -> None:
        """T7.4 fidelity: BME280 emits temperature/humidity/pressure units."""
        sample = await _first_sample(MockBME280Source())

        assert sample.source_name == "mock_bme280_lab"
        assert set(_sample_values(sample)) == {"temperature", "humidity", "pressure"}
        assert sample.unit_hints == {
            "temperature": "degC",
            "humidity": "%",
            "pressure": "hPa",
        }
