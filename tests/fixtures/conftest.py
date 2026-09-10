# SPDX-License-Identifier: Apache-2.0
"""Local fixture wiring for direct `pytest tests/fixtures/` runs."""

from __future__ import annotations

import pytest

from tests.fixtures.mock_serial import MockSerialChannel


@pytest.fixture
def mock_serial_channel(monkeypatch: pytest.MonkeyPatch) -> MockSerialChannel:
    """Patch pyserial-asyncio to use a programmable in-memory serial channel."""
    channel = MockSerialChannel()
    monkeypatch.setattr("serial_asyncio.open_serial_connection", channel.open)
    return channel
