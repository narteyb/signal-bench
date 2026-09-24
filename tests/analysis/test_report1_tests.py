"""Known-answer synthetic checks at three independent sessions per board."""

import math

import numpy as np
import pytest
from statsmodels.stats.inter_rater import cohens_kappa as library_cohen
from statsmodels.stats.inter_rater import fleiss_kappa as library_fleiss
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.oneway import anova_oneway

from signal_bench.analysis.report1_tests import (
    bland_altman_log,
    cohen_kappa,
    exact_permutation_pair,
    fleiss_kappa,
    games_howell,
    welch_anova,
)


def test_welch_and_games_howell_against_statsmodels():
    groups = [[1, 1.02, 1.01], [2, 2.02, 2.01], [3, 3.01, 3.03]]
    logs = [np.log(group) for group in groups]
    ours = welch_anova(groups)
    reference = anova_oneway(logs, use_var="unequal")
    assert ours is not None
    assert ours.f == pytest.approx(reference.statistic, rel=1e-10)
    assert ours.df2 == pytest.approx(reference.df[1], rel=1e-10)
    assert ours.p == pytest.approx(reference.pvalue, rel=1e-9)
    assert 0 <= ours.omega_squared <= 1
    reference_pairs = pairwise_tukeyhsd(
        np.concatenate(logs), np.repeat(["a", "b", "c"], 3), use_var="unequal"
    )
    pair = games_howell(groups[0], groups[1])
    assert pair is not None
    assert pair.ratio == pytest.approx(math.exp(-reference_pairs.meandiffs[0]))
    assert pair.lower == pytest.approx(math.exp(-reference_pairs.confint[0, 1]), rel=1e-6)
    assert pair.upper == pytest.approx(math.exp(-reference_pairs.confint[0, 0]), rel=1e-6)
    assert pair.p_adjusted == pytest.approx(reference_pairs.pvalues[0], abs=1e-6)
    assert pair.n_first == pair.n_second == 3
    pooled = math.sqrt((2 * np.var(logs[0], ddof=1) + 2 * np.var(logs[1], ddof=1)) / 4)
    correction = 1 - 3 / (4 * 4 - 1)
    assert pair.hedges_g == pytest.approx(
        correction * (float(np.mean(logs[0])) - float(np.mean(logs[1]))) / pooled
    )
    all_logs = np.concatenate(logs)
    grand = float(np.mean(all_logs))
    between = sum(3 * (float(np.mean(group)) - grand) ** 2 for group in logs)
    within = sum(2 * float(np.var(group, ddof=1)) for group in logs)
    ms_within = within / 6
    assert ours.omega_squared == pytest.approx(
        (between - 2 * ms_within) / (between + within + ms_within)
    )


def test_null_and_zero_variance_resolution():
    identical = [1, 1.01, 1.02]
    assert exact_permutation_pair(identical, identical) == pytest.approx(1)
    assert welch_anova([[1, 1, 1], [2, 2, 2], [3, 3, 3]]) is None
    assert games_howell([1, 1, 1], [2, 2, 2]) is None


def test_exact_permutation_has_twenty_assignments():
    # Complete separation can only reach 2/20 = 0.10 two-sided.
    assert exact_permutation_pair([1, 1.01, 1.02], [5, 5.01, 5.02]) == pytest.approx(0.1)


def test_bland_altman_and_prediction_kappas():
    agreement = bland_altman_log([1, 2, 3], [1.1, 2.2, 3.3])
    assert agreement.ratio_bias == pytest.approx(1.1)
    assert agreement.ratio_lower == pytest.approx(1.1)
    boards = [[0, 0, 1, 1], [0, 0, 1, 1], [0, 1, 1, 1]]
    counts = np.array([[3, 0], [2, 1], [0, 3], [0, 3]])
    assert fleiss_kappa(boards) == pytest.approx(library_fleiss(counts), abs=1e-12)
    contingency = np.array([[1, 1], [0, 2]])
    assert cohen_kappa(boards[0], boards[2]) == pytest.approx(library_cohen(contingency).kappa)
