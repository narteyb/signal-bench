# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt

import pytest

from signal_bench.adapters.base import ThermalReading
from signal_bench.adapters.exceptions import PrepareError
from tests.fixtures.test_helpers import (
    TestMCUAdapter,
    ThermalTestMCUAdapter,
    make_mcu_config,
    with_test_timeout,
)

pytestmark = pytest.mark.asyncio


async def test_read_thermal_default_unavailable() -> None:
    adapter = TestMCUAdapter(make_mcu_config())

    reading = await with_test_timeout(adapter.read_thermal())

    assert reading == ThermalReading(available=False)


async def test_read_thermal_subclass_override() -> None:
    timestamp = dt.datetime.now(tz=dt.UTC)
    expected = ThermalReading(
        available=True,
        temperature_c=42.5,
        sensor="test-sensor",
        timestamp=timestamp,
    )
    adapter = ThermalTestMCUAdapter(make_mcu_config(), thermal_reading=expected)

    reading = await with_test_timeout(adapter.read_thermal())

    assert reading == expected


async def test_os_info_returns_target_info() -> None:
    adapter = TestMCUAdapter(
        make_mcu_config(target_id="test-target"),
        firmware_version="firmware-123",
    )

    info = await with_test_timeout(adapter.os_info())

    assert info.target_name == "test-target"
    assert info.firmware_version == "firmware-123"
    assert info.additional == {}
    assert adapter.firmware_version_calls == 1


async def test_os_info_timeout_raises_prepare_error() -> None:
    adapter = TestMCUAdapter(
        make_mcu_config(prepare_s=0.01),
        firmware_delay_s=0.05,
    )

    with pytest.raises(PrepareError, match="firmware version read timed out"):
        await with_test_timeout(adapter.os_info())
