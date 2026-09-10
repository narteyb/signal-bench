# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from tests.fixtures.mock_serial import MockSerialChannel, Scenario
from tests.fixtures.test_helpers import TestMCUAdapter, make_mcu_config, with_test_timeout

pytestmark = pytest.mark.asyncio


async def test_prepare_opens_serial_connection(mock_serial_channel: MockSerialChannel) -> None:
    scenario = mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config())

    await with_test_timeout(adapter.prepare("run-1"))

    assert scenario is mock_serial_channel.scenario
    assert adapter._reader is not None
    assert adapter._writer is not None
    assert adapter._run_id == "run-1"
    assert mock_serial_channel.calls == [
        {"args": (), "kwargs": {"url": "mock://mcu", "baudrate": 115_200}}
    ]


async def test_prepare_calls_flash_firmware_when_flag_true(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config(flash_before_prepare=True))

    await with_test_timeout(adapter.prepare("run-1"))

    assert adapter.flash_calls == 1


async def test_prepare_skips_flash_when_flag_false(
    mock_serial_channel: MockSerialChannel,
) -> None:
    mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config())

    await with_test_timeout(adapter.prepare("run-1"))

    assert adapter.flash_calls == 0


async def test_prepare_idempotent(mock_serial_channel: MockSerialChannel) -> None:
    mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config(flash_before_prepare=True))

    await with_test_timeout(adapter.prepare("run-1"))
    original_reader = adapter._reader
    original_writer = adapter._writer
    await with_test_timeout(adapter.prepare("run-2"))

    assert adapter._reader is original_reader
    assert adapter._writer is original_writer
    assert adapter._run_id == "run-2"
    assert adapter.flash_calls == 1
    assert len(mock_serial_channel.calls) == 1


async def test_teardown_closes_serial_connection(mock_serial_channel: MockSerialChannel) -> None:
    mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config())
    await with_test_timeout(adapter.prepare("run-1"))
    writer = adapter._writer

    await with_test_timeout(adapter.teardown())

    assert writer is not None
    assert writer.is_closing()
    assert adapter._reader is None
    assert adapter._writer is None
    assert adapter._run_id is None


async def test_teardown_idempotent(mock_serial_channel: MockSerialChannel) -> None:
    mock_serial_channel.use(Scenario())
    adapter = TestMCUAdapter(make_mcu_config())

    await with_test_timeout(adapter.teardown())
    await with_test_timeout(adapter.prepare("run-1"))
    await with_test_timeout(adapter.teardown())
    await with_test_timeout(adapter.teardown())

    assert adapter._reader is None
    assert adapter._writer is None


async def test_warmup_default_no_op() -> None:
    adapter = TestMCUAdapter(make_mcu_config())

    await with_test_timeout(adapter.warmup())
