# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from signal_bench.adapters.exceptions import PrepareError
from signal_bench.adapters.mcu import CommandMCUAdapter, MCUAdapterConfig


class _Process:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def test_command_adapter_runs_flash_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    sleeps: list[float] = []

    async def fake_exec(*args: str, **kwargs: object) -> _Process:
        assert {"stderr", "stdout"} <= set(kwargs)
        calls.append(tuple(args))
        return _Process(0)

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    adapter = CommandMCUAdapter(
        MCUAdapterConfig(
            target_id="nano33",
            serial_port="/dev/null",
            flash_command=["pio", "run", "-t", "upload"],
            flash_before_prepare=True,
            post_flash_delay_s=3.0,
        ),
    )

    asyncio.run(adapter._flash_firmware())

    assert calls == [("pio", "run", "-t", "upload")]
    assert sleeps == [3.0]


def test_command_adapter_reports_flash_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_exec(*args: str, **kwargs: object) -> _Process:
        assert args
        assert {"stderr", "stdout"} <= set(kwargs)
        return _Process(2, stderr=b"upload failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    adapter = CommandMCUAdapter(
        MCUAdapterConfig(
            target_id="f401re",
            serial_port="/dev/null",
            flash_command=["pio", "run", "-t", "upload"],
            flash_before_prepare=True,
        ),
    )

    with pytest.raises(PrepareError, match="upload failed"):
        asyncio.run(adapter._flash_firmware())


def test_command_adapter_uses_firmware_path_as_version() -> None:
    adapter = CommandMCUAdapter(
        MCUAdapterConfig(
            target_id="esp32s3",
            serial_port="/dev/null",
            firmware_path=Path("firmware.bin"),
        ),
    )

    assert asyncio.run(adapter._get_firmware_version()) == "firmware.bin"
