# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import math
import os
from typing import TYPE_CHECKING

import pytest

from signal_bench.telemetry.sources import Bme280Config, Bme280Source, Ina219Config, Ina219Source

if TYPE_CHECKING:
    from signal_bench.telemetry import TelemetrySample

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.hardware,
    pytest.mark.skipif(
        not os.getenv("SIGNAL_BENCH_HW"),
        reason="SIGNAL_BENCH_HW not set; hardware telemetry tests skipped",
    ),
]


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


async def test_real_i2c_sources_30s_sample_counts() -> None:
    ina219_address = int(os.environ.get("INA219_ADDRESS", "0x40"), 0)
    bme280_address = int(os.environ.get("BME280_ADDRESS", "0x77"), 0)
    ina219 = Ina219Source(Ina219Config(address=ina219_address))
    bme280 = Bme280Source(Bme280Config(address=bme280_address))
    ina219_samples: list[TelemetrySample] = []
    bme280_samples: list[TelemetrySample] = []

    duration_s = 30.5
    await ina219.start()
    await bme280.start()
    try:
        async with asyncio.timeout(duration_s):
            async with asyncio.TaskGroup() as task_group:
                task_group.create_task(
                    _collect(
                        ina219,
                        ina219_samples,
                        _minimum_samples(ina219.sample_rate_hz, duration_s, 0.75),
                    ),
                )
                task_group.create_task(
                    _collect(
                        bme280,
                        bme280_samples,
                        _minimum_samples(bme280.sample_rate_hz, duration_s, 0.75),
                    ),
                )
    finally:
        await ina219.stop()
        await bme280.stop()

    assert len(ina219_samples) >= _minimum_samples(ina219.sample_rate_hz, duration_s, 0.75)
    assert len(bme280_samples) >= _minimum_samples(bme280.sample_rate_hz, duration_s, 0.75)
    assert all(
        set(_sample_values(sample)) == {"voltage", "current", "power"} for sample in ina219_samples
    )
    assert all(
        set(_sample_values(sample)) == {"temperature", "humidity", "pressure"}
        for sample in bme280_samples
    )


async def _collect(
    source: Ina219Source | Bme280Source,
    samples: list[TelemetrySample],
    target_count: int,
) -> None:
    async for sample in source.samples():
        samples.append(sample)
        if len(samples) >= target_count:
            return


def _minimum_samples(sample_rate_hz: float, duration_s: float, coverage: float) -> int:
    return math.floor(sample_rate_hz * duration_s * coverage)
