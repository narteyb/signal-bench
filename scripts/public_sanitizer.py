# SPDX-License-Identifier: Apache-2.0
"""Sanitize public artifacts that may carry local lab identity."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

DEVICE_PATH_RE = re.compile(
    r"/dev/(?:cu\.[^\s\"'`,;).]+|tty\.[^\s\"'`,;).]+|ttyUSB[^\s\"'`,;).]+|"
    r"ttyACM[^\s\"'`,;).]+|serial/[^\s\"'`,;).]+)",
)
BARE_MACOS_DEVICE_RE = re.compile(r"\b(?:cu|tty)\.(?:usbmodem|usbserial)[^\s\"'`,;).]*")
LOCAL_PATH_RE = re.compile("/Us" r"ers/[^\s\"']+")
GOOGLE_DRIVE_RE = re.compile("Google" + r"Drive-[^/\s\"']+")
NON_PUBLIC_EMAIL_RE = re.compile(
    r"(?i)\b[\w.+-]+@(?:"
    "ya"
    r"hoo|gmail|googlemail|icloud|me|mac|hotmail|outlook|live)\.[a-z]{2,}\b",
)
LAB_HOSTNAME_RE = re.compile(
    r"(?i)\b(?:(?:pi\d*|rpi|raspberrypi)-edge-\d{2,}|jetson-orin-\d{2,})\b",
)
METER_LABEL_RE = re.compile(r"\bFNB58-\d{5,}\b")
LAB_SERIAL_LABEL_RE = re.compile(
    r"(?i)(\b(?:serial|ser|serial_number|hardware_id|hwid)\s*[:= ]\s*)"
    r"(?=[A-Z0-9._-]*\d)([A-Z0-9][A-Z0-9._-]{7,})",
)
SER_FIELD_RE = re.compile(r"(?i)(\bSER=)(?=[A-Z0-9._-]*\d)([A-Z0-9][A-Z0-9._-]{7,})")
CONTEXTUAL_HARDWARE_SERIAL_RE = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{12,}\b")
TIMESTAMP_TOKEN_RE = re.compile(r"^\d{8}T\d{6}Z$")
VARIANT_PIPELINE_PATH_MARKER = "/" + "signal-bench-" + "variants" + "/"

DEVICE_IDENTITY_KEYS = {
    "device",
    "debug_port",
    "hardware_id",
    "hwid",
    "monitor_port",
    "port",
    "serial",
    "serial_number",
    "serial_path",
    "serial_port",
    "stlink_enumeration_state",
    "upload_port",
    "usb_device",
    "usb_path",
}
DEVICE_IDENTITY_KEY_FRAGMENTS = (
    "serial",
    "hardware_id",
    "hwid",
    "stlink",
    "usb_device",
    "usb_path",
)

PRIVATE_PATTERNS = (
    LOCAL_PATH_RE,
    GOOGLE_DRIVE_RE,
    NON_PUBLIC_EMAIL_RE,
    re.compile(r"192\.168\."),
    re.compile(r"10\.1\.10\."),
    LAB_HOSTNAME_RE,
    METER_LABEL_RE,
    DEVICE_PATH_RE,
    BARE_MACOS_DEVICE_RE,
    LAB_SERIAL_LABEL_RE,
    SER_FIELD_RE,
)
SCAN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("local-path", LOCAL_PATH_RE),
    ("cloud-drive-path", GOOGLE_DRIVE_RE),
    ("non-public-email", NON_PUBLIC_EMAIL_RE),
    ("private-ipv4", re.compile(r"\b(?:192\.168\.|10\.1\.10\.)\d{1,3}(?:\.\d{1,3}){0,2}\b")),
    ("lab-hostname", LAB_HOSTNAME_RE),
    ("meter-label", METER_LABEL_RE),
    ("device-path", DEVICE_PATH_RE),
    ("bare-macos-device", BARE_MACOS_DEVICE_RE),
    ("labeled-hardware-serial", LAB_SERIAL_LABEL_RE),
    ("ser-field", SER_FIELD_RE),
)


def sanitize_json(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {item_key: sanitize_json(item, key=item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item, key=key) for item in value]
    if isinstance(value, str):
        return sanitize_string(value, key=key)
    if key and _is_identity_key(key) and value is not None:
        return "[hardware-identity-redacted]"
    return value


def sanitize_string(value: str, *, key: str | None = None) -> str:
    sanitized = LOCAL_PATH_RE.sub(_sanitize_path_match, value)
    sanitized = GOOGLE_DRIVE_RE.sub("cloud-drive-sanitized", sanitized)
    sanitized = NON_PUBLIC_EMAIL_RE.sub("[non-public-email-redacted]", sanitized)
    sanitized = LAB_HOSTNAME_RE.sub("[lab-hostname-redacted]", sanitized)
    sanitized = METER_LABEL_RE.sub("FNB58-[meter-label-redacted]", sanitized)
    sanitized = DEVICE_PATH_RE.sub("[device-path-redacted]", sanitized)
    sanitized = BARE_MACOS_DEVICE_RE.sub("[device-path-redacted]", sanitized)
    sanitized = SER_FIELD_RE.sub(r"\1[hardware-serial-redacted]", sanitized)
    sanitized = LAB_SERIAL_LABEL_RE.sub(r"\1[hardware-serial-redacted]", sanitized)
    sanitized = "\n".join(_sanitize_contextual_serials(line) for line in sanitized.split("\n"))
    if key and _is_serial_value_key(key) and sanitized == value:
        return "[hardware-serial-redacted]"
    return sanitized


def assert_clean_text(text: str) -> None:
    hits = [pattern.pattern for pattern in PRIVATE_PATTERNS if pattern.search(text)]
    if hits:
        raise RuntimeError(f"artifact still contains private patterns: {hits}")


def sanitize_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    if _looks_like_json(path):
        payload = json.loads(original)
        sanitized_payload = sanitize_json(payload)
        if sanitized_payload == payload:
            return False
        sanitized = json.dumps(sanitized_payload, indent=2, sort_keys=True) + "\n"
    else:
        sanitized = sanitize_string(original)
        if sanitized == original:
            return False
    path.write_text(sanitized, encoding="utf-8")
    return True


def file_needs_sanitizing(path: Path) -> bool:
    original = _read_text(path)
    if original is None:
        return False
    if _looks_like_json(path):
        payload = json.loads(original)
        return sanitize_json(payload) != payload
    return sanitize_string(original) != original


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    text = _read_text(path)
    if text is None:
        return []
    hits: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SCAN_RULES:
            for match in pattern.finditer(line):
                hits.append((line_no, name, match.group(0)))
    return hits


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def _is_identity_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in DEVICE_IDENTITY_KEYS or any(
        fragment in normalized for fragment in DEVICE_IDENTITY_KEY_FRAGMENTS
    )


def _is_serial_value_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in {"serial", "serial_number", "hardware_id", "hwid"} or normalized.endswith(
        "_serial",
    )


def _sanitize_path_match(match: re.Match[str]) -> str:
    path = match.group(0)
    if VARIANT_PIPELINE_PATH_MARKER in path:
        return "variant-pipeline://model-prep/" + path.split(VARIANT_PIPELINE_PATH_MARKER, 1)[1]
    if "/signal-bench/build/" in path:
        return "sanitized://signal-bench-build/" + path.split("/signal-bench/build/", 1)[1]
    if "/edge-bringup/" in path:
        return "sanitized://source-artifact/" + path.rsplit("/", 1)[-1]
    return "sanitized://local-path"


def _sanitize_contextual_serials(line: str) -> str:
    if not re.search(r"(?i)serial|st-?link|hwid|hardware id", line):
        return line
    return CONTEXTUAL_HARDWARE_SERIAL_RE.sub(_sanitize_contextual_serial_match, line)


def _sanitize_contextual_serial_match(match: re.Match[str]) -> str:
    token = match.group(0)
    if TIMESTAMP_TOKEN_RE.match(token):
        return token
    return "[hardware-serial-redacted]"


def _looks_like_json(path: Path) -> bool:
    return path.suffix.lower() == ".json"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--write", action="store_true", help="Rewrite files in place.")
    parser.add_argument(
        "--tracked-tree",
        action="store_true",
        help="Scan every tracked text file for lab-fingerprint patterns.",
    )
    args = parser.parse_args()

    if args.tracked_tree:
        all_hits: list[str] = []
        for path in tracked_files():
            for line_no, name, value in scan_file(path):
                all_hits.append(f"{path}:{line_no}:{name}:{value}")
        if all_hits:
            print("\n".join(all_hits))
            return 1
        return 0

    if not args.paths:
        parser.error("paths are required unless --tracked-tree is used")

    changed: list[str] = []
    for path in args.paths:
        if args.write:
            if sanitize_file(path):
                changed.append(str(path))
        elif file_needs_sanitizing(path):
            changed.append(str(path))
    if changed:
        print("\n".join(changed))
        return 1 if not args.write else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
