# SPDX-License-Identifier: Apache-2.0
"""Prepare DCASE 2020 Task 2 ToyCar test partition for signal-bench Phase 5 AD benchmarks.

Reads raw audio from local staging at
``~/data/dcase-2020-task2/ToyCar/test/`` (populated by
``scripts/datasets/stage_dcase.py``), extracts 640-dim log-mel-spectrogram
features via the MLPerf Tiny v1.2 AD reference pipeline (upstream
``benchmark/training/anomaly_detection/common.py::file_to_vector_array`` at
commit ``5dae3296...``), generates a class-balanced 100-sample MCU subset
(50 normal + 50 anomaly, one random frame per clip, seed=42), and writes the
local subset. Maintainers can explicitly publish the per-clip feature matrices
to Hugging Face with ``--publish``, but normal reproduction only regenerates the
local subset.

DCASE 2020 Task 2 is licensed CC BY-NC-SA 4.0. Users must run
``scripts/datasets/stage_dcase.py`` to fetch the upstream audio themselves.

Feature pipeline (pinned to upstream baseline.yaml + common.py):
  16 kHz audio
    → librosa.feature.melspectrogram(n_fft=1024, hop_length=512,
                                      n_mels=128, power=2.0)   # power spectrum
    → 20/power * log10(mel + sys.float_info.epsilon)            # dB conversion
    → [:, 50:250]                                                # 200-frame central slice
    → 5-frame context concatenation                              # 128 x 5 = 640
    → (196, 640) float32 per clip

Numerical-fidelity note: this script uses librosa rather than TF (the
KWS-slice choice) because the upstream AD pipeline uses librosa. Same
"match the upstream library, not just the upstream math" discipline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.datasets._subset_selection import SEED, select_balanced_clips

# Mel-spectrogram parameters pinned to upstream
# `benchmark/training/anomaly_detection/baseline.yaml` + `common.py`
# at commit 5dae3296bd899ed58a65311a8e6fd91d83f664ab.
SAMPLE_RATE = 16_000
N_MELS = 128
N_FFT = 1024
HOP_LENGTH = 512
POWER = 2.0
FRAMES = 5  # context-concatenation width
TIME_SLICE = slice(50, 250)  # central 200 frames per upstream common.py:3b
LOG_EPSILON = sys.float_info.epsilon  # upstream uses sys.float_info.epsilon
EXPECTED_VECTOR_DIM = N_MELS * FRAMES  # 640

DEFAULT_DCASE_DIR = Path.home() / "data" / "dcase-2020-task2" / "ToyCar" / "test"
SUBSET_PATH = _REPO_ROOT / "data" / "mcu_subsets" / "ad" / "subset_v1.npz"
DATASET_CARD_PATH = Path(__file__).parent / "dataset_cards" / "ad.md"
HF_REPO_ID = "narteybrown/signal-bench-ad-v1"

N_PER_CLASS_IN_SUBSET = 50  # 50 normal + 50 anomaly = 100-sample MCU subset


def file_to_vector_array(wav_path: Path) -> np.ndarray:
    """Return ``(n_vectors, 640)`` float32 feature array for one WAV file.

    Mirrors upstream MLPerf Tiny AD ``common.py::file_to_vector_array``
    exactly: power-spectrum mel filterbank, dB-scaled log, central
    200-frame slice, 5-frame context concatenation.
    """
    import librosa
    import soundfile as sf

    audio, sr = sf.read(wav_path)
    if sr != SAMPLE_RATE:
        raise RuntimeError(f"expected {SAMPLE_RATE} Hz audio, got {sr} Hz in {wav_path}")

    mel_spectrogram = librosa.feature.melspectrogram(
        y=audio.astype(np.float32),
        sr=SAMPLE_RATE,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH,
        n_mels=N_MELS,
        power=POWER,
    )
    # dB-scaled log per upstream: `20.0 / power * np.log10(mel + epsilon)`.
    # For power=2.0 this reduces to 10 * log10(mel + epsilon).
    log_mel = (20.0 / POWER) * np.log10(mel_spectrogram + LOG_EPSILON)
    # Central 200-frame slice (upstream "3b take central part only").
    log_mel = log_mel[:, TIME_SLICE]

    n_frames = log_mel.shape[1]
    n_vectors = n_frames - FRAMES + 1
    if n_vectors < 1:
        return np.empty((0, EXPECTED_VECTOR_DIM), dtype=np.float32)

    # Context concatenation: each output row stitches together FRAMES
    # consecutive log-mel columns (128 mels x 5 frames = 640 dim).
    vectors = np.zeros((n_vectors, EXPECTED_VECTOR_DIM), dtype=np.float32)
    for t in range(FRAMES):
        vectors[:, N_MELS * t : N_MELS * (t + 1)] = log_mel[:, t : t + n_vectors].T
    return vectors


def parse_label(filename: str) -> int:
    """Return ``0`` for normal_*.wav, ``1`` for anomaly_*.wav."""
    if filename.startswith("normal_"):
        return 0
    if filename.startswith("anomaly_"):
        return 1
    raise RuntimeError(f"unexpected DCASE filename prefix: {filename}")


def fetch_features(
    dcase_dir: Path,
) -> tuple[list[np.ndarray], np.ndarray, list[str]]:
    """Walk ``dcase_dir`` and return per-clip feature matrices + labels + names."""
    if not dcase_dir.exists():
        raise SystemExit(
            f"ERROR: DCASE ToyCar test directory not found at {dcase_dir}\n"
            f"       Run: uv run python scripts/datasets/stage_dcase.py"
        )
    wav_files = sorted(dcase_dir.glob("*.wav"))
    if not wav_files:
        raise SystemExit(
            f"ERROR: no .wav files in {dcase_dir}\n"
            f"       Run: uv run python scripts/datasets/stage_dcase.py"
        )

    print(f"[prepare_ad] processing {len(wav_files)} WAV files from {dcase_dir}", file=sys.stderr)
    per_clip_features: list[np.ndarray] = []
    labels: list[int] = []
    filenames: list[str] = []
    for i, wav_path in enumerate(wav_files):
        vectors = file_to_vector_array(wav_path)
        per_clip_features.append(vectors)
        labels.append(parse_label(wav_path.name))
        filenames.append(wav_path.name)
        if (i + 1) % 250 == 0:
            print(f"  [{i + 1}/{len(wav_files)}] processed", file=sys.stderr)

    labs = np.asarray(labels, dtype=np.int64)
    print(
        f"[prepare_ad] {len(per_clip_features)} clips: "
        f"{(labs == 0).sum()} normal, {(labs == 1).sum()} anomaly",
        file=sys.stderr,
    )
    return per_clip_features, labs, filenames


def select_balanced_subset(
    per_clip_features: list[np.ndarray],
    labels: np.ndarray,
    filenames: list[str],
    n_per_class: int = N_PER_CLASS_IN_SUBSET,
    seed: int = SEED,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return ``(100, 640)`` MCU subset: 50 normal + 50 anomaly, one random frame per clip.

    Deterministic against ``seed``; uses per-clip RNG (``seed + clip_idx``)
    so each clip's chosen frame is reproducible independently of selection
    order.
    """
    picks = select_balanced_clips(labels, n_per_class, seed=seed)
    selected_clip_indices: list[int] = picks[0] + picks[1]
    selected_clip_indices.sort()

    selected_features = []
    selected_labels = []
    selected_sources = []
    for clip_idx in selected_clip_indices:
        clip_vectors = per_clip_features[clip_idx]
        if clip_vectors.shape[0] == 0:
            raise RuntimeError(f"clip {filenames[clip_idx]} produced 0 feature vectors")
        frame_rng = np.random.default_rng(seed + clip_idx)
        frame_idx = int(frame_rng.integers(0, clip_vectors.shape[0]))
        selected_features.append(clip_vectors[frame_idx])
        selected_labels.append(int(labels[clip_idx]))
        selected_sources.append(filenames[clip_idx])

    return (
        np.stack(selected_features, axis=0).astype(np.float32),
        np.asarray(selected_labels, dtype=np.int64),
        selected_sources,
    )


def write_subset(
    inputs: np.ndarray,
    labels: np.ndarray,
    sources: list[str],
) -> None:
    """Write the MCU subset to ``data/mcu_subsets/ad/subset_v1.npz``."""
    SUBSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        SUBSET_PATH,
        inputs=inputs,
        labels=labels,
        sources=np.asarray(sources),
    )
    print(
        f"[prepare_ad] subset written: {SUBSET_PATH} " f"({SUBSET_PATH.stat().st_size:,} bytes)",
        file=sys.stderr,
    )


def publish_to_hub(
    per_clip_features: list[np.ndarray],
    labels: np.ndarray,
    filenames: list[str],
) -> None:
    """Push the full per-clip feature dataset to HF as a literal ``test`` split."""
    from datasets import Dataset, DatasetDict
    from huggingface_hub import HfApi

    test_split = Dataset.from_dict(
        {
            "features": [vec.tolist() for vec in per_clip_features],
            "label": labels.tolist(),
            "filename": filenames,
        }
    )
    hf_ds = DatasetDict({"test": test_split})
    print(
        f"[prepare_ad] pushing {len(test_split)} rows to {HF_REPO_ID} " "(split: 'test')",
        file=sys.stderr,
    )
    hf_ds.push_to_hub(HF_REPO_ID, private=True)

    api = HfApi()
    api.upload_file(
        path_or_fileobj=str(DATASET_CARD_PATH),
        path_in_repo="README.md",
        repo_id=HF_REPO_ID,
        repo_type="dataset",
    )
    print(
        f"[prepare_ad] published: https://huggingface.co/datasets/{HF_REPO_ID}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    """Fetch features, write the MCU subset, and optionally publish the dataset."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument(
        "--dcase-dir",
        type=Path,
        default=DEFAULT_DCASE_DIR,
        help="Path to the staged DCASE ToyCar test/ directory.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Maintainer-only: publish the full feature set to Hugging Face.",
    )
    args = parser.parse_args(argv)
    dcase_dir = args.dcase_dir.expanduser()

    per_clip_features, labels, filenames = fetch_features(dcase_dir)

    sub_inputs, sub_labels, sub_sources = select_balanced_subset(
        per_clip_features, labels, filenames
    )
    assert sub_inputs.shape == (2 * N_PER_CLASS_IN_SUBSET, EXPECTED_VECTOR_DIM)
    assert sub_labels.shape == (2 * N_PER_CLASS_IN_SUBSET,)
    assert (sub_labels == 0).sum() == N_PER_CLASS_IN_SUBSET
    assert (sub_labels == 1).sum() == N_PER_CLASS_IN_SUBSET
    write_subset(sub_inputs, sub_labels, sub_sources)

    if args.publish:
        publish_to_hub(per_clip_features, labels, filenames)
    else:
        print(
            "[prepare_ad] skipped Hugging Face publish; pass --publish to upload", file=sys.stderr
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
