# SPDX-License-Identifier: Apache-2.0
"""Prepare CIFAR-10 test set for signal-bench Phase 5 benchmarking.

Sources CIFAR-10's official test split and generates a deterministic 100-sample
MCU subset via stratified sampling (seed=42). Maintainers can explicitly publish
the full test set to Hugging Face with ``--publish``, but normal reproduction
only regenerates the local subset.

Fetch path: direct download from https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz
(canonical source). torchvision was the prompt's first-choice path but is
absent from the local environment; direct download avoids adding a heavy
ML-framework dependency for what is essentially a one-time data fetch.

Processing: passthrough. CIFAR-10 test images are stored as-is at 32x32x3
uint8 (RGB). No normalization, no cropping, no augmentation — the reference
MLPerf Tiny ResNet-8 model applies its own normalization at inference time.

Idempotency: the subset .npz is byte-deterministic against seed=42.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import pickle
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

import numpy as np

# Make `scripts.datasets.*` importable when this file is invoked directly
# as `uv run python scripts/datasets/prepare_ic.py` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.datasets._subset_selection import SUBSET_SIZE, select_subset

CIFAR10_URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"
CIFAR10_SHA256 = "6d958be074577803d12ecdefd02955f39262c83c16fe9348329d7fe0b5c001ce"
CIFAR10_TEST_MEMBER = "cifar-10-batches-py/test_batch"
DOWNLOAD_TIMEOUT_S = 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_WORKERS = 4
DOWNLOAD_RETRIES = 8
DOWNLOAD_CACHE_DIR = Path.home() / ".cache" / "signal-bench" / "cifar-10-python"

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSET_PATH = REPO_ROOT / "data" / "mcu_subsets" / "ic" / "subset_v1.npz"
DATASET_CARD_PATH = Path(__file__).parent / "dataset_cards" / "ic.md"
HF_REPO_ID = "narteybrown/signal-bench-ic-v1"

# CIFAR-10 class names in label order (0..9). Used only for logging clarity;
# the published dataset stores integer labels, not strings.
CIFAR10_LABEL_NAMES = (
    "airplane",
    "automobile",
    "bird",
    "cat",
    "deer",
    "dog",
    "frog",
    "horse",
    "ship",
    "truck",
)


def fetch_cifar10_test() -> tuple[np.ndarray, np.ndarray]:
    """Download CIFAR-10 and return the test split as (images, labels).

    Returns
    -------
    images : np.ndarray, shape (10000, 32, 32, 3), dtype uint8 (RGB)
    labels : np.ndarray, shape (10000,), dtype int64

    """
    archive_bytes = download_cifar10_archive()
    _verify_cifar10_archive(archive_bytes)

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        member = tar.getmember(CIFAR10_TEST_MEMBER)
        extracted = tar.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"missing CIFAR-10 member: {CIFAR10_TEST_MEMBER}")
        # CIFAR-10's pickle is Python-2-era; force bytes-keyed unpickling so
        # the `batch[b"data"]` / `batch[b"labels"]` accesses below work. The
        # archive SHA-256 is pinned before this point.
        # Security rationale: the CIFAR archive SHA-256 is pinned before this pickle load.
        batch = pickle.loads(  # nosec B301
            extracted.read(),
            encoding="bytes",
        )

    # CIFAR-10 stores images as flat (3072,) rows: 1024 R + 1024 G + 1024 B.
    raw = np.asarray(batch[b"data"], dtype=np.uint8)
    images = raw.reshape(-1, 3, 32, 32).transpose(0, 2, 3, 1)  # (N, H, W, C)
    labels = np.asarray(batch[b"labels"], dtype=np.int64)
    return images, labels


def _read_url(request: urllib.request.Request) -> bytes:
    """Read one request with the script's bounded socket timeout."""
    _require_https(request.full_url)
    # Security rationale: fixed HTTPS CIFAR URL; the archive SHA-256 is verified by the caller.
    response_ctx = urllib.request.urlopen(  # nosec B310
        request,
        timeout=DOWNLOAD_TIMEOUT_S,
    )
    with response_ctx as resp:
        return resp.read()


def _read_url_with_retries(
    request_factory: Callable[[], urllib.request.Request],
    label: str,
) -> bytes:
    """Read one URL request, retrying transient upstream stalls."""
    last_exc: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            return _read_url(request_factory())
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            last_exc = exc
            print(
                f"[prepare_ic] retry {attempt}/{DOWNLOAD_RETRIES} after timeout: {label}",
                file=sys.stderr,
            )
            time.sleep(min(attempt, 5))
    msg = f"CIFAR-10 download failed after {DOWNLOAD_RETRIES} attempts: {label}"
    raise RuntimeError(msg) from last_exc


def _content_length_from_range_header(value: str | None) -> int | None:
    """Parse ``Content-Range: bytes start-end/total``."""
    if not value or "/" not in value:
        return None
    try:
        return int(value.rsplit("/", maxsplit=1)[1])
    except ValueError:
        return None


def download_cifar10_archive() -> bytes:
    """Download CIFAR-10 from the official URL, using ranges when available."""
    print(f"[prepare_ic] fetching {CIFAR10_URL}", file=sys.stderr)
    first_byte, total, supports_ranges = _probe_cifar10_ranges()
    if not supports_ranges or total is None:
        print("[prepare_ic] server did not honor ranges; using serial download", file=sys.stderr)
        return _read_url_with_retries(
            lambda: urllib.request.Request(CIFAR10_URL),
            "full archive",
        )

    ranges = _build_ranges(total)
    cache_dir = DOWNLOAD_CACHE_DIR / str(total)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_first_range(cache_dir, ranges[0], first_byte)
    _download_missing_ranges(cache_dir, ranges, total)
    archive_bytes = b"".join(_range_part_path(cache_dir, item).read_bytes() for item in ranges)
    if len(archive_bytes) != total:
        msg = f"CIFAR-10 download length mismatch: {len(archive_bytes)} != {total}"
        raise RuntimeError(msg)
    return archive_bytes


def _verify_cifar10_archive(archive_bytes: bytes) -> None:
    """Validate the official CIFAR-10 archive before reading its pickle payload."""
    actual = hashlib.sha256(archive_bytes).hexdigest()
    if actual != CIFAR10_SHA256:
        msg = f"CIFAR-10 archive SHA-256 mismatch: {actual} != {CIFAR10_SHA256}"
        raise RuntimeError(msg)


def _require_https(url: str) -> None:
    """Reject non-HTTPS download URLs before opening them."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refusing non-HTTPS URL: {url}")


def _probe_cifar10_ranges() -> tuple[bytes, int | None, bool]:
    """Return first byte, content length, and whether the source supports ranges."""
    first_byte = b""
    total: int | None = None
    supports_ranges = False
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            probe = urllib.request.Request(CIFAR10_URL, headers={"Range": "bytes=0-0"})
            _require_https(probe.full_url)
            # Security rationale: fixed HTTPS CIFAR URL used only to probe range support.
            response_ctx = urllib.request.urlopen(  # nosec B310
                probe,
                timeout=DOWNLOAD_TIMEOUT_S,
            )
            with response_ctx as resp:
                first_byte = resp.read()
                total = _content_length_from_range_header(resp.headers.get("Content-Range"))
                supports_ranges = resp.status == 206 and total is not None
            break
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            print(
                f"[prepare_ic] retry {attempt}/{DOWNLOAD_RETRIES} after probe timeout",
                file=sys.stderr,
            )
            if attempt == DOWNLOAD_RETRIES:
                msg = "CIFAR-10 range probe failed"
                raise RuntimeError(msg) from exc
            time.sleep(min(attempt, 5))
    return first_byte, total, supports_ranges


def _build_ranges(total: int) -> list[tuple[int, int]]:
    """Split ``total`` bytes into byte ranges."""
    ranges: list[tuple[int, int]] = []
    for start in range(0, total, DOWNLOAD_CHUNK_BYTES):
        end = min(start + DOWNLOAD_CHUNK_BYTES - 1, total - 1)
        ranges.append((start, end))
    return ranges


def _cache_first_range(cache_dir: Path, first_range: tuple[int, int], first_byte: bytes) -> None:
    """Cache the first range, reusing the first byte from the probe."""
    first_part = _range_part_path(cache_dir, first_range)
    if not _cached_range_valid(first_part, first_range):
        first_part.write_bytes(
            first_byte
            + _read_url_with_retries(
                lambda: urllib.request.Request(
                    CIFAR10_URL,
                    headers={"Range": f"bytes=1-{first_range[1]}"},
                ),
                f"bytes=1-{first_range[1]}",
            )
        )


def _download_missing_ranges(
    cache_dir: Path,
    ranges: list[tuple[int, int]],
    total: int,
) -> None:
    """Download all missing byte ranges into ``cache_dir``."""
    cached_before = sum(
        1 for item in ranges if _cached_range_valid(_range_part_path(cache_dir, item), item)
    )
    completed = 0
    print(
        f"[prepare_ic] downloading {total / 1024 / 1024:.0f} MiB in "
        f"{len(ranges)} ranges with {DOWNLOAD_WORKERS} workers "
        f"({cached_before} cached)",
        file=sys.stderr,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        future_map = {
            pool.submit(_fetch_and_cache_range, cache_dir, item[1]): item[0]
            for item in enumerate(ranges)
        }
        for future in concurrent.futures.as_completed(future_map):
            future.result()
            completed += 1
            if completed % 8 == 0 or completed == len(ranges):
                downloaded = sum(
                    _range_part_path(cache_dir, item).stat().st_size
                    for item in ranges
                    if _cached_range_valid(_range_part_path(cache_dir, item), item)
                )
                print(
                    f"[prepare_ic] downloaded {downloaded / 1024 / 1024:.0f} "
                    f"of {total / 1024 / 1024:.0f} MiB",
                    file=sys.stderr,
                )

    missing = [
        item for item in ranges if not _cached_range_valid(_range_part_path(cache_dir, item), item)
    ]
    if missing:
        msg = f"CIFAR-10 download ended with {len(missing)} missing ranges"
        raise RuntimeError(msg)


def _fetch_and_cache_range(cache_dir: Path, range_item: tuple[int, int]) -> int:
    """Fetch one byte range unless it is already cached."""
    start, end = range_item
    range_label = f"bytes={start}-{end}"
    part_path = _range_part_path(cache_dir, range_item)
    if _cached_range_valid(part_path, range_item):
        return part_path.stat().st_size
    chunk = _read_url_with_retries(
        lambda: urllib.request.Request(
            CIFAR10_URL,
            headers={"Range": range_label},
        ),
        range_label,
    )
    expected_size = end - start + 1
    if len(chunk) != expected_size:
        msg = (
            f"CIFAR-10 range length mismatch for {range_label}: " f"{len(chunk)} != {expected_size}"
        )
        raise RuntimeError(msg)
    tmp_path = part_path.with_suffix(".tmp")
    tmp_path.write_bytes(chunk)
    tmp_path.replace(part_path)
    return len(chunk)


def _range_part_path(cache_dir: Path, range_item: tuple[int, int]) -> Path:
    """Return the cache path for one byte range."""
    start, end = range_item
    return cache_dir / f"{start}-{end}.part"


def _cached_range_valid(path: Path, range_item: tuple[int, int]) -> bool:
    """Return true if ``path`` contains the complete byte range."""
    if not path.exists():
        return False
    start, end = range_item
    return path.stat().st_size == end - start + 1


def write_subset(inputs: np.ndarray, labels: np.ndarray, indices: list[int]) -> None:
    """Write the MCU subset to the repo as a compressed .npz file."""
    SUBSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        SUBSET_PATH,
        inputs=inputs,
        labels=labels,
        indices=np.asarray(indices, dtype=np.int64),
    )
    print(
        f"[prepare_ic] subset written: {SUBSET_PATH} " f"({SUBSET_PATH.stat().st_size:,} bytes)",
        file=sys.stderr,
    )


def publish_to_hub(images: np.ndarray, labels: np.ndarray) -> None:
    """Push the full test set to HuggingFace and upload the Dataset Card."""
    from datasets import Dataset
    from huggingface_hub import HfApi

    hf_dataset = Dataset.from_dict(
        {
            "img": [images[i] for i in range(images.shape[0])],
            "label": labels.tolist(),
        }
    )
    print(f"[prepare_ic] pushing {len(hf_dataset)} rows to {HF_REPO_ID}", file=sys.stderr)
    hf_dataset.push_to_hub(HF_REPO_ID, private=True)

    api = HfApi()
    api.upload_file(
        path_or_fileobj=str(DATASET_CARD_PATH),
        path_in_repo="README.md",
        repo_id=HF_REPO_ID,
        repo_type="dataset",
    )
    print(
        f"[prepare_ic] published: https://huggingface.co/datasets/{HF_REPO_ID}",
        file=sys.stderr,
    )


def main() -> None:
    """Fetch CIFAR-10, write the MCU subset, and optionally publish to Hugging Face."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Maintainer-only: publish the full test set to Hugging Face.",
    )
    args = parser.parse_args()

    images, labels = fetch_cifar10_test()
    assert images.shape == (10000, 32, 32, 3), f"unexpected images shape: {images.shape}"
    assert labels.shape == (10000,), f"unexpected labels shape: {labels.shape}"

    sub_inputs, sub_labels, indices = select_subset(images, labels)
    assert sub_inputs.shape == (SUBSET_SIZE, 32, 32, 3)
    assert sub_labels.shape == (SUBSET_SIZE,)

    write_subset(sub_inputs, sub_labels, indices)
    if args.publish:
        publish_to_hub(images, labels)
    else:
        print(
            "[prepare_ic] skipped Hugging Face publish; pass --publish to upload",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
