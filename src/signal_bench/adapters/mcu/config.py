# SPDX-License-Identifier: Apache-2.0
"""Configuration dataclasses for MCU adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from signal_bench.adapters.base import AdapterConfig

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class MCUAdapterConfig(AdapterConfig):
    """Configuration shared by USB-CDC MCU adapters."""

    serial_port: str
    baud_rate: int = 115_200
    flash_command: list[str] | None = None
    firmware_path: Path | None = None
    flash_before_prepare: bool = False
    post_flash_delay_s: float = 0.0
