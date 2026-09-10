# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import datetime as dt

from signal_bench.phase1.accuracy import score_generations
from signal_bench.phase1.runtime import DecodeParams, GenerationResult
from signal_bench.phase1.workload import AccuracyCriterion, PromptCase


def _result(prompt_id: str, text: str) -> GenerationResult:
    now = dt.datetime.now(dt.UTC)
    return GenerationResult(
        prompt_id=prompt_id,
        started_at=now,
        finished_at=now,
        duration_ms=10.0,
        first_token_ms=1.0,
        tokens_in=8,
        tokens_out=4,
        text=text,
    )


def test_score_generations_uses_prompt_id_and_contains_all_criteria() -> None:
    prompts = (
        PromptCase(
            prompt_id="apollo",
            prompt="Name the mission.",
            decode=DecodeParams(),
            accuracy=AccuracyCriterion(kind="contains_all", expected=("Apollo", "11")),
        ),
        PromptCase(
            prompt_id="water",
            prompt="Formula?",
            decode=DecodeParams(),
            accuracy=AccuracyCriterion(kind="contains_all", expected=("H2O",)),
        ),
    )

    summary = score_generations(
        prompts,
        (
            _result("water", "The formula is H2O."),
            _result("apollo", "Apollo 11."),
        ),
    )

    assert summary.metric == "deterministic_contains_all"
    assert summary.score == 1.0
    assert summary.passed == 2
    assert [score.prompt_id for score in summary.prompt_scores] == ["apollo", "water"]


def test_score_generations_records_failed_criteria() -> None:
    prompt = PromptCase(
        prompt_id="eiffel",
        prompt="Year?",
        decode=DecodeParams(),
        accuracy=AccuracyCriterion(kind="contains_all", expected=("1889",)),
    )

    summary = score_generations((prompt,), (_result("eiffel", "Built in Paris."),))

    assert summary.score == 0.0
    assert summary.prompt_scores[0].passed is False
    assert summary.prompt_scores[0].expected == ("1889",)
    assert summary.prompt_scores[0].observed == "Built in Paris."
