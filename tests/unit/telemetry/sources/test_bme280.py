# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Never

import pytest

from signal_bench.telemetry.exceptions import SourceDataError, SourceStartError
from signal_bench.telemetry.sources.bme280 import Bme280Config, Bme280Source


class _FakeBME280:
    temperature = 24.5
    relative_humidity = 46.25
    pressure = 1012.8


class _FailingBME280:
    @property
    def temperature(self) -> Never:
        message = "i2c read failed"
        raise OSError(message)

    relative_humidity = 0.0
    pressure = 0.0


def _sample_values(sample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


@pytest.mark.asyncio
async def test_bme280_source_yields_grouped_ambient_values() -> None:
    source = Bme280Source(Bme280Config(sample_rate_hz=20.0), sensor=_FakeBME280())

    await source.start()
    sample = await anext(source.samples())
    await source.stop()

    assert source.name == "bme280"
    assert _sample_values(sample) == {
        "temperature": pytest.approx(24.5),
        "humidity": pytest.approx(46.25),
        "pressure": pytest.approx(1012.8),
    }
    assert sample.unit_hints == {"temperature": "degC", "humidity": "%", "pressure": "hPa"}


def test_bme280_legacy_sample_returns_scalar_rows() -> None:
    source = Bme280Source(sensor=_FakeBME280())
    source.open()

    samples = source.sample()

    assert [sample.metric for sample in samples] == ["temperature", "humidity", "pressure"]
    assert [sample.source for sample in samples] == ["bme280", "bme280", "bme280"]


@pytest.mark.asyncio
async def test_bme280_read_error_marks_source_data_error() -> None:
    source = Bme280Source(sensor=_FailingBME280())

    with pytest.raises(SourceStartError):
        await source.start()

    source = Bme280Source(sensor=_FakeBME280())
    await source.start()
    source._sensor = _FailingBME280()

    with pytest.raises(SourceDataError):
        await anext(source.samples())


def test_bme280_factory_receives_bus_and_address() -> None:
    calls = []

    def _factory(bus: object, address: int) -> _FakeBME280:
        calls.append((bus, address))
        return _FakeBME280()

    bus = object()
    source = Bme280Source(Bme280Config(address=0x76), i2c_bus=bus, sensor_factory=_factory)
    source.open()

    assert calls == [(bus, 0x76)]
