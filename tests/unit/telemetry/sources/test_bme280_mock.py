# SPDX-License-Identifier: Apache-2.0
import asyncio

import pytest

from signal_bench.telemetry.base import TelemetrySample
from signal_bench.telemetry.exceptions import SourceStartError
from signal_bench.telemetry.sources import MockBME280Config, MockBME280Source


async def _collect(source: MockBME280Source, count: int) -> list:
    samples = []
    async for sample in source.samples():
        samples.append(sample)
        if len(samples) >= count:
            break
    return samples


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


@pytest.mark.asyncio
async def test_mock_bme280_requires_start() -> None:
    source = MockBME280Source()
    iterator = source.samples()

    with pytest.raises(SourceStartError):
        await anext(iterator)


@pytest.mark.asyncio
async def test_mock_bme280_emits_expected_metrics_and_ranges() -> None:
    source = MockBME280Source(MockBME280Config(sample_rate_hz=10.0))
    await source.start()

    samples = await _collect(source, 5)
    await source.stop()

    assert {sample.source_name for sample in samples} == {"mock_bme280_lab"}
    for sample in samples:
        values = _sample_values(sample)
        assert set(values) == {"temperature", "humidity", "pressure"}
        assert 22.0 <= values["temperature"] <= 26.0
        assert 35.0 <= values["humidity"] <= 55.0
        assert 1010.0 <= values["pressure"] <= 1020.0
        assert sample.unit_hints == {
            "temperature": "degC",
            "humidity": "%",
            "pressure": "hPa",
        }


@pytest.mark.asyncio
async def test_mock_bme280_default_rate_is_about_one_hz() -> None:
    source = MockBME280Source()
    await source.start()

    started = asyncio.get_running_loop().time()
    await _collect(source, 2)
    elapsed = asyncio.get_running_loop().time() - started
    await source.stop()

    assert elapsed == pytest.approx(1.0, rel=0.35)


@pytest.mark.asyncio
async def test_mock_bme280_stop_halts_emission() -> None:
    source = MockBME280Source(MockBME280Config(sample_rate_hz=20.0))
    await source.start()
    iterator = source.samples()

    await anext(iterator)
    await source.stop()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(iterator), timeout=0.1)


@pytest.mark.asyncio
async def test_mock_bme280_seeded_random_walk_is_repeatable() -> None:
    left = MockBME280Source(MockBME280Config(sample_rate_hz=10.0, random_seed=7))
    right = MockBME280Source(MockBME280Config(sample_rate_hz=10.0, random_seed=7))
    await left.start()
    await right.start()

    left_samples = await _collect(left, 3)
    right_samples = await _collect(right, 3)
    await left.stop()
    await right.stop()

    assert [_sample_values(sample) for sample in left_samples] == [
        _sample_values(sample) for sample in right_samples
    ]
