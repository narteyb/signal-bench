# SPDX-License-Identifier: Apache-2.0
"""Closed boundary records and v21 acceptance checks for the launch runner."""

from __future__ import annotations

import math
from typing import Any, NoReturn

REQUIRED_INSTRUMENTS = ("ina219", "fnb58", "bme280")
COVERAGE_MIN = 0.85
MIN_DURATION_S = 30.0
MIN_SUCCESSFUL_ITERATIONS = 20
MIN_AMBIENT_SAMPLES = 2


def _reject(message: str) -> NoReturn:
    raise ValueError(message)


def validate_boundary(value: object, target: str) -> dict[str, Any]:
    """Reject missing fields, ambiguous prose and unmetered supply bypasses."""
    fields = {
        "board",
        "shunt_rail",
        "interface_inside_boundary",
        "usb_vbus",
        "input_pin",
        "jumpers",
    }
    if not isinstance(value, dict) or set(value) != fields:
        _reject(
            "boundary: exactly board, shunt_rail, interface_inside_boundary, "
            "usb_vbus, input_pin, jumpers required"
        )
    if value["board"] != target:
        _reject("boundary: board must match requested target")
    if value["shunt_rail"] != "5v_positive_high_side":
        _reject("boundary: shunt_rail must be 5v_positive_high_side")
    if type(value["interface_inside_boundary"]) is not bool:
        _reject("boundary: interface_inside_boundary must be a JSON boolean")
    if value["usb_vbus"] not in ("disconnected", "connected_metered", "connected_unmetered"):
        _reject(
            "boundary: usb_vbus must be disconnected, connected_metered, or connected_unmetered"
        )
    if value["usb_vbus"] == "connected_unmetered":
        _reject("boundary: connected_unmetered VBUS bypasses the approved shunt")
    if value["interface_inside_boundary"] is not True:
        _reject("boundary: campaign includes the board and its communication/debug interface")
    _validate_board_links(value, target)
    return value


def _validate_board_links(value: dict[str, Any], target: str) -> None:
    pins = {"f401re": ("e5v",), "nano33": ("vin", "vusb"), "esp32s3": ("5v", "v_plus")}
    if target not in pins or value["input_pin"] not in pins[target]:
        _reject("boundary: input_pin must name one supported physical input")
    jumpers = value["jumpers"]
    if not isinstance(jumpers, dict):
        _reject("boundary: jumpers must be an object")
    if target == "f401re":
        if jumpers != {"jp5": "e5v"} or value["usb_vbus"] != "connected_metered":
            _reject("boundary: F401RE requires jp5=e5v and metered ST-LINK VBUS")
    elif target == "nano33":
        if set(jumpers) != {"vusb_solder_bridge"} or jumpers["vusb_solder_bridge"] not in (
            "open",
            "closed",
        ):
            _reject("boundary: Nano requires vusb_solder_bridge=open or closed")
    elif jumpers:
        _reject("boundary: ESP32-S3 jumper record must be the explicit empty object")


def acceptance_reasons(  # noqa: PLR0913 - independent recorded gate inputs
    *,
    boundary: object,
    target: str,
    duration_s: float,
    successful_iterations: int,
    iteration_errors: int,
    ambient: dict[str, Any],
    coverage: dict[str, Any],
    tooling_error: str | None = None,
) -> list[str]:
    """Evaluate actual recorded data; no ambient band and no coverage grace."""
    reasons = []
    try:
        validate_boundary(boundary, target)
    except ValueError as exc:
        reasons.append(str(exc))
    if not math.isfinite(duration_s) or duration_s < MIN_DURATION_S:
        reasons.append(f"duration: {duration_s!r} s < {MIN_DURATION_S} s or nonfinite")
    if successful_iterations < MIN_SUCCESSFUL_ITERATIONS:
        reasons.append(
            f"iterations: {successful_iterations} successful < {MIN_SUCCESSFUL_ITERATIONS}"
        )
    if iteration_errors:
        reasons.append(f"tooling: {iteration_errors} iteration errors")
    if tooling_error:
        reasons.append(f"tooling: {tooling_error}")
    for metric in ("temperature_c", "humidity_pct"):
        series = ambient.get(metric, {})
        if series.get("sample_count", 0) < MIN_AMBIENT_SAMPLES or series.get("invalid_count", 0):
            reasons.append(f"ambient: {metric} requires at least two finite recorded samples")
    for instrument in REQUIRED_INSTRUMENTS:
        item = coverage.get(instrument, {})
        received, expected = item.get("received", 0), item.get("expected", 0)
        if expected <= 0 or received / expected < COVERAGE_MIN:
            reasons.append(
                f"coverage: {instrument} {received}/{expected} "
                f"below {COVERAGE_MIN:.2f} or denominator absent"
            )
    return reasons
