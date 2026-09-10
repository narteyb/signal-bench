# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import pytest

from signal_bench.telemetry.sources import FnirsiHidSource, FnirsiHidSourceConfig

if TYPE_CHECKING:
    from signal_bench.telemetry import TelemetrySample

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.hardware,
    pytest.mark.hardware_fnb58,
    pytest.mark.skipif(
        not os.getenv("SIGNAL_BENCH_FNB58_USB_HID"),
        reason="hardware not yet connected",
    ),
]


def _sample_values(sample: TelemetrySample) -> dict[str, float]:
    return object.__getattribute__(sample, "values")


async def test_fnirsi_usb_hid_real_hardware_30s_rate() -> None:
    """Connect to a real FNB58 over USB-HID and verify sustained 100 Hz samples."""
    source = FnirsiHidSource(FnirsiHidSourceConfig())
    samples: list[TelemetrySample] = []
    await source.start()
    try:
        async with asyncio.timeout(30.5):
            async for sample in source.samples():
                samples.append(sample)
                if len(samples) >= 3_000:
                    break
    finally:
        await source.stop()

    assert len(samples) >= 2_900
    assert all(set(_sample_values(sample)) == {"voltage", "current", "power"} for sample in samples)
    assert all(_sample_values(sample)["voltage"] >= 0.0 for sample in samples)
