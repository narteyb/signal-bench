# SPDX-License-Identifier: Apache-2.0
"""Phase 1 deterministic SLM scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self

from signal_bench.phase1.runtime import GenerationResult
from signal_bench.phase1.workload import PromptCase


@dataclass(frozen=True, slots=True)
class PromptScore:
    """Accuracy result for one prompt."""

    prompt_id: str
    passed: bool
    score: float
    expected: tuple[str, ...]
    observed: str


@dataclass(frozen=True, slots=True)
class AccuracySummary:
    """Aggregate accuracy score for one run."""

    metric: str
    score: float
    passed: int
    total: int
    prompt_scores: tuple[PromptScore, ...]

    @property
    def pass_rate(self: Self) -> float:
        """Return the fraction of prompts passing their criterion."""
        return self.passed / self.total if self.total else 0.0


def score_generations(
    prompts: tuple[PromptCase, ...],
    results: tuple[GenerationResult, ...],
) -> AccuracySummary:
    """Score generation outputs against frozen deterministic criteria."""
    by_prompt = {result.prompt_id: result for result in results}
    scores: list[PromptScore] = []
    for prompt in prompts:
        result = by_prompt[prompt.prompt_id]
        normalized = _normalize(result.text)
        expected = tuple(_normalize(item) for item in prompt.accuracy.expected)
        if prompt.accuracy.kind != "contains_all":
            msg = f"unsupported accuracy criterion: {prompt.accuracy.kind}"
            raise ValueError(msg)
        passed = all(item in normalized for item in expected)
        scores.append(
            PromptScore(
                prompt_id=prompt.prompt_id,
                passed=passed,
                score=1.0 if passed else 0.0,
                expected=prompt.accuracy.expected,
                observed=result.text.strip(),
            ),
        )
    passed_count = sum(score.passed for score in scores)
    return AccuracySummary(
        metric="deterministic_contains_all",
        score=passed_count / len(scores) if scores else 0.0,
        passed=passed_count,
        total=len(scores),
        prompt_scores=tuple(scores),
    )


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
