# SPDX-License-Identifier: Apache-2.0
"""Command-flashed MCU adapter implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Self

from signal_bench.adapters.exceptions import PrepareError
from signal_bench.adapters.mcu.base import MCUAdapterBase


class CommandMCUAdapter(MCUAdapterBase):
    """MCU adapter that flashes firmware by running a configured shell command.

    The serial measurement protocol remains the shared ``MCUAdapterBase``
    protocol. This subclass only supplies the board/toolchain-specific flashing
    hook needed by hardware runners.
    """

    async def _flash_firmware(self: Self) -> None:
        command = self.config.flash_command
        if command is None or not command:
            msg = "flash_before_prepare requires MCUAdapterConfig.flash_command"
            raise PrepareError(msg)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            output = b"\n".join(part for part in (stdout, stderr) if part).decode(
                "utf-8",
                errors="replace",
            )
            msg = f"MCU flash command failed with exit code {process.returncode}: {output}"
            raise PrepareError(msg)
        if self.config.post_flash_delay_s > 0:
            await asyncio.sleep(self.config.post_flash_delay_s)

    async def _get_firmware_version(self: Self) -> str:
        if self.config.firmware_path is None:
            return "unknown"
        path = Path(self.config.firmware_path)
        return path.name or str(path)
