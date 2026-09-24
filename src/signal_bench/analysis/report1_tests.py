"""Tests and agreement measures for independent Report 1 sessions.

All continuous comparisons accept one positive value per independent session.
Log-scale inference uses SciPy distributions; no inference row is an analysis unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb, exp, isfinite, log, sqrt
from statistics import mean, stdev, variance
from typing import TYPE_CHECKING

from scipy.stats import f as f_distribution
from scipy.stats import studentized_range

if TYPE_CHECKING:
    from collections.abc import Sequence

MIN_GROUP_SIZE = 2
MIN_OMNIBUS_GROUPS = 3


@dataclass(frozen=True)
class WelchResult:
    """Welch omnibus statistic and conventional log-scale omega squared."""

    f: float
    df1: float
    df2: float
    p: float
    omega_squared: float


@dataclass(frozen=True)
class PairResult:
    """Games-Howell pair with an exact permutation sensitivity p-value."""

    ratio: float
    lower: float
    upper: float
    p_adjusted: float
    hedges_g: float | None
    n_first: int
    n_second: int
    permutation_p: float


@dataclass(frozen=True)
class BlandAltman:
    """Mean paired log difference and 95% limits of agreement."""

    n: int
    log_bias: float
    log_lower: float
    log_upper: float
    ratio_bias: float
    ratio_lower: float
    ratio_upper: float


def _positive_logs(values: Sequence[float]) -> list[float]:
    if len(values) < MIN_GROUP_SIZE:
        message = "At least two sessions are needed per group"
        raise ValueError(message)
    if any(not isfinite(value) or value <= 0 for value in values):
        message = "Session outcomes must be positive and finite"
        raise ValueError(message)
    return [log(value) for value in values]


def welch_anova(groups: Sequence[Sequence[float]]) -> WelchResult | None:
    """Welch ANOVA on logs; return None when a group has zero variance.

    Omega squared is the conventional ANOVA sum-of-squares effect-size estimate
    on the same logs; it is descriptive and is not a Welch-weighted effect size.
    """
    logs = [_positive_logs(group) for group in groups]
    k = len(logs)
    if k < MIN_OMNIBUS_GROUPS:
        message = "Welch omnibus requires at least three groups"
        raise ValueError(message)
    sizes = [len(group) for group in logs]
    variances = [variance(group) for group in logs]
    if any(value <= 0 for value in variances):
        return None
    means = [mean(group) for group in logs]
    weights = [size / value for size, value in zip(sizes, variances, strict=True)]
    total_weight = sum(weights)
    weighted_mean = sum(w * m for w, m in zip(weights, means, strict=True)) / total_weight
    correction_sum = sum(
        (1 - weight / total_weight) ** 2 / (size - 1)
        for weight, size in zip(weights, sizes, strict=True)
    )
    df1 = float(k - 1)
    df2 = (k**2 - 1) / (3 * correction_sum)
    numerator = (
        sum(
            weight * (group_mean - weighted_mean) ** 2
            for weight, group_mean in zip(weights, means, strict=True)
        )
        / df1
    )
    f_value = numerator / (1 + 2 * (k - 2) * correction_sum / (k**2 - 1))
    grand_mean = mean(value for group in logs for value in group)
    ss_between = sum(
        size * (group_mean - grand_mean) ** 2 for size, group_mean in zip(sizes, means, strict=True)
    )
    ss_within = sum((len(group) - 1) * value for group, value in zip(logs, variances, strict=True))
    ms_within = ss_within / (sum(sizes) - k)
    omega = max(0.0, (ss_between - df1 * ms_within) / (ss_between + ss_within + ms_within))
    return WelchResult(f_value, df1, df2, float(f_distribution.sf(f_value, df1, df2)), omega)


def exact_permutation_pair(first: Sequence[float], second: Sequence[float]) -> float:
    """Two-sided exact permutation p for mean log difference, including ties."""
    a, b = _positive_logs(first), _positive_logs(second)
    pooled = a + b
    n = len(a)
    observed = abs(mean(a) - mean(b))
    extreme = 0
    for indices in combinations(range(len(pooled)), n):
        chosen = set(indices)
        difference = abs(
            mean(pooled[i] for i in chosen)
            - mean(pooled[i] for i in range(len(pooled)) if i not in chosen)
        )
        extreme += difference >= observed - 1e-12
    return extreme / comb(len(pooled), n)


def games_howell(
    first: Sequence[float], second: Sequence[float], *, group_count: int = 3
) -> PairResult | None:
    """Games-Howell all-pairs-adjusted interval and p on mean log difference.

    A zero standard error in both groups leaves the interval unestimable. A
    single zero-variance group is permitted because the other group supplies
    the Welch standard error and degrees of freedom.
    """
    a, b = _positive_logs(first), _positive_logs(second)
    n_a, n_b = len(a), len(b)
    var_a, var_b = variance(a), variance(b)
    v_a, v_b = var_a / n_a, var_b / n_b
    if v_a + v_b <= 0:
        return None
    difference = mean(a) - mean(b)
    df = (v_a + v_b) ** 2 / (v_a**2 / (n_a - 1) + v_b**2 / (n_b - 1))
    se = sqrt((v_a + v_b) / 2)
    q = abs(difference) / se
    critical = studentized_range.ppf(0.95, group_count, df)
    p_adjusted = float(studentized_range.sf(q, group_count, df))
    pooled_sd = sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2))
    hedges = (difference / pooled_sd) * (1 - 3 / (4 * (n_a + n_b - 2) - 1)) if pooled_sd else None
    return PairResult(
        exp(difference),
        exp(difference - critical * se),
        exp(difference + critical * se),
        p_adjusted,
        hedges,
        n_a,
        n_b,
        exact_permutation_pair(first, second),
    )


def bland_altman_log(ina219: Sequence[float], fnb58: Sequence[float]) -> BlandAltman:
    """FNB58 versus INA219 log-ratio bias and mean ±1.96 SD limits."""
    if len(ina219) != len(fnb58) or len(ina219) < MIN_GROUP_SIZE:
        message = "At least two paired meter sessions are required"
        raise ValueError(message)
    paired = [
        log(b / a)
        for a, b in zip(ina219, fnb58, strict=True)
        if isfinite(a) and isfinite(b) and a > 0 and b > 0
    ]
    if len(paired) != len(ina219):
        message = "Meter energy must be positive"
        raise ValueError(message)
    bias = mean(paired)
    halfwidth = 1.96 * stdev(paired)
    return BlandAltman(
        len(paired),
        bias,
        bias - halfwidth,
        bias + halfwidth,
        exp(bias),
        exp(bias - halfwidth),
        exp(bias + halfwidth),
    )


def cohen_kappa(first: Sequence[int], second: Sequence[int]) -> float | None:
    """Unweighted nominal agreement; None when expected agreement is one."""
    if len(first) != len(second) or not first:
        message = "Kappa requires matched nonempty inputs"
        raise ValueError(message)
    labels = set(first) | set(second)
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    expected = sum(first.count(label) * second.count(label) for label in labels) / n**2
    return (observed - expected) / (1 - expected) if expected < 1 else None


def fleiss_kappa(board_predictions: Sequence[Sequence[int]]) -> float | None:
    """Nominal Fleiss agreement across boards on the same input indices."""
    if len(board_predictions) < MIN_GROUP_SIZE or not board_predictions[0]:
        message = "Fleiss kappa requires at least two boards and one input"
        raise ValueError(message)
    n_inputs = len(board_predictions[0])
    if any(len(board) != n_inputs for board in board_predictions):
        message = "All boards must cover the same inputs"
        raise ValueError(message)
    raters = len(board_predictions)
    labels = {value for board in board_predictions for value in board}
    counts = [
        {label: sum(board[i] == label for board in board_predictions) for label in labels}
        for i in range(n_inputs)
    ]
    observed = mean(
        (sum(v * v for v in row.values()) - raters) / (raters * (raters - 1)) for row in counts
    )
    expected = sum(
        (sum(row[label] for row in counts) / (n_inputs * raters)) ** 2 for label in labels
    )
    return (observed - expected) / (1 - expected) if expected < 1 else None
