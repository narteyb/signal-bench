# SPDX-License-Identifier: Apache-2.0
"""Real INA219 rail-side power telemetry source."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, cast

from signal_bench.telemetry.base import TelemetrySample, TelemetrySource
from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

INA219_UNIT_HINTS = {"voltage": "V", "current": "A", "power": "W"}


@dataclass(frozen=True, slots=True)
class Ina219Config:
    """Configuration for a real INA219 rail-side power monitor."""

    name: str = "ina219"
    sample_rate_hz: float = 8.0
    address: int = 0x40


class Ina219Source(TelemetrySource):
    """Read rail-side voltage, current, and power from an INA219 over I2C."""

    source_name = "ina219"
    sample_rate_hz = 8.0
    partial_coverage_threshold = 0.75

    def __init__(
        self: Self,
        config: Ina219Config | None = None,
        *,
        i2c_bus: object | None = None,
        sensor: object | None = None,
        sensor_factory: Callable[[object, int], object] | None = None,
    ) -> None:
        """Create an INA219 source.

        ``i2c_bus``, ``sensor``, and ``sensor_factory`` are injection seams for
        hardware-free unit tests. Production code leaves them unset and lets
        Blinka construct the MCP2221A/native I2C bus.
        """
        self._config = config or Ina219Config()
        self.source_name = self._config.name
        self.sample_rate_hz = self._config.sample_rate_hz
        self._i2c_bus = i2c_bus
        self._sensor = sensor
        self._sensor_factory = sensor_factory
        self._started = False
        self._stopping = True

    @property
    def name(self: Self) -> str:
        """Return the stable telemetry source name."""
        return self._config.name

    def is_available(self: Self) -> bool:
        """Return whether the INA219 runtime dependencies import successfully."""
        return (
            _module_available("board")
            and _module_available("busio")
            and _module_available(
                "adafruit_ina219",
            )
        )

    async def start(self: Self) -> None:
        """Initialize the INA219 sensor."""
        self.open()

    async def stop(self: Self) -> None:
        """Stop polling the INA219 sensor."""
        self.close()

    async def samples(self: Self) -> AsyncIterator[TelemetrySample]:
        """Yield grouped INA219 samples until stopped."""
        if not self._started:
            msg = "Ina219Source must be started before samples() is consumed"
            raise SourceStartError(msg)

        period_s = 1.0 / self.sample_rate_hz
        next_sample_at = time.monotonic()
        while not self._stopping:
            yield self._read_grouped_sample()
            next_sample_at += period_s
            sleep_s = next_sample_at - time.monotonic()
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            else:
                next_sample_at = time.monotonic()

    def open(self: Self) -> None:
        """Initialize the I2C bus and INA219 driver."""
        if self._started:
            return
        try:
            if self._sensor is None:
                bus = self._i2c_bus if self._i2c_bus is not None else _create_default_i2c_bus()
                self._i2c_bus = bus
                factory = self._sensor_factory or _create_ina219_sensor
                self._sensor = factory(bus, self._config.address)
            self._read_values()
        except Exception as exc:
            msg = f"INA219 unavailable at I2C address 0x{self._config.address:02x}"
            raise SourceStartError(msg) from exc
        self._started = True
        self._stopping = False

    def close(self: Self) -> None:
        """Stop polling. Blinka I2C buses do not require explicit close here."""
        self._stopping = True
        self._started = False

    def sample(self: Self) -> list[TelemetrySample]:
        """Return scalar samples for the legacy threaded collector."""
        if not self._started:
            return []
        timestamp = dt.datetime.now(dt.UTC)
        values = self._read_values()
        return [
            TelemetrySample(
                timestamp=timestamp,
                source=self.source_name,
                metric=metric,
                value=value,
            )
            for metric, value in values.items()
        ]

    def _read_grouped_sample(self: Self) -> TelemetrySample:
        return TelemetrySample(
            timestamp=dt.datetime.now(dt.UTC),
            source_name=self.source_name,
            values=self._read_values(),
            unit_hints=INA219_UNIT_HINTS,
        )

    def _read_values(self: Self) -> dict[str, float]:
        sensor = self._sensor
        if sensor is None:
            msg = "INA219 sensor is not initialized"
            raise SourceStartError(msg)
        try:
            sensor_obj = cast("Any", sensor)
            voltage = _as_float(sensor_obj.bus_voltage)
            current_a = _as_float(sensor_obj.current) / 1000.0
            power = _as_float(sensor_obj.power)
        except Exception as exc:
            msg = "INA219 read failed"
            raise SourceDataError(msg) from exc
        return {"voltage": voltage, "current": current_a, "power": power}


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - Blinka raises RuntimeError when hardware is absent.
        return False
    return True


def _create_default_i2c_bus() -> object:
    board = cast("Any", importlib.import_module("board"))
    busio = cast("Any", importlib.import_module("busio"))
    return busio.I2C(board.SCL, board.SDA)


def _create_ina219_sensor(i2c_bus: object, address: int) -> object:
    module = cast("Any", importlib.import_module("adafruit_ina219"))
    return module.INA219(i2c_bus, addr=address)


def _as_float(value: object) -> float:
    return float(cast("float | int", value))
