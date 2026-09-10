# SPDX-License-Identifier: Apache-2.0
"""Mock INA219 telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

INA219_UNIT_HINTS = {"voltage": "V", "current": "A", "power": "W"}


@dataclass(frozen=True, slots=True)
class MockINA219Config:
    """Configuration for a synthetic INA219 rail monitor."""

    name: str = "mock_ina219_main"
    sample_rate_hz: float = 50.0
    nominal_voltage_v: float = 3.3
    voltage_drift_v: float = 0.05
    min_current_a: float = 0.05
    max_current_a: float = 0.5


class MockINA219Source(TelemetrySource):
    """Synthetic INA219 source with plausible electrical telemetry."""

    source_name = "mock_ina219_main"
    sample_rate_hz = 50.0
    partial_coverage_threshold = 0.75

    def __init__(self: Self, config: MockINA219Config | None = None) -> None:
        """Create a mock INA219 source."""
        self._config = config or MockINA219Config()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._started_at: float | None = None
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return the stable telemetry source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Start synthetic INA219 sample generation."""
        self._started_at = time.monotonic()
        self._stopping = False

    async def stop(self: Self) -> None:
        """Stop synthetic INA219 sample generation."""
        self._stopping = True

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield grouped voltage/current/power samples until stopped."""
        if self._started_at is None:
            msg = "MockINA219Source must be started before samples() is consumed"
            raise SourceStartError(msg)

        period_s = 1.0 / self._config.sample_rate_hz
        while not self._stopping:
            elapsed = time.monotonic() - self._started_at
            voltage = self._voltage_at(elapsed)
            current = self._current_at(elapsed)
            power = voltage * current
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values={"voltage": voltage, "current": current, "power": power},
                unit_hints=INA219_UNIT_HINTS,
            )
            await asyncio.sleep(period_s)

    def _voltage_at(self: Self, elapsed_s: float) -> float:
        return self._config.nominal_voltage_v + self._config.voltage_drift_v * math.sin(
            2 * math.pi * elapsed_s / 60.0,
        )

    def _current_at(self: Self, elapsed_s: float) -> float:
        midpoint = (self._config.max_current_a + self._config.min_current_a) / 2.0
        amplitude = (self._config.max_current_a - self._config.min_current_a) / 2.0
        return midpoint + amplitude * math.sin(2 * math.pi * elapsed_s / 10.0)
