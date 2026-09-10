# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
from types import ModuleType

SYNTH_MODEM_PATH = "/dev/cu." + "usbmodemTEST"
SYNTH_SERIAL_PATH = "/dev/cu." + "usbserial-TEST"
SYNTH_BARE_MODEM = "cu." + "usbmodemTEST"
SYNTH_HARDWARE_SERIAL = "STLINK" + "1234567890"
SYNTH_METER_LABEL = "FNB58-" + "123456"
SYNTH_HOSTNAME = "pi5-edge-" + "99"
SYNTH_VARIANT_PATH = "/Us" + "ers/example/signal-bench-" + "variants/v1/kws/model.tflite"


def _load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "public_sanitizer.py"
    spec = importlib.util.spec_from_file_location("public_sanitizer", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitizes_device_paths_and_serial_fields() -> None:
    sanitizer = _load_module()
    payload = {
        "run_id": "019f3d83-32b9-74d0-b483-b8f81725204e",
        "serial_port": SYNTH_MODEM_PATH,
        "device": SYNTH_SERIAL_PATH,
        "serial_number": SYNTH_HARDWARE_SERIAL,
        "stlink_enumeration_state": (
            f"attached_enumerated ({SYNTH_MODEM_PATH}; "
            f"STM32 STLink serial {SYNTH_HARDWARE_SERIAL})"
        ),
    }

    sanitized = sanitizer.sanitize_json(payload)

    assert sanitized["run_id"] == payload["run_id"]
    assert sanitized["serial_port"] == "[device-path-redacted]"
    assert sanitized["device"] == "[device-path-redacted]"
    assert sanitized["serial_number"] == "[hardware-serial-redacted]"
    assert SYNTH_MODEM_PATH not in sanitized["stlink_enumeration_state"]
    assert SYNTH_HARDWARE_SERIAL not in sanitized["stlink_enumeration_state"]


def test_sanitizes_usbserial_in_free_text() -> None:
    sanitizer = _load_module()

    sanitized = sanitizer.sanitize_string(f"ESP32 appeared at {SYNTH_SERIAL_PATH}.")

    assert sanitized == "ESP32 appeared at [device-path-redacted]."


def test_sanitizes_bare_macos_device_name() -> None:
    sanitizer = _load_module()

    sanitized = sanitizer.sanitize_string(f"No device found on {SYNTH_BARE_MODEM}")

    assert sanitized == "No device found on [device-path-redacted]"


def test_sanitizes_contextual_markdown_serial() -> None:
    sanitizer = _load_module()

    sanitized = sanitizer.sanitize_string(
        f"`{SYNTH_HARDWARE_SERIAL}`, with serial path `{SYNTH_MODEM_PATH}`.",
    )

    assert SYNTH_HARDWARE_SERIAL not in sanitized
    assert "[hardware-serial-redacted]" in sanitized
    assert "[device-path-redacted]" in sanitized


def test_sanitizes_meter_labels_and_lab_hostnames() -> None:
    sanitizer = _load_module()

    sanitized = sanitizer.sanitize_string(
        f"Validation used {SYNTH_METER_LABEL} on host {SYNTH_HOSTNAME}.",
    )

    assert SYNTH_METER_LABEL not in sanitized
    assert SYNTH_HOSTNAME not in sanitized
    assert "FNB58-[meter-label-redacted]" in sanitized
    assert "[lab-hostname-redacted]" in sanitized


def test_sanitizes_private_variant_pipeline_paths() -> None:
    sanitizer = _load_module()

    sanitized = sanitizer.sanitize_string(f"model artifact: {SYNTH_VARIANT_PATH}")

    assert "signal-bench-" + "variants" not in sanitized
    assert "variant-pipeline://model-prep/v1/kws/model.tflite" in sanitized


def test_does_not_touch_run_ids_or_hashes() -> None:
    sanitizer = _load_module()
    payload = {
        "run_id": "019e5da7-ef3e-7830-94a8-2ef6f6845b8e",
        "model_hash": "c4ef6f080b274584c74a0a7ef5d1a4bb5d14f4a0686a1cc40fdf0e3b52f6e03e",
        "source_sha256": "0ac79b8acc6bcee9facc485a8a523220e26c74b4",
    }

    assert sanitizer.sanitize_json(payload) == payload


def test_does_not_touch_artifact_timestamps_in_stlink_context() -> None:
    sanitizer = _load_module()

    text = (
        "ST-LINK disconnected artifact "
        "`data/meter_integrity/phase-d-f401re-usb-disconnected-20260705T015945Z/summary.json`"
    )

    assert sanitizer.sanitize_string(text) == text
