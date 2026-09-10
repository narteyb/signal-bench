# SPDX-License-Identifier: Apache-2.0
"""Stage DCASE 2020 Task 2 ToyADMOS ToyCar audio data for signal-bench AD benchmarks.

Downloads the ToyCar portion of the DCASE 2020 Task 2 development dataset from
Zenodo record 3678171, verifies integrity via MD5 (Zenodo's published checksum
format), and stages at the target path for consumption by
``scripts/datasets/prepare_ad.py``.

Run once per environment. Idempotent: re-running with existing staging produces
a no-op confirmation.

The staged audio data lives under ``~/data/`` by default, **outside** the
signal-bench repo. DCASE 2020 Task 2 is licensed CC BY-NC-SA 4.0; keep the
downloaded audio outside this Apache-2.0 repository and do not commit it.

Usage:

    uv run python scripts/datasets/stage_dcase.py
    uv run python scripts/datasets/stage_dcase.py --stage-dir /custom/path
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ZENODO_RECORD_ID = "3678171"
ZENODO_API_URL = f"https://zenodo.org/api/records/{ZENODO_RECORD_ID}"
DEFAULT_STAGE_DIR = Path.home() / "data" / "dcase-2020-task2"
DEFAULT_MACHINE_TYPE = "ToyCar"

_KIB = 1024
_PROGRESS_REPORT_INTERVAL_S = 5
_DCASE_FILENAME_MIN_PARTS = 3


def fetch_record_metadata() -> dict:
    """Fetch Zenodo record metadata as a parsed JSON object."""
    _require_https(ZENODO_API_URL)
    # Security rationale: fixed HTTPS Zenodo metadata source; file checksums are used below.
    response_ctx = urllib.request.urlopen(  # nosec B310
        ZENODO_API_URL,
        timeout=30,
    )
    with response_ctx as response:
        return json.load(response)


def find_target_file(metadata: dict, machine_type: str) -> dict:
    """Find the Zenodo file entry matching the target machine type.

    Returns the file dict with at minimum ``key``, ``size``, ``checksum``,
    and ``links.self`` populated.
    """
    target_name = f"dev_data_{machine_type}.zip"
    for entry in metadata.get("files", []):
        if entry.get("key") == target_name:
            return entry
    available = [e.get("key") for e in metadata.get("files", [])]
    raise RuntimeError(
        f"file {target_name!r} not found in Zenodo record "
        f"{ZENODO_RECORD_ID}; available: {available}"
    )


def parse_checksum(raw: str) -> tuple[str, str]:
    """Split Zenodo's ``"md5:..."`` / ``"sha256:..."`` checksum string."""
    if ":" not in raw:
        raise RuntimeError(f"unexpected checksum format: {raw!r}")
    algo, value = raw.split(":", 1)
    return algo.lower(), value


def verify_checksum(file_path: Path, algo: str, expected: str) -> bool:
    """Compute the digest of ``file_path`` under ``algo`` and compare to expected."""
    hasher = hashlib.new(algo)
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest() == expected


def _format_bytes(n: float) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < _KIB:
            return f"{n:.1f} {unit}"
        n /= _KIB
    return f"{n:.1f} TB"


def download_with_progress(url: str, target_path: Path) -> None:
    """Stream ``url`` to ``target_path`` while printing a progress line."""
    _require_https(url)
    print(f"[stage_dcase] downloading {url}", file=sys.stderr)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    last_report = start

    # Security rationale: fixed HTTPS Zenodo file source; checksum verification follows download.
    response_ctx = urllib.request.urlopen(  # nosec B310
        url,
        timeout=60,
    )
    with response_ctx as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        with target_path.open("wb") as out:
            while True:
                chunk = response.read(1 << 20)  # 1 MB at a time
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= _PROGRESS_REPORT_INTERVAL_S or downloaded == total:
                    elapsed = now - start
                    rate = downloaded / elapsed if elapsed > 0 else 0
                    pct = (downloaded / total * 100) if total else 0
                    print(
                        f"  {_format_bytes(downloaded)} / "
                        f"{_format_bytes(total) if total else '?'} "
                        f"({pct:5.1f}%) @ {_format_bytes(int(rate))}/s",
                        file=sys.stderr,
                    )
                    last_report = now


def extract_zip_selective(zip_path: Path, target_dir: Path) -> None:
    """Extract the zip to ``target_dir``, surfacing the top-level layout produced."""
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        member_count = len(zf.namelist())
        print(
            f"[stage_dcase] extracting {member_count:,} members from "
            f"{zip_path.name} → {target_dir}",
            file=sys.stderr,
        )
        for info in zf.infolist():
            destination = (target_root / info.filename).resolve()
            if not destination.is_relative_to(target_root):
                raise RuntimeError(f"refusing unsafe zip member path: {info.filename}")
            zf.extract(info, target_root)


def _require_https(url: str) -> None:
    """Reject non-HTTPS Zenodo URLs before opening them."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refusing non-HTTPS URL: {url}")


def summarize_staging(stage_dir: Path, machine_type: str) -> None:
    """Print a verification summary of the staged ToyCar tree."""
    machine_dir = stage_dir / machine_type
    train_dir = machine_dir / "train"
    test_dir = machine_dir / "test"

    train_files = sorted(train_dir.glob("*.wav")) if train_dir.exists() else []
    test_files = sorted(test_dir.glob("*.wav")) if test_dir.exists() else []
    test_normal = [f for f in test_files if f.name.startswith("normal_")]
    test_anomaly = [f for f in test_files if f.name.startswith("anomaly_")]

    machine_ids: set[str] = set()
    for f in test_files + train_files:
        # DCASE filenames look like normal_id_01_00000000.wav
        parts = f.stem.split("_")
        if len(parts) >= _DCASE_FILENAME_MIN_PARTS and parts[1] == "id":
            machine_ids.add(parts[2])

    print(f"\n=== Staging summary: {machine_dir} ===", file=sys.stderr)
    print(f"  train/   {len(train_files):>6} files (all normal)", file=sys.stderr)
    print(
        f"  test/    {len(test_files):>6} files "
        f"({len(test_normal)} normal + {len(test_anomaly)} anomaly)",
        file=sys.stderr,
    )
    print(f"  machine IDs found: {sorted(machine_ids)}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Stage DCASE ToyCar from Zenodo: download, verify, extract, summarize."""
    parser = argparse.ArgumentParser(description="Stage DCASE 2020 Task 2 ToyCar audio data.")
    parser.add_argument("--stage-dir", type=Path, default=DEFAULT_STAGE_DIR)
    parser.add_argument("--machine-type", default=DEFAULT_MACHINE_TYPE)
    args = parser.parse_args(argv)

    if args.machine_type != DEFAULT_MACHINE_TYPE:
        print(
            f"WARNING: Phase 5 scope is {DEFAULT_MACHINE_TYPE} only. "
            f"Requested: {args.machine_type}",
            file=sys.stderr,
        )

    stage_dir: Path = args.stage_dir.expanduser().resolve()
    stage_dir.mkdir(parents=True, exist_ok=True)
    machine_dir = stage_dir / args.machine_type
    test_dir = machine_dir / "test"
    if test_dir.exists() and any(test_dir.glob("*.wav")):
        print(f"[stage_dcase] already extracted: {machine_dir}", file=sys.stderr)
        summarize_staging(stage_dir, args.machine_type)
        return 0

    downloads_dir = stage_dir / "_downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    print(f"[stage_dcase] fetching Zenodo record {ZENODO_RECORD_ID} metadata", file=sys.stderr)
    metadata = fetch_record_metadata()
    target_file = find_target_file(metadata, args.machine_type)

    expected_algo, expected_digest = parse_checksum(target_file["checksum"])
    download_url = target_file["links"]["self"]
    zip_path = downloads_dir / target_file["key"]

    print(
        f"[stage_dcase] target: {target_file['key']} "
        f"({_format_bytes(target_file['size'])}, {expected_algo}={expected_digest})",
        file=sys.stderr,
    )

    if zip_path.exists() and verify_checksum(zip_path, expected_algo, expected_digest):
        print(f"[stage_dcase] cache hit: {zip_path}", file=sys.stderr)
    else:
        if zip_path.exists():
            print(
                "[stage_dcase] cache present but checksum mismatch; re-downloading",
                file=sys.stderr,
            )
        download_with_progress(download_url, zip_path)
        if not verify_checksum(zip_path, expected_algo, expected_digest):
            print(
                f"ERROR: {expected_algo} mismatch on {zip_path}; download corrupted",
                file=sys.stderr,
            )
            return 1
        print("[stage_dcase] checksum verified", file=sys.stderr)

    if test_dir.exists() and any(test_dir.glob("*.wav")):
        print(f"[stage_dcase] already extracted: {machine_dir}", file=sys.stderr)
    else:
        extract_zip_selective(zip_path, stage_dir)

    summarize_staging(stage_dir, args.machine_type)
    return 0


if __name__ == "__main__":
    sys.exit(main())
