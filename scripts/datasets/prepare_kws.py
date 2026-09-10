# SPDX-License-Identifier: Apache-2.0
"""Prepare Google Speech Commands v0.02 for signal-bench Phase 5 benchmarking.

Sources Speech Commands v0.02 via TensorFlow Datasets (which handles the
testing-list partitioning and the `_silence_` / `_unknown_` synthesis per
Pete Warden's specification), extracts 49x10x1 MFCC features matching
`kws_ref_model.tflite`'s input shape, generates a deterministic 100-sample
MCU subset (seed=42, stratified across 12 classes), commits the subset to
the repo as `.npz`, and publishes the full test set to HuggingFace at
``narteybrown/signal-bench-kws-v1`` as a literal ``test`` split.

Pipeline: 16 kHz audio → 30 ms STFT windows / 20 ms stride
(``fft_length=512`` — auto next-pow2 ≥ 480) → 40 mel filters covering
20-4000 Hz → log mel → 10 MFCC coefficients across 49 frames
yielding (49, 10, 1) float32. Parameters pinned to upstream
``mlcommons/tiny/benchmark/training/keyword_spotting/{kws_util,get_dataset}.py``
at commit ``5dae3296bd899ed58a65311a8e6fd91d83f664ab``.

Pinning the MFCC pipeline to TensorFlow's ``tf.signal`` ops keeps the
extracted features byte-faithful to what MLPerf Tiny's reference DS-CNN
model was trained on. Numerical-drift risk vs. a librosa or pure-numpy
re-implementation would be silent (features look fine but model accuracy
drops without an obvious cause); avoiding that is the point.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Suppress TF's startup chatter before the import so the CLI output stays
# legible.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import numpy as np
import tensorflow as tf
import tensorflow_datasets as tfds

# Make `scripts.datasets.*` importable when this file is invoked directly
# as `uv run python scripts/datasets/prepare_kws.py` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.datasets._subset_selection import select_subset

# MFCC parameters pinned from MLPerf Tiny v1.2 KWS reference preprocessing
# (upstream: benchmark/training/keyword_spotting/{kws_util,get_dataset}.py).
SAMPLE_RATE = 16_000
CLIP_DURATION_MS = 1_000
WINDOW_LENGTH_MS = 30
WINDOW_STRIDE_MS = 20
WINDOW_LENGTH = int(SAMPLE_RATE * WINDOW_LENGTH_MS / 1000)  # 480
WINDOW_STRIDE = int(SAMPLE_RATE * WINDOW_STRIDE_MS / 1000)  # 320
FFT_LENGTH = 512  # next pow2 ≥ WINDOW_LENGTH
N_MFCC = 10
N_FRAMES = 49
N_MELS = 40
F_MIN = 20.0
F_MAX = 4000.0

# 12-class target set (MLPerf Tiny v1.2 KWS).
TARGET_LABELS = (
    "down",
    "go",
    "left",
    "no",
    "off",
    "on",
    "right",
    "stop",
    "up",
    "yes",
    "_silence_",
    "_unknown_",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBSET_PATH = REPO_ROOT / "data" / "mcu_subsets" / "kws" / "subset_v1.npz"
DATASET_CARD_PATH = Path(__file__).parent / "dataset_cards" / "kws.md"
HF_REPO_ID = "narteybrown/signal-bench-kws-v1"
DEFAULT_CACHE = Path.home() / ".cache" / "signal-bench" / "datasets" / "tfds"


def extract_mfcc(audio: tf.Tensor) -> tf.Tensor:
    """Return a (49, 10, 1) float32 MFCC tensor for a 1-second 16 kHz clip.

    Mirrors upstream ``kws_util.py``'s preprocessing exactly:
    audio → STFT → magnitude spectrum → linear-to-mel weight matrix →
    log mel → MFCC (DCT-II) → take the first 10 coefficients.
    """
    audio = tf.cast(audio, tf.float32)
    desired_samples = SAMPLE_RATE * CLIP_DURATION_MS // 1000
    audio = audio[:desired_samples]
    audio = tf.pad(audio, [[0, desired_samples - tf.shape(audio)[0]]])

    stft = tf.signal.stft(
        audio,
        frame_length=WINDOW_LENGTH,
        frame_step=WINDOW_STRIDE,
        fft_length=FFT_LENGTH,
        pad_end=False,
    )
    magnitude = tf.abs(stft)

    mel_weights = tf.signal.linear_to_mel_weight_matrix(
        num_mel_bins=N_MELS,
        num_spectrogram_bins=FFT_LENGTH // 2 + 1,
        sample_rate=SAMPLE_RATE,
        lower_edge_hertz=F_MIN,
        upper_edge_hertz=F_MAX,
    )
    mel_spectrogram = tf.matmul(magnitude, mel_weights)
    log_mel = tf.math.log(mel_spectrogram + 1e-6)

    mfcc = tf.signal.mfccs_from_log_mel_spectrograms(log_mel)[..., :N_MFCC]
    return tf.expand_dims(mfcc, axis=-1)  # (N_FRAMES, N_MFCC, 1)


def fetch_speech_commands_test(cache_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load Speech Commands v0.02 test split via TFDS and run MFCC.

    Returns
    -------
    features : np.ndarray, shape (N, 49, 10, 1), dtype float32
    labels   : np.ndarray, shape (N,), dtype int64

    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"[prepare_kws] TFDS cache: {cache_dir}", file=sys.stderr)
    print(
        "[prepare_kws] loading speech_commands test split via TFDS (may "
        "download ~2.4 GB on first run)",
        file=sys.stderr,
    )

    builder = tfds.builder("speech_commands", data_dir=str(cache_dir))
    label_names = builder.info.features["label"].names
    print(f"[prepare_kws] TFDS labels ({len(label_names)}): {label_names}", file=sys.stderr)
    if len(label_names) != len(TARGET_LABELS):
        raise RuntimeError(
            f"expected {len(TARGET_LABELS)} TFDS labels, got " f"{len(label_names)}: {label_names}"
        )

    ds = tfds.load(
        "speech_commands",
        split="test",
        data_dir=str(cache_dir),
        as_supervised=False,
    )

    features: list[np.ndarray] = []
    labels: list[int] = []
    for sample in tfds.as_numpy(ds):
        mfcc = extract_mfcc(tf.constant(sample["audio"])).numpy()
        features.append(mfcc.astype(np.float32))
        labels.append(int(sample["label"]))

    feats = np.stack(features, axis=0)
    labs = np.asarray(labels, dtype=np.int64)
    print(
        f"[prepare_kws] extracted {feats.shape[0]} MFCC tensors, "
        f"shape per sample: {feats.shape[1:]}",
        file=sys.stderr,
    )
    return feats, labs


def write_subset(inputs: np.ndarray, labels: np.ndarray, indices: list[int]) -> None:
    """Write the MCU subset to the repo as a compressed `.npz` file."""
    SUBSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        SUBSET_PATH,
        inputs=inputs,
        labels=labels,
        indices=np.asarray(indices, dtype=np.int64),
    )
    print(
        f"[prepare_kws] subset written: {SUBSET_PATH} " f"({SUBSET_PATH.stat().st_size:,} bytes)",
        file=sys.stderr,
    )


def publish_to_hub(features: np.ndarray, labels: np.ndarray) -> None:
    """Push the full test set to HuggingFace and upload the Dataset Card."""
    from datasets import Dataset, DatasetDict
    from huggingface_hub import HfApi

    test_split = Dataset.from_dict(
        {
            "mfcc": [features[i] for i in range(features.shape[0])],
            "label": labels.tolist(),
        }
    )
    hf_ds = DatasetDict({"test": test_split})
    print(
        f"[prepare_kws] pushing {len(test_split)} rows to {HF_REPO_ID} " "(split: 'test')",
        file=sys.stderr,
    )
    hf_ds.push_to_hub(HF_REPO_ID, private=False)

    api = HfApi()
    api.upload_file(
        path_or_fileobj=str(DATASET_CARD_PATH),
        path_in_repo="README.md",
        repo_id=HF_REPO_ID,
        repo_type="dataset",
    )
    print(
        f"[prepare_kws] published: https://huggingface.co/datasets/{HF_REPO_ID}",
        file=sys.stderr,
    )


def main() -> None:
    """Fetch, extract, write the MCU subset, and publish to HuggingFace."""
    features, labels = fetch_speech_commands_test(DEFAULT_CACHE)
    assert features.shape[1:] == (N_FRAMES, N_MFCC, 1), f"unexpected MFCC shape: {features.shape}"
    assert features.dtype == np.float32

    sub_features, sub_labels, indices = select_subset(features, labels)
    assert sub_features.shape == (100, N_FRAMES, N_MFCC, 1)
    assert sub_labels.shape == (100,)

    write_subset(sub_features, sub_labels, indices)
    publish_to_hub(features, labels)


if __name__ == "__main__":
    main()
