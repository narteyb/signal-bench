# Reference Models

This directory pins the Post 1 MLPerf Tiny reference artifacts selected in
`docs/post-1-tasks.md`: keyword spotting, image classification, and anomaly
detection. MLCommons lists these benchmark definitions as available in MLPerf
Tiny v1.3, but the public `mlcommons/tiny` repository currently exposes release
tags only through `v1.1`; the files here are therefore pinned to the exact
public commit recorded in `manifest.yaml`.

Layout:

- `kws/` stores the DS-CNN keyword-spotting TFLite model.
- `ic/` stores the small quantized ResNet image-classification TFLite model.
- `ad/` stores the quantized ToyADMOS anomaly-detection TFLite model.

Every model has a per-task `provenance.yaml` with source path, source URL,
retrieval timestamp, byte count, SHA-256 hash, and license. The root
`manifest.yaml` is the consolidated registry future loader code should consume.

Verify local bytes with:

```bash
uv run python - <<'PY'
import hashlib, pathlib, yaml
m = yaml.safe_load(open("models/reference/manifest.yaml"))
for task, info in m["tasks"].items():
    path = pathlib.Path("models/reference") / info["directory"] / info["canonical_file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == info["sha256"]
    print(f"{task}: OK")
PY
```

Reference artifacts are sourced from MLPerf Tiny under Apache-2.0. Future
Signal Reports may add tasks or variants; follow this manifest/provenance
pattern and do not replace these Post 1 bytes in place.
