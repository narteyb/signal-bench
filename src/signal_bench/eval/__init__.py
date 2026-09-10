# SPDX-License-Identifier: Apache-2.0
"""Full evaluation helpers for hardware-backed benchmark targets."""

from signal_bench.eval.full_eval import (
    EvalRunConfig,
    FullEvalProtocolError,
    compute_ad_clip_auroc,
    compute_kws_top1,
    run_full_eval,
)

__all__ = [
    "EvalRunConfig",
    "FullEvalProtocolError",
    "compute_ad_clip_auroc",
    "compute_kws_top1",
    "run_full_eval",
]
