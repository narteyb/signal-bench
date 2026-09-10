# SPDX-License-Identifier: Apache-2.0
import asyncio
import os
from typing import cast

import pytest

from signal_bench.telemetry import TelemetrySample
from signal_bench.telemetry.sources import FnirsiSource, FnirsiSourceConfig

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.hardware,
    pytest.mark.hardware_fnb58,
    pytest.mark.skipif(
        not os.getenv("FNB58_ADDRESS"),
        reason="FNB58_ADDRESS env var not set; FNB58 hardware test skipped",
    ),
]


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return cast("dict[str, float]", object.__getattribute__(sample, "values"))


async def test_fnirsi_real_hardware_30s() -> None:
    """Connect to a real FNB58 and verify live voltage/current/power samples."""
    address = os.environ["FNB58_ADDRESS"]

    source = FnirsiSource(FnirsiSourceConfig(address=address))
    samples: list[TelemetrySample] = []
    await source.start()
    try:
        async with asyncio.timeout(30.0):
            async for sample in source.samples():
                samples.append(sample)
                if len(samples) >= 30:
                    break
    finally:
        await source.stop()

    assert len(samples) >= 30
    assert all(set(_sample_values(sample)) == {"voltage", "current", "power"} for sample in samples)
    assert all(_sample_values(sample)["voltage"] >= 0.0 for sample in samples)
