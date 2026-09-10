# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json

from signal_bench.archive import (
    copy_lineage_file,
    create_archive_dir,
    write_orchestrator_log,
    write_toolchain_manifest,
)


def test_archive_directory_and_artifacts(tmp_path) -> None:
    root = tmp_path / "archives"
    archive = create_archive_dir("run-1", root=root)
    assert archive == root / "run-1"
    assert archive.exists()

    manifest = write_toolchain_manifest("run-1", {"compiler": "gcc"}, root=root)
    assert json.loads(manifest.read_text(encoding="utf-8"))["compiler"] == "gcc"

    log = write_orchestrator_log("run-1", "run-1 kept\nrun-2 dropped\n", root=root)
    assert log.read_text(encoding="utf-8") == "run-1 kept\n"

    lineage = tmp_path / "lineage.json"
    lineage.write_text('{"ok": true}', encoding="utf-8")
    copied = copy_lineage_file("run-1", lineage, root=root)
    assert copied.read_text(encoding="utf-8") == '{"ok": true}'
