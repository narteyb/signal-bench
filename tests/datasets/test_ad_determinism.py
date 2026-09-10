# SPDX-License-Identifier: Apache-2.0
"""Verify AD subset selection is byte-deterministic and 50/50 class-balanced.

Uses synthetic per-clip feature matrices so the test runs without DCASE
audio, librosa, or any heavy deps. The determinism guarantee is about
the selection helpers (``select_balanced_clips`` in the shared module +
``select_balanced_subset`` in ``prepare_ad``), not the feature pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.datasets._subset_selection import select_balanced_clips  # noqa: E402


def _make_synthetic_corpus(  # noqa: PLR0913
    n_clips: int = 2_500,
    n_normal: int = 1_400,
    n_anomaly: int = 1_100,
    vectors_per_clip: int = 196,
    feature_dim: int = 640,
    rng_seed: int = 0,
) -> tuple[list[np.ndarray], np.ndarray, list[str]]:
    """Return synthetic per-clip features, labels, filenames."""
    if n_normal + n_anomaly != n_clips:
        msg = "n_normal + n_anomaly must equal n_clips"
        raise ValueError(msg)
    rng = np.random.default_rng(rng_seed)
    per_clip = [
        rng.standard_normal((vectors_per_clip, feature_dim)).astype(np.float32)
        for _ in range(n_clips)
    ]
    labels = np.concatenate(
        [
            np.zeros(n_normal, dtype=np.int64),
            np.ones(n_anomaly, dtype=np.int64),
        ]
    )
    rng.shuffle(labels)
    filenames = [
        f"{'normal' if labels[i] == 0 else 'anomaly'}_id_01_{i:08d}.wav" for i in range(n_clips)
    ]
    return per_clip, labels, filenames


def test_balanced_clip_selection_is_deterministic() -> None:
    """Same seed produces identical clip-index picks across runs."""
    _, labels, _ = _make_synthetic_corpus()
    picks_1 = select_balanced_clips(labels, n_per_class=50, seed=42)
    picks_2 = select_balanced_clips(labels, n_per_class=50, seed=42)
    assert picks_1 == picks_2
    assert len(picks_1[0]) == 50
    assert len(picks_1[1]) == 50


def test_balanced_subset_is_50_50() -> None:
    """End-to-end subset selection yields exactly 50 normal + 50 anomaly."""
    from scripts.datasets.prepare_ad import select_balanced_subset  # noqa: PLC0415

    per_clip, labels, filenames = _make_synthetic_corpus()
    inputs, sub_labels, sources = select_balanced_subset(
        per_clip, labels, filenames, n_per_class=50, seed=42
    )

    assert inputs.shape == (100, 640)
    assert inputs.dtype == np.float32
    assert sub_labels.shape == (100,)
    assert (sub_labels == 0).sum() == 50
    assert (sub_labels == 1).sum() == 50
    assert len(sources) == 100


def test_balanced_subset_byte_deterministic() -> None:
    """End-to-end subset selection is byte-identical across two invocations."""
    from scripts.datasets.prepare_ad import select_balanced_subset  # noqa: PLC0415

    per_clip, labels, filenames = _make_synthetic_corpus()
    a = select_balanced_subset(per_clip, labels, filenames, n_per_class=50, seed=42)
    b = select_balanced_subset(per_clip, labels, filenames, n_per_class=50, seed=42)

    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[1], b[1])
    assert a[2] == b[2]
