# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import pytest

from tests.fixtures.mock_serial import MockSerialChannel


@pytest.fixture
def mock_serial_channel(monkeypatch: pytest.MonkeyPatch) -> MockSerialChannel:
    """Patch pyserial-asyncio for isolated MCU adapter test runs."""
    channel = MockSerialChannel()
    monkeypatch.setattr("serial_asyncio.open_serial_connection", channel.open)
    return channel
