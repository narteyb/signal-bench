# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from signal_bench.eval.full_eval import compute_ad_clip_auroc, compute_kws_top1


def test_compute_kws_top1_and_per_class() -> None:
    value, per_class = compute_kws_top1([0, 0, 1, 1], [0, 1, 1, 1])

    assert value == 0.75
    assert per_class == {"0": 0.5, "1": 1.0}


def test_compute_ad_clip_auroc_aggregates_patch_scores_by_clip_mean() -> None:
    value = compute_ad_clip_auroc(
        labels=[0, 0, 1, 1],
        scores=[0.1, 0.3, 0.7, 0.9],
        sources=["normal.wav", "normal.wav", "anomaly.wav", "anomaly.wav"],
    )

    assert value == 1.0
