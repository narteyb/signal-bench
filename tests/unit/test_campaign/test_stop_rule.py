# SPDX-License-Identifier: Apache-2.0
"""Tests for the campaign discard stop rule."""

import pytest

from signal_bench.campaign.stop_rule import CampaignStopRule, StopRuleConfig


def test_first_discard_does_not_trigger_rate_condition() -> None:
    decision = CampaignStopRule().evaluate(attempts=1, discards=1)

    assert decision.stop is False
    assert decision.discard_rate is None


def test_rate_is_not_triggered_at_exactly_twenty_five_percent() -> None:
    decision = CampaignStopRule().evaluate(attempts=4, discards=1)

    assert decision.stop is False
    assert decision.discard_rate == pytest.approx(0.25)


def test_rate_triggers_after_minimum_attempts() -> None:
    decision = CampaignStopRule().evaluate(attempts=4, discards=2)

    assert decision.stop is True
    assert decision.reason == "discard rate exceeded: 2/4 = 0.500 > 0.250"


def test_absolute_limit_applies_before_rate_is_available() -> None:
    decision = CampaignStopRule().evaluate(attempts=3, discards=3)

    assert decision.stop is True
    assert decision.reason == "absolute discard limit reached: 3 >= 3"
    assert decision.discard_rate is None


def test_absolute_limit_applies_even_when_rate_is_low() -> None:
    decision = CampaignStopRule().evaluate(attempts=20, discards=3)

    assert decision.stop is True
    assert decision.reason == "absolute discard limit reached: 3 >= 3"


def test_invalid_counts_are_rejected() -> None:
    rule = CampaignStopRule()

    with pytest.raises(ValueError, match="must not be negative"):
        rule.evaluate(attempts=-1, discards=0)
    with pytest.raises(ValueError, match="must not exceed"):
        rule.evaluate(attempts=1, discards=2)


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        StopRuleConfig(min_attempts_for_rate=0)
    with pytest.raises(ValueError, match="between 0 and 1"):
        StopRuleConfig(discard_rate_limit=1.0)
    with pytest.raises(ValueError, match="must be positive"):
        StopRuleConfig(max_discards=0)
