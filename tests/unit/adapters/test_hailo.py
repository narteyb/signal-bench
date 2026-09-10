# SPDX-License-Identifier: Apache-2.0
"""Tests for the Hailo-10H adapter preflight guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from signal_bench.adapters import HailoAdapter, HailoAdapterConfig
from signal_bench.adapters.exceptions import ConfigurationError, PrepareError
from signal_bench.adapters.hailo import NPU_NOT_READY_MESSAGE, preflight_hailo10h


def _completed(
    stdout: str,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["hailortcli", "fw-control", "identify"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_preflight_fails_loudly_when_device_node_missing() -> None:
    with pytest.raises(PrepareError, match="NPU not ready"):
        preflight_hailo10h(
            command_runner=lambda _command: _completed(""),
            path_exists=lambda _path: False,
        )


def test_preflight_fails_loudly_when_architecture_is_not_hailo10h() -> None:
    output = """
Executing on device: 0001:01:00.0
Identifying board
Firmware Version: 5.1.1 (release,app)
Device Architecture: HAILO8L
"""

    with pytest.raises(PrepareError) as exc_info:
        preflight_hailo10h(
            command_runner=lambda _command: _completed(output),
            path_exists=lambda path: path == Path("/dev/hailo0"),
        )

    assert str(exc_info.value) == NPU_NOT_READY_MESSAGE
    assert "dkms autoinstall" in str(exc_info.value)
    assert "modprobe hailo1x_pci" in str(exc_info.value)


def test_preflight_parses_hailo10h_identity() -> None:
    output = """
Executing on device: 0001:01:00.0
Identifying board
Control Protocol Version: 2
Firmware Version: 5.1.1 (release,app)
Logger Version: 0
Device Architecture: HAILO10H
"""

    info = preflight_hailo10h(
        command_runner=lambda _command: _completed(output),
        path_exists=lambda path: path == Path("/dev/hailo0"),
    )

    assert info.architecture == "HAILO10H"
    assert info.firmware_version == "5.1.1 (release,app)"
    assert "Device Architecture: HAILO10H" in info.identify_output


def test_adapter_rejects_invalid_batch_size() -> None:
    with pytest.raises(ConfigurationError, match="batch_size"):
        HailoAdapter(
            HailoAdapterConfig(
                target_id="pi5-hailo10h",
                hef_path=Path("model.hef"),
                batch_size=0,
            ),
        )
