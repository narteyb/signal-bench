# SPDX-License-Identifier: Apache-2.0
"""Jetson onboard INA3221 telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

JETSON_INA3221_UNIT_HINTS = {"voltage": "V", "current": "A", "power": "W"}


@dataclass(frozen=True, slots=True)
class JetsonIna3221Config:
    """Configuration for Jetson onboard INA3221 rail polling."""

    name: str = "jetson_ina3221"
    rail_label: str = "VDD_IN"
    hwmon_root: Path = Path("/sys/class/hwmon")
    sample_rate_hz: float = 1.0 / 2.4


class JetsonIna3221Source(TelemetrySource):
    """Async source for Jetson whole-board input power via INA3221 VDD_IN."""

    source_name = "jetson_ina3221"
    sample_rate_hz = 1.0 / 2.4
    partial_coverage_threshold = 0.75

    def __init__(self: Self, config: JetsonIna3221Config | None = None) -> None:
        """Create a Jetson INA3221 source."""
        self._config = config or JetsonIna3221Config()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._rail: _RailFiles | None = None
        self._started = False
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return the source name."""
        return self._config.name

    async def start(self: Self) -> None:
        """Find the configured Jetson INA3221 rail and validate one sample."""
        if self._started:
            return
        self._rail = _find_rail(self._config.hwmon_root, self._config.rail_label)
        sample = _read_rail(self._rail)
        if sample["power"] <= 0:
            msg = f"Jetson INA3221 {self._config.rail_label} returned non-positive power"
            raise SourceStartError(msg)
        self._started = True
        self._stopping = False

    async def stop(self: Self) -> None:
        """Stop polling."""
        self._stopping = True
        self._started = False

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield voltage/current/power samples."""
        if not self._started or self._rail is None:
            msg = "JetsonIna3221Source must be started before samples() is consumed"
            raise SourceStartError(msg)
        period_s = 1.0 / self._config.sample_rate_hz
        while not self._stopping:
            values = _read_rail(self._rail)
            if values["power"] <= 0:
                msg = f"Jetson INA3221 returned non-positive power: {values['power']}"
                raise SourceDataError(msg)
            yield TelemetrySample(
                timestamp=dt.datetime.now(dt.UTC),
                source_name=self._config.name,
                values=values,
                unit_hints=JETSON_INA3221_UNIT_HINTS,
            )
            await asyncio.sleep(period_s)


@dataclass(frozen=True, slots=True)
class _RailFiles:
    voltage: Path
    current: Path


def _find_rail(hwmon_root: Path, rail_label: str) -> _RailFiles:
    label = rail_label.casefold()
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        name = _read_text(hwmon / "name")
        if name != "ina3221":
            continue
        for label_file in sorted(hwmon.glob("in*_label")):
            if _read_text(label_file).casefold() != label:
                continue
            index = label_file.name.removeprefix("in").removesuffix("_label")
            voltage = hwmon / f"in{index}_input"
            current = hwmon / f"curr{index}_input"
            if voltage.exists() and current.exists():
                return _RailFiles(voltage=voltage, current=current)
    msg = f"Jetson INA3221 rail {rail_label!r} not found under {hwmon_root}"
    raise SourceStartError(msg)


def _read_rail(files: _RailFiles) -> dict[str, float]:
    try:
        voltage_v = float(_read_text(files.voltage)) / 1000.0
        current_a = float(_read_text(files.current)) / 1000.0
    except OSError as exc:
        msg = f"failed to read Jetson INA3221 rail: {exc}"
        raise SourceDataError(msg) from exc
    return {
        "voltage": voltage_v,
        "current": current_a,
        "power": voltage_v * current_a,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()
