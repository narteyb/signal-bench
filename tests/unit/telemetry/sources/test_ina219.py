# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Never

import pytest

from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.sources.ina219 import Ina219Config, Ina219Source


class _FakeINA219:
    bus_voltage = 3.31
    current = 123.0
    power = 0.40713


class _FailingINA219:
    @property
    def bus_voltage(self) -> Never:
        message = "i2c read failed"
        raise OSError(message)

    current = 0.0
    power = 0.0


def _sample_values(sample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


@pytest.mark.asyncio
async def test_ina219_source_yields_grouped_canonical_units() -> None:
    source = Ina219Source(Ina219Config(sample_rate_hz=100.0), sensor=_FakeINA219())

    await source.start()
    sample = await anext(source.samples())
    await source.stop()

    assert source.name == "ina219"
    assert _sample_values(sample) == {
        "voltage": pytest.approx(3.31),
        "current": pytest.approx(0.123),
        "power": pytest.approx(0.40713),
    }
    assert sample.unit_hints == {"voltage": "V", "current": "A", "power": "W"}


def test_ina219_legacy_sample_returns_scalar_rows() -> None:
    source = Ina219Source(sensor=_FakeINA219())
    source.open()

    samples = source.sample()

    assert [sample.metric for sample in samples] == ["voltage", "current", "power"]
    assert [sample.source for sample in samples] == ["ina219", "ina219", "ina219"]


@pytest.mark.asyncio
async def test_ina219_read_error_marks_source_data_error() -> None:
    source = Ina219Source(sensor=_FailingINA219())

    with pytest.raises(SourceStartError):
        await source.start()

    source = Ina219Source(sensor=_FakeINA219())
    await source.start()
    source._sensor = _FailingINA219()

    with pytest.raises(SourceDataError):
        await anext(source.samples())


def test_ina219_factory_receives_bus_and_address() -> None:
    calls = []

    def _factory(bus: object, address: int) -> _FakeINA219:
        calls.append((bus, address))
        return _FakeINA219()

    bus = object()
    source = Ina219Source(Ina219Config(address=0x41), i2c_bus=bus, sensor_factory=_factory)
    source.open()

    assert calls == [(bus, 0x41)]
