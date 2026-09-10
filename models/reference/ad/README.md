# MLPerf Tiny v1.2 — Anomaly Detection Reference Model

Canonical TFLite artifact for the MLPerf Tiny Anomaly Detection task,
sourced from `mlcommons/tiny`. Full machine-readable metadata lives in
[`provenance.yaml`](./provenance.yaml): pinned commit, source URL,
SHA-256, byte count, retrieval timestamp, model card (Dense AutoEncoder
architecture, ToyADMOS ToyCar dataset, AUC target/metric, quantization
scales/zero-points, input/output shapes), license.

## Companion dataset

The AD workload uses ToyCar audio from the DCASE 2020 Task 2 development
dataset, converted to MLPerf Tiny-compatible log-mel feature vectors. The
upstream dataset is CC BY-NC-SA 4.0, so the derived MCU subset is regenerated
from upstream instead of being redistributed in this Apache-2.0 repository.

Regenerate the deterministic 100-vector MCU subset from Zenodo with:

```bash
uv run python scripts/datasets/stage_dcase.py
uv run python scripts/datasets/prepare_ad.py
```

See `docs/third-party-data.md` for the license position and citations.

## Modification policy

Files in this directory are canonical artifacts from upstream and must
not be modified. Per-target conversions land in `models/{onnx,tflm}/`.
