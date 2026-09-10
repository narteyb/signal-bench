# MLPerf Tiny v1.2 — Keyword Spotting Reference Model

Canonical TFLite artifact for the MLPerf Tiny Keyword Spotting task,
sourced from `mlcommons/tiny`. Full machine-readable metadata lives in
[`provenance.yaml`](./provenance.yaml): pinned commit, source URL,
SHA-256, byte count, retrieval timestamp, model card (DS-CNN
architecture, dataset, accuracy target/metric, quantization
scales/zero-points, input/output shapes), license.

## Companion dataset

The test set used to evaluate this model in signal-bench's Phase 5
benchmarks is published as a HuggingFace Dataset:

**[narteybrown/signal-bench-kws-v1](https://huggingface.co/datasets/narteybrown/signal-bench-kws-v1)**

A deterministic 100-sample MCU subset (seed=42, stratified across all
12 classes) is committed at `data/mcu_subsets/kws/subset_v1.npz`.

## Modification policy

Files in this directory are canonical artifacts from upstream and must
not be modified. Per-target conversions land in `models/{onnx,tflm}/`.
