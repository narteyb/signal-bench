# SPDX-License-Identifier: Apache-2.0
"""The measured image and the reported image must be the same build."""

import asyncio

import pytest

from scripts.run_p3_mcu_matrix import CPP_TEMPLATE, _audit_firmware_behavior
from signal_bench.adapters.mcu.frames import FrameParser, MetadataFrame
from signal_bench.telemetry.session_contract import SessionContractError, make_session_contract
from tests.fixtures.test_helpers import TestMCUAdapter, make_mcu_config


def test_metadata_frame_roundtrip() -> None:
    values = {"build_id": "abc", "wifi_initialized": False}
    frame = FrameParser().parse(MetadataFrame(values).serialize())
    assert isinstance(frame, MetadataFrame)
    assert frame.values == values


def test_session_contract_rejects_flashing_a_different_build() -> None:
    build = {"build_id": "expected", "source_commit": "sha", "firmware_sha256": "image"}
    firmware = {
        "build_id": "different",
        "source_commit": "sha",
        "wifi_initialized": False,
        "bluetooth_initialized": False,
        "radio_basis": "runtime_controller_query",
        "sleep_calls_during_inference": 0,
        "loop_pacing_ms": 0,
        "regulator_mode": {"nrf_dcdc_enabled": False},
    }
    boundary = {"rail": "E5V", "components_inside": ["board"], "source": "rig config"}
    with pytest.raises(SessionContractError, match="build_id differs"):
        make_session_contract(build=build, firmware=firmware, boundary=boundary)
    firmware["build_id"] = "expected"
    contract = make_session_contract(build=build, firmware=firmware, boundary=boundary)
    assert contract["firmware_build_sha256"] == "image"
    assert contract["power_boundary"]["rail"] == "E5V"


def test_generated_firmware_behavior_is_checked_from_source() -> None:
    assert _audit_firmware_behavior(CPP_TEMPLATE) == {
        "sleep_calls_during_inference": 0,
        "loop_pacing_ms": 0,
    }
    changed = CPP_TEMPLATE.replace(
        "  emit_done(iterations);", "  delay(5);\n  emit_done(iterations);"
    )
    assert _audit_firmware_behavior(changed)["loop_pacing_ms"] == 5
    with pytest.raises(ValueError, match="radio initialization"):
        _audit_firmware_behavior(
            CPP_TEMPLATE.replace(
                "  emit_done(iterations);", "  WiFi.begin();\n  emit_done(iterations);"
            )
        )


@pytest.mark.asyncio
async def test_adapter_queries_firmware_before_measurement() -> None:
    class Writer:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    adapter = TestMCUAdapter(make_mcu_config())
    reader = asyncio.StreamReader()
    reader.feed_data(MetadataFrame({"build_id": "abc"}).serialize().encode())
    writer = Writer()
    adapter._reader = reader
    adapter._writer = writer  # type: ignore[assignment]
    assert await adapter.read_firmware_metadata() == {"build_id": "abc"}
    assert writer.writes == [b"META\n"]
