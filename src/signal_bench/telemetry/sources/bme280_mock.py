# SPDX-License-Identifier: Apache-2.0
"""Mock BME280 telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

BME280_UNIT_HINTS = {"temperature": "degC", "humidity": "%", "pressure": "hPa"}


@dataclass(frozen=True, slots=True)
class MockBME280Config:
    """Configuration for a synthetic BME280 ambient sensor."""

    name: str = "mock_bme280_lab"
    sample_rate_hz: float = 1.0
    random_seed: int = 42
    initial_temperature_c: float = 24.0
    initial_humidity_pct: float = 45.0
    initial_pressure_hpa: float = 1013.0


class MockBME280Source(TelemetrySource):
    """Synthetic BME280 source with bounded indoor-lab random walks."""

    source_name = "mock_bme280_lab"
    sample_rate_hz = 1.0

    def __init__(self: Self, config: MockBME280Config | None = None) -> None:
        """Create a mock BME280 source."""
        self._config = config or MockBME280Config()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._rng = random.Random(self._config.random_seed)  # noqa: S311 - deterministic mock.
        self._temperature = self._config.initial_temperature_c
        self._humidity = self._config.initial_humidity_pct
        self._pressure = self._config.initial_pressure_hpa
        self._started = False
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return the stable telemetry source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Start synthetic BME280 sample generation."""
        self._started = True
        self._stopping = False

    async def stop(self: Self) -> None:
        """Stop synthetic BME280 sample generation."""
        self._stopping = True

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield grouped temperature/humidity/pressure samples until stopped."""
        if not self._started:
            msg = "MockBME280Source must be started before samples() is consumed"
            raise SourceStartError(msg)

        period_s = 1.0 / self._config.sample_rate_hz
        while not self._stopping:
            self._walk_values()
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values={
                    "temperature": self._temperature,
                    "humidity": self._humidity,
                    "pressure": self._pressure,
                },
                unit_hints=BME280_UNIT_HINTS,
            )
            await asyncio.sleep(period_s)

    def _walk_values(self: Self) -> None:
        self._temperature = _clamp(self._temperature + self._rng.gauss(0.0, 0.05), 22.0, 26.0)
        self._humidity = _clamp(self._humidity + self._rng.gauss(0.0, 0.2), 35.0, 55.0)
        self._pressure = _clamp(self._pressure + self._rng.gauss(0.0, 0.1), 1010.0, 1020.0)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))
