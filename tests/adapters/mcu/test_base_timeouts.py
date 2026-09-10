# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
from typing import cast

import pytest

from signal_bench.adapters.exceptions import MeasureError, PrepareError, TeardownError
from tests.fixtures.mock_serial import MockSerialChannel, Scenario, timeout_scenario
from tests.fixtures.test_helpers import (
    TestMCUAdapter,
    make_mcu_config,
    make_task,
    with_test_timeout,
)

pytestmark = pytest.mark.asyncio


async def test_prepare_timeout_raises_prepare_error() -> None:
    adapter = TestMCUAdapter(
        make_mcu_config(flash_before_prepare=True, prepare_s=0.01),
        flash_delay_s=0.05,
    )

    with pytest.raises(PrepareError, match="prepare timed out"):
        await with_test_timeout(adapter.prepare("run-1"))


async def test_measure_timeout_raises_measure_error(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(timeout_scenario(delay_s=0.05))
    adapter = TestMCUAdapter(make_mcu_config(measure_per_iteration_s=0.01))
    await with_test_timeout(adapter.prepare("run-1"))

    async def consume() -> None:
        async for _result in adapter.measure(make_task(), 1):
            pass

    with pytest.raises(MeasureError, match="serial read timed out"):
        await with_test_timeout(consume())


async def test_teardown_timeout_raises_teardown_error() -> None:
    class SlowClosingWriter:
        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            await asyncio.sleep(0.05)

    adapter = TestMCUAdapter(make_mcu_config(teardown_s=0.01))
    adapter._writer = cast("asyncio.StreamWriter", SlowClosingWriter())

    with pytest.raises(TeardownError, match="teardown timed out"):
        await with_test_timeout(adapter.teardown())


async def test_measure_rejects_non_positive_iterations(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))

    async def consume() -> None:
        async for _result in adapter.measure(make_task(), 0):
            pass

    with pytest.raises(MeasureError, match="iterations must be positive"):
        await with_test_timeout(consume())
