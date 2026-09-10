# SPDX-License-Identifier: Apache-2.0
"""Public-domain prompt fixtures for Experiment 01."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptTier:
    """One deterministic LLM workload tier."""

    name: str
    prompt: str
    max_tokens: int


SHORT = PromptTier(
    name="short",
    max_tokens=50,
    prompt=(
        "What year was the Eiffel Tower completed? Answer in one sentence and include no "
        "additional context."
    ),
)

MEDIUM = PromptTier(
    name="medium",
    max_tokens=150,
    prompt=(
        "Summarize the following public-domain passage in one clear paragraph, then list two "
        "observations about its tone.\n\n"
        "It was the best of times, it was the worst of times, it was the age of wisdom, it was "
        "the age of foolishness, it was the epoch of belief, it was the epoch of incredulity, "
        "it was the season of Light, it was the season of Darkness, it was the spring of hope, "
        "it was the winter of despair, we had everything before us, we had nothing before us, "
        "we were all going direct to Heaven, we were all going direct the other way."
    ),
)

_LONG_EXCERPT = """
When in the Course of human events, it becomes necessary for one people to dissolve the
political bands which have connected them with another, and to assume among the powers of the
earth, the separate and equal station to which the Laws of Nature and of Nature's God entitle
them, a decent respect to the opinions of mankind requires that they should declare the causes
which impel them to the separation.

We hold these truths to be self-evident, that all men are created equal, that they are endowed
by their Creator with certain unalienable Rights, that among these are Life, Liberty and the
pursuit of Happiness. That to secure these rights, Governments are instituted among Men,
deriving their just powers from the consent of the governed. That whenever any Form of
Government becomes destructive of these ends, it is the Right of the People to alter or to
abolish it, and to institute new Government, laying its foundation on such principles and
organizing its powers in such form, as to them shall seem most likely to effect their Safety
and Happiness.
"""

LONG = PromptTier(
    name="long",
    max_tokens=160,
    prompt=(
        "Analyze the following public-domain excerpt. First provide a concise summary, then "
        "identify the central claim, the supporting reasoning, and one possible limitation of "
        "the argument when read by a modern audience.\n\n"
        f"{_LONG_EXCERPT}"
        f"{_LONG_EXCERPT}"
        f"{_LONG_EXCERPT}"
        f"{_LONG_EXCERPT}"
    ),
)

PROMPT_TIERS = {tier.name: tier for tier in (SHORT, MEDIUM, LONG)}
