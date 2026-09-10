# SPDX-License-Identifier: Apache-2.0
import asyncio
import math

import pytest

from signal_bench.telemetry.base import TelemetrySample
from signal_bench.telemetry.exceptions import SourceStartError
from signal_bench.telemetry.sources import MockINA219Config, MockINA219Source


async def _collect(source: MockINA219Source, count: int) -> list:
    samples = []
    async for sample in source.samples():
        samples.append(sample)
        if len(samples) >= count:
            break
    return samples


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


@pytest.mark.asyncio
async def test_mock_ina219_requires_start() -> None:
    source = MockINA219Source()
    iterator = source.samples()

    with pytest.raises(SourceStartError):
        await anext(iterator)


@pytest.mark.asyncio
async def test_mock_ina219_emits_expected_metrics_and_ranges() -> None:
    source = MockINA219Source(MockINA219Config(sample_rate_hz=20.0))
    await source.start()

    samples = await _collect(source, 5)
    await source.stop()

    assert {sample.source_name for sample in samples} == {"mock_ina219_main"}
    for sample in samples:
        values = _sample_values(sample)
        assert set(values) == {"voltage", "current", "power"}
        assert 3.25 <= values["voltage"] <= 3.35
        assert 0.05 <= values["current"] <= 0.5
        assert sample.unit_hints == {"voltage": "V", "current": "A", "power": "W"}


@pytest.mark.asyncio
async def test_mock_ina219_rate_is_close_to_configured_rate() -> None:
    source = MockINA219Source(MockINA219Config(sample_rate_hz=20.0))
    await source.start()

    started = asyncio.get_running_loop().time()
    await _collect(source, 8)
    elapsed = asyncio.get_running_loop().time() - started
    await source.stop()

    assert elapsed == pytest.approx(7 / 20.0, rel=0.35)


@pytest.mark.asyncio
async def test_mock_ina219_power_matches_voltage_times_current() -> None:
    source = MockINA219Source(MockINA219Config(sample_rate_hz=10.0))
    await source.start()

    sample = (await _collect(source, 1))[0]
    await source.stop()
    values = _sample_values(sample)

    assert values["power"] == pytest.approx(
        values["voltage"] * values["current"],
    )


@pytest.mark.asyncio
async def test_mock_ina219_stop_halts_emission() -> None:
    source = MockINA219Source(MockINA219Config(sample_rate_hz=50.0))
    await source.start()
    iterator = source.samples()

    await anext(iterator)
    await source.stop()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(iterator), timeout=0.1)


def test_mock_ina219_current_profile_bounds() -> None:
    source = MockINA219Source()

    values = [source._current_at(t) for t in range(21)]

    assert min(values) >= 0.05
    assert max(values) <= 0.5
    assert any(not math.isclose(values[0], value) for value in values[1:])
