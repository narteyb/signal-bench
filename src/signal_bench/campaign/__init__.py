# SPDX-License-Identifier: Apache-2.0
"""Campaign-level execution policies."""

from signal_bench.campaign.stop_rule import (
    CampaignStopRule,
    StopDecision,
    StopRuleConfig,
)

__all__ = ["CampaignStopRule", "StopDecision", "StopRuleConfig"]
