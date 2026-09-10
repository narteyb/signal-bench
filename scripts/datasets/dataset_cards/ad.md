---
license: cc-by-nc-sa-4.0
task_categories:
  - audio-classification
language:
  - en
size_categories:
  - 1K<n<10K
tags:
  - tinyml
  - mlperf-tiny
  - edge-ai
  - benchmarking
  - signal-bench
  - anomaly-detection
  - dcase
  - toyadmos
---

# Signal-Bench AD Test Set v1

## What this is

Log-mel-spectrogram features extracted from the DCASE 2020 Task 2 ToyADMOS ToyCar test partition, packaged for maintainer-only signal-bench experiments.

**This dataset contains processed features only, not raw audio.** The upstream DCASE 2020 Task 2 dataset is licensed CC BY-NC-SA 4.0. The public repository does not redistribute this dataset or its MCU subset because that license is not compatible with carrying derived feature data in an Apache-2.0 repository.

## Source attribution

Raw audio: DCASE 2020 Task 2 development dataset, ToyCar machine type.
- URL: https://zenodo.org/records/3678171
- Source paper: Koizumi et al., "ToyADMOS: A Dataset of Miniature-machine Operating Sounds for Anomalous Sound Detection," WASPAA 2019.
- License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International.

Feature extraction parameters match MLPerf Tiny v1.2's AD reference preprocessing:
- Pinned commit: `5dae3296bd899ed58a65311a8e6fd91d83f664ab`
- Upstream baseline: `benchmark/training/anomaly_detection/baseline.yaml` + `common.py::file_to_vector_array`

## Processing

Each 10-second 16 kHz audio clip is converted to a 2D feature matrix following the MLPerf Tiny AD reference pipeline:

1. `librosa.feature.melspectrogram(n_fft=1024, hop_length=512, n_mels=128, power=2.0)` → power-spectrum mel filterbank.
2. `20.0 / power * np.log10(mel + sys.float_info.epsilon)` → dB-scaled log (resolves to `10 * log10(...)` for `power=2.0`).
3. `[:, 50:250]` → central 200-frame slice (matches upstream's "take central part only" step, skipping the first ~1.6 s and last ~2 s of the 10 s clip to avoid edge effects).
4. 5-frame context concatenation: each output row stitches 5 consecutive log-mel columns into a 640-dim vector (128 mels × 5 frames).
5. Output per clip: `(196, 640)` float32 — 196 overlapping context-concatenated vectors.

Each row in the dataset corresponds to one input clip; the `features` column is a 2D array of shape (196, 640) per clip. Anomaly detection at inference time evaluates each 640-dim vector independently against the reference autoencoder and aggregates per-clip anomaly scores.

## Subset structure

- **Samples:** 2,459 clips (1,400 normal + 1,059 anomaly across machine IDs 01–04).
- **Classes:** 2 (binary: 0 = normal, 1 = anomaly).
- **Feature shape per clip:** (196, 640) float32.
- **Columns:** `features` (2D array), `label` (int), `filename` (str, source WAV name for provenance only).

## Intended use

Benchmark evaluation for edge AI anomaly detection. Designed to pair with MLPerf Tiny's reference autoencoder (`ad01_int8.tflite`, 640-dim input, dense AE).

The Hugging Face dataset is private. Public reproducers should fetch DCASE 2020
Task 2 ToyCar from Zenodo and run `uv run python scripts/datasets/stage_dcase.py`
followed by `uv run python scripts/datasets/prepare_ad.py`.

## MCU subset

A 100-sample class-balanced subset (50 normal + 50 anomaly, one random frame per clip, `seed=42`) is generated at `data/mcu_subsets/ad/subset_v1.npz`. Subset arrays: `inputs` (100, 640) float32 + `labels` (100,) int64 + `sources` (100,) string.

Balanced 50/50 is a deliberate stratification choice for MCU benchmarking (per-sample latency/energy measurement on balanced classes), deviating from the source distribution (1,400 normal / 1,059 anomaly). To regenerate: `uv run python scripts/datasets/prepare_ad.py`.

## Citation

```bibtex
@misc{signalbench-ad-v1,
  author = {Brown, Daniel},
  title = {Signal-Bench AD Test Set v1},
  year = {2026},
  publisher = {Agoo AI},
  howpublished = {\url{https://huggingface.co/datasets/narteybrown/signal-bench-ad-v1}},
}

@inproceedings{Koizumi_WASPAA2019_01,
  author = {Koizumi, Yuma and Saito, Shoichiro and Uematsu, Hisashi and Harada, Noboru and Imoto, Keisuke},
  title = {{ToyADMOS}: A Dataset of Miniature-machine Operating Sounds for Anomalous Sound Detection},
  booktitle = {Proceedings of {IEEE} Workshop on Applications of Signal Processing to Audio and Acoustics ({WASPAA})},
  year = {2019},
  pages = {308--312},
}

@inproceedings{Koizumi_DCASE2020_01,
  author = {Koizumi, Yuma and Kawaguchi, Yohei and Imoto, Keisuke and others},
  title = {Description and Discussion on {DCASE}2020 Challenge Task2: Unsupervised Anomalous Sound Detection for Machine Condition Monitoring},
  booktitle = {Proceedings of the DCASE 2020 Workshop},
  year = {2020},
  pages = {81--85},
}
```

## Limitations

ToyADMOS recordings were collected from miniature toy machines (not real industrial equipment), with environmental noise mixed in post-recording. Benchmark results using this set measure inference performance on a standardized reference workload; they do not generalize to real-world industrial anomaly detection.

The MCU subset (100 frames, 50/50 balanced) is small enough that per-class anomaly-score statistics have wide confidence intervals; it is intended for latency and energy measurement, not AUC reporting.

## License

DCASE 2020 Task 2 is licensed CC BY-NC-SA 4.0. The feature matrices are derivative works of that upstream dataset and carry the same NonCommercial and ShareAlike constraints. Users requiring the source audio must obtain it directly from Zenodo record `3678171`.
