# SPDX-License-Identifier: Apache-2.0
"""Provenance contract for a metered MCU session.

The firmware reports its own build ID and state before telemetry starts. The
external power path is a rig declaration; the instruments cannot sense which
components are behind their shunts, so that distinction is retained explicitly.
"""

from __future__ import annotations

from typing import Any


class SessionContractError(ValueError):
    """The observed firmware does not match the build being measured."""


def make_session_contract(
    *,
    build: dict[str, Any],
    firmware: dict[str, Any],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    """Validate and combine automatically collected build/firmware/rig facts."""
    _validate_inputs(build, firmware, boundary)
    return {
        "schema_version": 1,
        "firmware_build_sha256": build["firmware_sha256"],
        "build_id": build["build_id"],
        "source_commit": build["source_commit"],
        "source_tree_sha256": build.get("source_tree_sha256"),
        "platformio_env": build.get("platformio_env"),
        "radio": {
            "wifi_initialized": firmware["wifi_initialized"],
            "bluetooth_initialized": firmware["bluetooth_initialized"],
            "basis": firmware["radio_basis"],
        },
        "sleep": {"calls_during_inference": firmware["sleep_calls_during_inference"]},
        "loop_pacing_ms": firmware["loop_pacing_ms"],
        "regulator_mode": firmware["regulator_mode"],
        "power_boundary": boundary,
    }


def _validate_inputs(
    build: dict[str, Any], firmware: dict[str, Any], boundary: dict[str, Any]
) -> None:
    _validate_required_fields(build, firmware, boundary)
    for name in ("build_id", "source_commit"):
        if firmware[name] != build[name]:
            msg = f"flashed firmware {name} differs from current build"
            raise SessionContractError(msg)
    if not isinstance(firmware["loop_pacing_ms"], (int, float)) or firmware["loop_pacing_ms"] < 0:
        msg = "invalid firmware loop_pacing_ms"
        raise SessionContractError(msg)
    if not isinstance(firmware["sleep_calls_during_inference"], int):
        msg = "invalid firmware sleep call count"
        raise SessionContractError(msg)


def _validate_required_fields(
    build: dict[str, Any], firmware: dict[str, Any], boundary: dict[str, Any]
) -> None:
    required_build = ("build_id", "source_commit", "firmware_sha256")
    required_firmware = (
        "build_id",
        "source_commit",
        "wifi_initialized",
        "bluetooth_initialized",
        "radio_basis",
        "sleep_calls_during_inference",
        "loop_pacing_ms",
        "regulator_mode",
    )
    required_boundary = ("rail", "components_inside", "source")
    for name in required_build:
        if not build.get(name):
            msg = f"build missing {name}"
            raise SessionContractError(msg)
    for name in required_firmware:
        if name not in firmware:
            msg = f"firmware META missing {name}"
            raise SessionContractError(msg)
    for name in required_boundary:
        if not boundary.get(name):
            msg = f"rig boundary missing {name}"
            raise SessionContractError(msg)
