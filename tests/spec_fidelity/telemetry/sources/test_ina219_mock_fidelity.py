# SPDX-License-Identifier: Apache-2.0
"""Spec-fidelity tests for MockINA219Source.

These checks lock the T7.4 source contract for the mocked INA219 power rail:
canonical metric names, source naming, unit hints, and realistic default rate.
"""

from __future__ import annotations

import pytest

from signal_bench.telemetry import TelemetrySample, TelemetrySource
from signal_bench.telemetry.sources import MockINA219Config, MockINA219Source


async def _first_sample(source: MockINA219Source) -> TelemetrySample:
    await source.start()
    try:
        async for sample in source.samples():
            return sample
    finally:
        await source.stop()
    pytest.fail("mock INA219 source did not emit a sample")


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


class TestMockINA219SourceFidelity:
    """Architecture-facing fidelity checks for the mocked INA219 source."""

    def test_implements_telemetry_source_contract(self) -> None:
        """TelemetrySource contract: mock INA219 is a concrete async source."""
        assert issubclass(MockINA219Source, TelemetrySource)
        assert isinstance(MockINA219Source.source_name, str)
        assert MockINA219Source.source_name == "mock_ina219_main"
        assert isinstance(MockINA219Source.sample_rate_hz, float)
        assert MockINA219Source.sample_rate_hz == 50.0

    def test_default_config_uses_mock_identity_prefix(self) -> None:
        """T7.4 fidelity: placeholder sources use a mock_* source_name prefix."""
        config = MockINA219Config()

        assert config.name == "mock_ina219_main"
        assert config.name.startswith("mock_")

    @pytest.mark.asyncio
    async def test_emits_canonical_power_metrics(self) -> None:
        """T7.4 fidelity: INA219 emits voltage/current/power with V/A/W units."""
        sample = await _first_sample(MockINA219Source())

        assert sample.source_name == "mock_ina219_main"
        assert set(_sample_values(sample)) == {"voltage", "current", "power"}
        assert sample.unit_hints == {"voltage": "V", "current": "A", "power": "W"}
