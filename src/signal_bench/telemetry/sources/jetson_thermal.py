# SPDX-License-Identifier: Apache-2.0
"""Jetson sysfs thermal telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class JetsonThermalConfig:
    """Configuration for Jetson thermal-zone polling."""

    name: str = "jetson_thermal"
    thermal_root: Path = Path("/sys/class/thermal")
    sample_rate_hz: float = 1.0 / 2.4


class JetsonThermalSource(TelemetrySource):
    """Async source for Jetson thermal zones."""

    source_name = "jetson_thermal"
    sample_rate_hz = 1.0 / 2.4
    partial_coverage_threshold = 0.75

    def __init__(self: Self, config: JetsonThermalConfig | None = None) -> None:
        """Create a Jetson thermal source."""
        self._config = config or JetsonThermalConfig()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._zones: dict[str, Path] = {}
        self._unit_hints: dict[str, str] = {}
        self._started = False
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return the source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Discover readable thermal zones."""
        if self._started:
            return
        self._zones = _discover_zones(self._config.thermal_root)
        if not self._zones:
            msg = f"no readable Jetson thermal zones found under {self._config.thermal_root}"
            raise SourceStartError(msg)
        self._unit_hints = dict.fromkeys(self._zones, "C")
        self._started = True
        self._stopping = False

    async def stop(self: Self) -> None:
        """Stop polling."""
        self._stopping = True
        self._started = False

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield grouped thermal-zone samples in Celsius."""
        if not self._started:
            msg = "JetsonThermalSource must be started before samples() is consumed"
            raise SourceStartError(msg)
        period_s = 1.0 / self._config.sample_rate_hz
        while not self._stopping:
            values = _read_zones(self._zones)
            if not values:
                msg = "all Jetson thermal zones failed to read"
                raise SourceDataError(msg)
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values=values,
                unit_hints=self._unit_hints,
            )
            await asyncio.sleep(period_s)


def _discover_zones(root: Path) -> dict[str, Path]:
    zones: dict[str, Path] = {}
    for zone in sorted(root.glob("thermal_zone*")):
        type_path = zone / "type"
        temp_path = zone / "temp"
        if not type_path.exists() or not temp_path.exists():
            continue
        try:
            metric = _metric_name(type_path.read_text(encoding="utf-8").strip())
            _ = _read_temp_c(temp_path)
        except (OSError, TypeError, ValueError):
            continue
        zones[metric] = temp_path
    return zones


def _read_zones(zones: dict[str, Path]) -> dict[str, float]:
    values: dict[str, float] = {}
    for metric, path in zones.items():
        try:
            values[metric] = _read_temp_c(path)
        except (OSError, TypeError, ValueError):
            continue
    return values


def _read_temp_c(path: Path) -> float:
    return float(path.read_text(encoding="utf-8").strip()) / 1000.0


def _metric_name(zone_type: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", zone_type.strip().lower()).strip("_")
    return f"{normalized}_c"
