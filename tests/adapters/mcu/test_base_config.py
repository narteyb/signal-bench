# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from signal_bench.adapters.exceptions import ConfigurationError, MeasureError
from tests.fixtures.mock_serial import MockSerialChannel, timeout_scenario
from tests.fixtures.test_helpers import (
    TestMCUAdapter,
    make_mcu_config,
    make_task,
    with_test_timeout,
)

pytestmark = pytest.mark.asyncio


async def test_custom_serial_port_passed_to_open_connection(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(timeout_scenario(delay_s=0.0))
    adapter = TestMCUAdapter(make_mcu_config(serial_port="mock://custom"))

    await with_test_timeout(adapter.prepare("run-1"))

    kwargs = mock_serial_channel.calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["url"] == "mock://custom"


async def test_custom_baud_rate_passed_to_open_connection(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(timeout_scenario(delay_s=0.0))
    adapter = TestMCUAdapter(make_mcu_config(baud_rate=230_400))

    await with_test_timeout(adapter.prepare("run-1"))

    kwargs = mock_serial_channel.calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["baudrate"] == 230_400


async def test_custom_timeouts_respected(mock_serial_channel: MockSerialChannel) -> None:
    mock_serial_channel.use(timeout_scenario(delay_s=0.05))
    adapter = TestMCUAdapter(make_mcu_config(measure_per_iteration_s=0.01))
    await with_test_timeout(adapter.prepare("run-1"))

    async def consume() -> None:
        async for _result in adapter.measure(make_task(), 1):
            pass

    with pytest.raises(MeasureError, match="serial read timed out"):
        await with_test_timeout(consume())


async def test_blank_serial_port_rejected() -> None:
    with pytest.raises(ConfigurationError, match="serial_port must be set"):
        TestMCUAdapter(make_mcu_config(serial_port="   "))


async def test_non_positive_baud_rate_rejected() -> None:
    with pytest.raises(ConfigurationError, match="baud_rate must be positive"):
        TestMCUAdapter(make_mcu_config(baud_rate=0))
