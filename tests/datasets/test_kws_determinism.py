# SPDX-License-Identifier: Apache-2.0
"""Verify KWS subset generation is byte-deterministic + stratified.

Uses synthetic float32 MFCC-shaped arrays so the test runs without
TensorFlow, TFDS, or the ~2.4 GB Speech Commands download. The
determinism guarantee is about the shared `select_subset` helper,
not the dataset contents — same seed, same input, same selected
indices, same output bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.datasets._subset_selection import SEED, SUBSET_SIZE, select_subset  # noqa: E402


def test_subset_is_deterministic() -> None:
    """Same seed produces byte-identical subsets across two invocations."""
    rng = np.random.default_rng(0)
    inputs = rng.standard_normal((5_000, 49, 10, 1)).astype(np.float32)
    labels = rng.integers(0, 12, size=5_000, dtype=np.int64)

    sub_in_1, sub_lab_1, idx_1 = select_subset(inputs, labels, seed=SEED)
    sub_in_2, sub_lab_2, idx_2 = select_subset(inputs, labels, seed=SEED)

    assert np.array_equal(sub_in_1, sub_in_2)
    assert np.array_equal(sub_lab_1, sub_lab_2)
    assert idx_1 == idx_2
    assert sub_in_1.shape == (SUBSET_SIZE, 49, 10, 1)
    assert sub_lab_1.shape == (SUBSET_SIZE,)


def test_subset_is_class_balanced() -> None:
    """Stratified selection: all 12 KWS classes covered, 8 or 9 samples per class."""
    rng = np.random.default_rng(0)
    inputs = rng.standard_normal((5_000, 49, 10, 1)).astype(np.float32)
    labels = np.tile(np.arange(12, dtype=np.int64), 5_000 // 12 + 1)[:5_000]

    _, sub_labels, _ = select_subset(inputs, labels, seed=SEED)
    unique, counts = np.unique(sub_labels, return_counts=True)

    assert len(unique) == 12
    # 100 / 12 = 8.33 → expect 8s and 9s only.
    assert counts.max() - counts.min() <= 1
    assert {int(c) for c in counts} <= {8, 9}
