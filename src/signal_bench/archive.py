# SPDX-License-Identifier: Apache-2.0
"""Per-cell archive helpers for Phase 5 evidence capture."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

DEFAULT_ARCHIVE_ROOT = Path("data/archives")


def create_archive_dir(run_id: str, *, root: Path = DEFAULT_ARCHIVE_ROOT) -> Path:
    """Create and return the archive directory for one run."""
    path = root / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_toolchain_manifest(
    run_id: str,
    manifest: dict[str, Any],
    *,
    root: Path = DEFAULT_ARCHIVE_ROOT,
) -> Path:
    """Write the toolchain manifest JSON for one run."""
    path = create_archive_dir(run_id, root=root) / "toolchain-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_orchestrator_log(
    run_id: str,
    log_text: str,
    *,
    root: Path = DEFAULT_ARCHIVE_ROOT,
) -> Path:
    """Write an orchestrator log filtered to lines mentioning the run id."""
    path = create_archive_dir(run_id, root=root) / "orchestrator.log"
    filtered = [line for line in log_text.splitlines() if run_id in line]
    path.write_text("\n".join(filtered) + ("\n" if filtered else ""), encoding="utf-8")
    return path


def copy_lineage_file(
    run_id: str,
    source_path: Path,
    *,
    root: Path = DEFAULT_ARCHIVE_ROOT,
) -> Path:
    """Copy an N3 model-lineage payload into the run archive."""
    archive = create_archive_dir(run_id, root=root)
    destination = archive / "model-lineage.json"
    shutil.copyfile(source_path, destination)
    return destination
