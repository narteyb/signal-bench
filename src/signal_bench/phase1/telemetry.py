# SPDX-License-Identifier: Apache-2.0
"""Phase 1 telemetry-source helpers and synthetic dual-meter sources."""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class SyntheticPowerConfig:
    """Configuration for deterministic Phase 1 power telemetry."""

    name: str
    sample_rate_hz: float = 20.0
    base_power_w: float = 8.0
    ripple_w: float = 0.25
    multiplier: float = 1.0


class SyntheticPowerSource(TelemetrySource):
    """Deterministic grouped power source for host-only harness tests."""

    partial_coverage_threshold = 0.90

    def __init__(self: Self, config: SyntheticPowerConfig) -> None:
        self._config = config
        self.source_name = config.name
        self.sample_rate_hz = config.sample_rate_hz
        self._started_at: float | None = None
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Start deterministic sample emission."""
        self._started_at = time.monotonic()
        self._stopping = False

    async def stop(self: Self) -> None:
        """Stop deterministic sample emission."""
        self._stopping = True

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield grouped voltage/current/power samples."""
        if self._started_at is None:
            msg = "SyntheticPowerSource must be started before samples()"
            raise RuntimeError(msg)
        period_s = 1.0 / self.sample_rate_hz
        while not self._stopping:
            elapsed = time.monotonic() - self._started_at
            power = self._config.multiplier * (
                self._config.base_power_w + self._config.ripple_w * math.sin(elapsed * 2.0)
            )
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values={"voltage": 5.0, "current": power / 5.0, "power": power},
                unit_hints={"voltage": "V", "current": "A", "power": "W"},
            )
            await asyncio.sleep(period_s)


def default_mock_sources() -> tuple[TelemetrySource, ...]:
    """Return synthetic primary and cross-check power sources for host slice."""
    return (
        SyntheticPowerSource(SyntheticPowerConfig(name="mock_wall_fnb58", sample_rate_hz=25.0)),
        SyntheticPowerSource(
            SyntheticPowerConfig(name="mock_rail_ina219", sample_rate_hz=25.0, multiplier=0.98),
        ),
    )
