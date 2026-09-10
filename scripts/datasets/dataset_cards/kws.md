---
license: cc-by-4.0
license_name: cc-by-4.0
license_link: https://creativecommons.org/licenses/by/4.0/
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
  - keyword-spotting
  - speech-commands
---

# Signal-Bench KWS Test Set v1

## What this is

The Google Speech Commands v0.02 test partition, filtered to the 12 MLPerf Tiny target classes and pre-processed to 49×10×1 MFCC features. Used by [signal-bench](https://github.com/narteybrown/signal-bench) for Phase 5 keyword-spotting benchmarks across the MCU-to-cloud hardware curve.

This is a derivative of Speech Commands v0.02 — specifically the test partition (sourced via TensorFlow Datasets, which handles the `testing_list.txt` partitioning and `_silence_`/`_unknown_` synthesis per Pete Warden's specification), filtered to MLPerf Tiny's 12-class target set, with MFCC features extracted using the exact parameters from MLPerf Tiny v1.2's KWS reference preprocessing.

## Source attribution

Google Speech Commands v0.02 was published by Pete Warden. Original dataset:
- URL: https://www.tensorflow.org/datasets/catalog/speech_commands
- License: Creative Commons Attribution 4.0
- Paper: Warden, P. "Speech commands: A dataset for limited-vocabulary speech recognition." arXiv:1804.03209 (2018).

MFCC preprocessing parameters match MLPerf Tiny v1.2's reference implementation:
- Pinned commit: `5dae3296bd899ed58a65311a8e6fd91d83f664ab`
- Source: https://github.com/mlcommons/tiny/blob/5dae3296bd899ed58a65311a8e6fd91d83f664ab/benchmark/training/keyword_spotting

## Processing

Each audio sample (1-second clips at 16 kHz) is converted to a 49×10×1 MFCC feature representation:
- 30 ms windows with 20 ms stride → 49 frames across the 1-second clip
- FFT length 512 (next power of 2 ≥ window length 480)
- 40 mel filters covering 20–4000 Hz
- 10 MFCC coefficients per frame
- Final shape: (49, 10, 1) float32

The MFCC pipeline is implemented via TensorFlow's `tf.signal.stft` + `tf.signal.linear_to_mel_weight_matrix` + `tf.signal.mfccs_from_log_mel_spectrograms`, matching MLPerf Tiny's reference `kws_util.py` byte-for-byte.

The 12 target classes match MLPerf Tiny's KWS task: 10 keywords (yes, no, up, down, left, right, on, off, stop, go) plus `_silence_` (synthesized from background_noise samples per Speech Commands convention) and `_unknown_` (sampled from non-target words). TFDS handles the synthesis automatically.

## Subset structure

- **Samples:** ~4,000–5,000 (Speech Commands test partition after filtering to 12 classes)
- **Classes:** 12
- **Feature shape:** 49×10×1 float32 MFCC

## Intended use

Benchmark evaluation for edge AI keyword spotting. Designed to pair with MLPerf Tiny's reference DS-CNN model (`kws_ref_model.tflite`).

```python
from datasets import load_dataset
ds = load_dataset("narteybrown/signal-bench-kws-v1", split="test")
print(ds)  # Single 'test' split with MFCC features and class labels
```

## MCU subset

A deterministic 100-sample stratified subset (8–9 samples per class, `seed=42`) is committed to the signal-bench repo at `data/mcu_subsets/kws/subset_v1.npz` for flashing into MCU firmware as C arrays. To regenerate: `uv run python scripts/datasets/prepare_kws.py`.

## Citation

```bibtex
@misc{signalbench-kws-v1,
  author = {Brown, Daniel},
  title = {Signal-Bench KWS Test Set v1},
  year = {2026},
  publisher = {Agoo AI},
  howpublished = {\url{https://huggingface.co/datasets/narteybrown/signal-bench-kws-v1}},
}

@article{warden2018speech,
  title={Speech commands: A dataset for limited-vocabulary speech recognition},
  author={Warden, Pete},
  journal={arXiv preprint arXiv:1804.03209},
  year={2018}
}
```

## Limitations

Speech Commands v0.02 was recorded in English, primarily by speakers in North America, in controlled conditions. Benchmark results using this set measure inference performance on a standardized reference workload; they do not generalize to real-world deployment with noise, accents, or far-field audio.

The MCU subset (100 samples) is small enough that per-class accuracy estimates have wide confidence intervals; it is intended for latency and energy measurement, not statistical accuracy reporting.

## License

CC-BY 4.0 (inherited from Speech Commands v0.02). Attribution requirements documented above.
