# SPDX-License-Identifier: Apache-2.0
"""Shared host-side I2C connection for real telemetry sources."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, cast

DEFAULT_I2C_FREQUENCY_HZ = 400_000


@dataclass(slots=True)
class I2CConnection:
    """An I2C bus and the lock protecting its host transport."""

    bus: object
    lock: threading.RLock = field(default_factory=threading.RLock)


_default_connection_guard = threading.Lock()
_default_connection_state: dict[str, I2CConnection | None] = {"connection": None}


def default_i2c_connection() -> I2CConnection:
    """Return the process-wide MCP2221A-backed I2C connection."""
    connection = _default_connection_state["connection"]
    if connection is None:
        with _default_connection_guard:
            connection = _default_connection_state["connection"]
            if connection is None:
                board = cast("Any", import_module("board"))
                busio = cast("Any", import_module("busio"))
                bus = busio.I2C(
                    board.SCL,
                    board.SDA,
                    frequency=DEFAULT_I2C_FREQUENCY_HZ,
                )
                connection = I2CConnection(bus=bus)
                _default_connection_state["connection"] = connection
    return connection
