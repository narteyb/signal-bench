# MLPerf Tiny v1.2 — Image Classification Reference Model

Canonical TFLite artifact for the MLPerf Tiny Image Classification task,
sourced from `mlcommons/tiny`. Full machine-readable metadata lives in
[`provenance.yaml`](./provenance.yaml): pinned commit, source URL,
SHA-256, byte count, retrieval timestamp, model card (architecture,
dataset, accuracy target/metric, quantization scales/zero-points,
input/output shapes), license.

## Companion dataset

The IC workload uses CIFAR-10's official test split. CIFAR-10's source requests
citation but does not provide an explicit redistribution license suitable for
carrying the pixel subset in this Apache-2.0 repository, so the MCU subset is
regenerated from upstream instead of redistributed here.

Regenerate the deterministic 100-sample MCU subset from the official University
of Toronto source with:

```bash
uv run python scripts/datasets/prepare_ic.py
```

See `docs/third-party-data.md` for the license position and citation.

## Modification policy

Files in this directory are canonical artifacts from upstream and must
not be modified. Per-target conversions land in `models/{onnx,tflm}/`.
