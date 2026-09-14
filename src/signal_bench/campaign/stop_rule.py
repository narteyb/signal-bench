# SPDX-License-Identifier: Apache-2.0
"""Stop policy for repeated measurement attempts within a campaign cell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StopRuleConfig:
    """Configuration for the campaign discard stop rule."""

    min_attempts_for_rate: int = 4
    discard_rate_limit: float = 0.25
    max_discards: int = 3

    def __post_init__(self) -> None:
        """Reject configurations that cannot express the approved policy."""
        if self.min_attempts_for_rate < 1:
            msg = "min_attempts_for_rate must be positive"
            raise ValueError(msg)
        if not 0.0 < self.discard_rate_limit < 1.0:
            msg = "discard_rate_limit must be between 0 and 1"
            raise ValueError(msg)
        if self.max_discards < 1:
            msg = "max_discards must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class StopDecision:
    """Result of evaluating the discard stop policy."""

    stop: bool
    reason: str | None
    attempts: int
    discards: int
    discard_rate: float | None


class CampaignStopRule:
    """Evaluate discard-based stop conditions for one campaign cell.

    The absolute discard limit applies from the first attempt. The rate
    condition is deliberately unavailable until the configured minimum number
    of attempts has been reached, so one early failure cannot produce a rate.
    """

    def __init__(self, config: StopRuleConfig | None = None) -> None:
        """Create a stop rule using the approved defaults unless overridden."""
        self.config = config or StopRuleConfig()

    def evaluate(self, *, attempts: int, discards: int) -> StopDecision:
        """Return whether the cell should stop after the supplied attempt counts."""
        if attempts < 0:
            msg = "attempts must not be negative"
            raise ValueError(msg)
        if discards < 0:
            msg = "discards must not be negative"
            raise ValueError(msg)
        if discards > attempts:
            msg = "discards must not exceed attempts"
            raise ValueError(msg)

        discard_rate = (
            discards / attempts
            if attempts >= self.config.min_attempts_for_rate
            else None
        )
        if discards >= self.config.max_discards:
            return StopDecision(
                stop=True,
                reason=(
                    f"absolute discard limit reached: {discards} >= "
                    f"{self.config.max_discards}"
                ),
                attempts=attempts,
                discards=discards,
                discard_rate=discard_rate,
            )
        if discard_rate is not None and discard_rate > self.config.discard_rate_limit:
            return StopDecision(
                stop=True,
                reason=(
                    f"discard rate exceeded: {discards}/{attempts} = "
                    f"{discard_rate:.3f} > {self.config.discard_rate_limit:.3f}"
                ),
                attempts=attempts,
                discards=discards,
                discard_rate=discard_rate,
            )
        return StopDecision(
            stop=False,
            reason=None,
            attempts=attempts,
            discards=discards,
            discard_rate=discard_rate,
        )
