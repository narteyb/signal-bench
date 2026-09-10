# SPDX-License-Identifier: Apache-2.0
"""Verify CIFAR-10 subset generation is byte-deterministic across runs.

Uses synthetic data so the test runs without a CIFAR-10 download. The
determinism guarantee is about the `select_subset` function, not the dataset
contents — same seed, same input, same indices, same output bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# scripts/ isn't on the default sys.path; add the repo root so the
# subset-selection helper can be imported from the prep script.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.datasets._subset_selection import SEED, SUBSET_SIZE, select_subset  # noqa: E402


def test_subset_is_deterministic() -> None:
    """Same seed produces byte-identical subsets across two invocations."""
    rng = np.random.default_rng(0)
    inputs = rng.integers(0, 256, size=(10_000, 32, 32, 3), dtype=np.uint8)
    labels = rng.integers(0, 10, size=10_000, dtype=np.int64)

    sub_in_1, sub_lab_1, idx_1 = select_subset(inputs, labels, seed=SEED)
    sub_in_2, sub_lab_2, idx_2 = select_subset(inputs, labels, seed=SEED)

    assert np.array_equal(sub_in_1, sub_in_2)
    assert np.array_equal(sub_lab_1, sub_lab_2)
    assert idx_1 == idx_2
    assert sub_in_1.shape == (SUBSET_SIZE, 32, 32, 3)
    assert sub_lab_1.shape == (SUBSET_SIZE,)


def test_subset_is_stratified() -> None:
    """Stratified selection: each of the 10 classes gets exactly 10 samples."""
    rng = np.random.default_rng(0)
    inputs = rng.integers(0, 256, size=(10_000, 32, 32, 3), dtype=np.uint8)
    labels = np.repeat(np.arange(10, dtype=np.int64), 1_000)

    _, sub_labels, _ = select_subset(inputs, labels, seed=SEED)

    counts = np.bincount(sub_labels, minlength=10)
    assert np.array_equal(counts, np.full(10, 10))
