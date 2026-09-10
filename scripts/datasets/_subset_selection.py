# SPDX-License-Identifier: Apache-2.0
"""Shared deterministic subset selection for signal-bench dataset prep.

Used by all three Phase 5 dataset prep scripts (KWS, IC, AD) to produce
byte-deterministic, stratified test-set subsets at the MCU subset size.
Single source of truth for the seed + subset size — changing either
breaks reproducibility of every published MCU subset, so they're
locked here per strategy §9 D61-A.
"""

from __future__ import annotations

import numpy as np

SEED = 42
SUBSET_SIZE = 100


def select_subset(
    inputs: np.ndarray,
    labels: np.ndarray,
    n: int = SUBSET_SIZE,
    seed: int = SEED,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Return a stratified deterministic subset of the test data.

    Each class contributes either ``n // num_classes`` or
    ``n // num_classes + 1`` samples; classes with the smaller index
    receive the extras when ``n`` is not evenly divisible. Indices are
    returned sorted so the subset's order is reproducible across
    machines.
    """
    rng = np.random.default_rng(seed)
    classes = np.unique(labels)
    per_class = n // len(classes)
    extras = n % len(classes)

    indices: list[int] = []
    for i, cls in enumerate(classes):
        cls_indices = np.where(labels == cls)[0]
        cls_sample_size = per_class + (1 if i < extras else 0)
        cls_sample = rng.choice(cls_indices, size=cls_sample_size, replace=False)
        indices.extend(int(x) for x in cls_sample)

    indices.sort()
    return inputs[indices], labels[indices], indices


def select_balanced_clips(
    labels: np.ndarray,
    n_per_class: int,
    seed: int = SEED,
) -> dict[int, list[int]]:
    """Return ``{class_id: [sorted clip indices]}`` with exactly ``n_per_class`` per class.

    Used by AD's MCU subset selector to force a 50/50 normal/anomaly split
    (D64-C) without threading a ``force_balanced=`` flag through the
    proportional-stratified :func:`select_subset` helper.

    The returned mapping is deterministic against ``seed`` and the row
    order of ``labels``. Caller is responsible for downstream
    per-clip-then-frame sampling — see ``prepare_ad.select_balanced_subset``.
    """
    rng = np.random.default_rng(seed)
    out: dict[int, list[int]] = {}
    for cls in np.unique(labels):
        cls_indices = np.where(labels == cls)[0]
        picked = rng.choice(cls_indices, size=n_per_class, replace=False)
        out[int(cls)] = sorted(int(x) for x in picked)
    return out
