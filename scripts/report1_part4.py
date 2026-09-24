"""Rebuild Report No. 1 statistics from the published 27 session values.

The source CSV is a frozen,
public export of those 27 corrected sessions; no unpublished campaign is read.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import median, quantiles
from typing import TYPE_CHECKING

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import statsmodels
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.oneway import anova_oneway

if TYPE_CHECKING:
    from matplotlib.figure import Figure

from signal_bench.analysis.report1_tests import (
    bland_altman_log,
    cohen_kappa,
    exact_permutation_pair,
    fleiss_kappa,
    games_howell,
    welch_anova,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/report1-statistics"
BOARDS = ("f401re", "nano33", "esp32s3")
TASKS = ("kws", "ic", "ad")
PAIRS = ((0, 1), (0, 2), (1, 2))
NAMES = {"f401re": "F401RE", "nano33": "Nano 33", "esp32s3": "ESP32-S3"}
TASK_NAMES = {"kws": "Keyword spotting", "ic": "Image classification", "ad": "Anomaly detection"}
SESOI = 0.10
KWS_FULL = {
    "f401re": "019f1b03-be72-74b2-8498-bacb755ae407",
    "nano33": "019f1c3e-bede-7e12-8383-c35fe1f5aa8f",
    "esp32s3": "019f1b19-4353-7943-9502-72e16d1e74eb",
}
COLORS = {"f401re": "#c96b36", "nano33": "#0e9e84", "esp32s3": "#587bc5"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_sessions() -> list[dict]:
    rows = read_csv(SOURCE / "sessions.csv")
    assert len(rows) == 27 and len({row["run_id"] for row in rows}) == 27
    for row in rows:
        for key in ("ina_mwh_per_1000", "latency_ms"):
            row[key] = float(row[key])
            assert row[key] > 0
        row["fnb_mwh_per_1000"] = (
            float(row["fnb_mwh_per_1000"]) if row["fnb_mwh_per_1000"] else None
        )
    counts = {
        (task, board): sum(row["task"] == task and row["board"] == board for row in rows)
        for task in TASKS
        for board in BOARDS
    }
    assert set(counts.values()) == {3}
    assert sum(row["fnb_mwh_per_1000"] is not None for row in rows) == 15
    return rows


def predictions() -> list[dict]:
    embedded = read_csv(SOURCE / "embedded-predictions.csv")
    by_task = defaultdict(lambda: defaultdict(dict))
    for row in embedded:
        by_task[row["task"]][row["board"]][int(row["sample_index"])] = row["output"]
    result = []
    for task in TASKS:
        common = sorted(set.intersection(*(set(by_task[task][board]) for board in BOARDS)))
        assert len(common) == 12
        matrix = [[by_task[task][board][index] for index in common] for board in BOARDS]
        matches = sum(len({matrix[j][i] for j in range(3)}) == 1 for i in range(len(common)))
        row = {
            "task": task,
            "source": "embedded",
            "inputs": len(common),
            "matches": matches,
            "fleiss_kappa": None,
            "cohen_f401_nano": None,
            "cohen_f401_esp": None,
            "cohen_nano_esp": None,
            "max_absolute_score_difference": None,
            "max_relative_score_difference": None,
        }
        if task == "ad":
            differences = [
                (abs(float(matrix[a][i]) - float(matrix[b][i])),
                 abs(float(matrix[a][i]) - float(matrix[b][i])) /
                 max(abs(float(matrix[a][i])), abs(float(matrix[b][i]))))
                for i in range(len(common)) for a, b in PAIRS
            ]
            row["max_absolute_score_difference"] = max(value[0] for value in differences)
            row["max_relative_score_difference"] = max(value[1] for value in differences)
        if task != "ad":
            row.update(
                fleiss_kappa=fleiss_kappa(matrix),
                cohen_f401_nano=cohen_kappa(matrix[0], matrix[1]),
                cohen_f401_esp=cohen_kappa(matrix[0], matrix[2]),
                cohen_nano_esp=cohen_kappa(matrix[1], matrix[2]),
            )
        result.append(row)
    full = {}
    for board, run_id in KWS_FULL.items():
        path = ROOT / "data/full-eval/a01" / run_id / "predictions.csv"
        data = read_csv(path)
        full[board] = {int(row["sample_index"]): int(row["prediction"]) for row in data}
        assert len(full[board]) == 4890
    indices = sorted(set.intersection(*(set(full[board]) for board in BOARDS)))
    assert len(indices) == 4890
    matrix = [[full[board][i] for i in indices] for board in BOARDS]
    matches = sum(len({matrix[j][i] for j in range(3)}) == 1 for i in range(len(indices)))
    result.append(
        {
            "task": "kws",
            "source": "retained full evaluation",
            "inputs": 4890,
            "matches": matches,
            "fleiss_kappa": fleiss_kappa(matrix),
            "cohen_f401_nano": cohen_kappa(matrix[0], matrix[1]),
            "cohen_f401_esp": cohen_kappa(matrix[0], matrix[2]),
            "cohen_nano_esp": cohen_kappa(matrix[1], matrix[2]),
            "max_absolute_score_difference": None,
            "max_relative_score_difference": None,
        }
    )
    return result


def analyze(sessions: list[dict]) -> tuple[list[dict], list[dict], dict, list[dict]]:
    cells = defaultdict(list)
    for row in sessions:
        cells[row["task"], row["board"]].append(row)
    omnibus, pairwise = [], []
    for task in TASKS:
        for metric, field in (("latency", "latency_ms"), ("energy", "ina_mwh_per_1000")):
            arrays = [[row[field] for row in cells[task, board]] for board in BOARDS]
            omni = welch_anova(arrays)
            omnibus.append(
                {
                    "task": task,
                    "metric": metric,
                    "f": omni.f if omni else None,
                    "df1": omni.df1 if omni else None,
                    "df2": omni.df2 if omni else None,
                    "p": omni.p if omni else None,
                    "omega_squared": omni.omega_squared if omni else None,
                }
            )
            for i, j in PAIRS:
                test = games_howell(arrays[i], arrays[j])
                low, high = (test.lower, test.upper) if test else (None, None)
                fixed_groups = test is None and all(v == arrays[i][0] for v in arrays[i]) and all(
                    v == arrays[j][0] for v in arrays[j]
                )
                observed_ratio = math.exp(
                    sum(math.log(v) for v in arrays[i]) / len(arrays[i])
                    - sum(math.log(v) for v in arrays[j]) / len(arrays[j])
                )
                sesoi = (
                    "beyond ±10% in every session"
                    if fixed_groups and (observed_ratio < 0.9 or observed_ratio > 1.1)
                    else "not estimable"
                    if test is None
                    else "beyond 10%"
                    if high < 0.9 or low > 1.1
                    else "inside 10%"
                    if low >= 0.9 and high <= 1.1
                    else "straddles 10%"
                )
                pairwise.append(
                    {
                        "task": task,
                        "metric": metric,
                        "first": BOARDS[i],
                        "second": BOARDS[j],
                        "n_first": 3,
                        "n_second": 3,
                        "ratio": test.ratio if test else observed_ratio,
                        "lower": low,
                        "upper": high,
                        "p_adjusted": test.p_adjusted if test else None,
                        "hedges_g": test.hedges_g if test else None,
                        "permutation_p": exact_permutation_pair(arrays[i], arrays[j]),
                        "sesoi": sesoi,
                    }
                )
    paired = [row for row in sessions if row["fnb_mwh_per_1000"] is not None]
    ba = bland_altman_log(
        [row["ina_mwh_per_1000"] for row in paired], [row["fnb_mwh_per_1000"] for row in paired]
    )
    agreement = {
        "n": ba.n,
        "log_bias": ba.log_bias,
        "log_lower": ba.log_lower,
        "log_upper": ba.log_upper,
        "ratio_bias": ba.ratio_bias,
        "ratio_lower": ba.ratio_lower,
        "ratio_upper": ba.ratio_upper,
    }
    ba_points = [
        {
            "run_id": row["run_id"],
            "task": row["task"],
            "board": row["board"],
            "log_mean": (math.log(row["ina_mwh_per_1000"]) + math.log(row["fnb_mwh_per_1000"])) / 2,
            "log_difference": math.log(row["fnb_mwh_per_1000"] / row["ina_mwh_per_1000"]),
        }
        for row in paired
    ]
    return omnibus, pairwise, agreement, ba_points


def cell_summaries(sessions: list[dict]) -> list[dict]:
    rows = []
    for task in TASKS:
        for board in BOARDS:
            for metric, field in (("latency", "latency_ms"), ("energy", "ina_mwh_per_1000")):
                values = sorted(
                    row[field] for row in sessions if row["task"] == task and row["board"] == board
                )
                q1, _, q3 = quantiles(values, n=4, method="inclusive")
                rows.append(
                    {
                        "task": task,
                        "board": board,
                        "metric": metric,
                        "n": len(values),
                        "median": median(values),
                        "q1": q1,
                        "q3": q3,
                        "iqr": q3 - q1,
                    }
                )
    return rows


def crosscheck_statsmodels(sessions: list[dict], omnibus: list[dict], pairs: list[dict]) -> dict:
    count_omnibus = count_pairs = 0
    max_f = max_df = max_ci = max_p = 0.0
    for task in TASKS:
        for metric, field in (("energy", "ina_mwh_per_1000"), ("latency", "latency_ms")):
            groups = [
                np.log(
                    [
                        row[field]
                        for row in sessions
                        if row["task"] == task and row["board"] == board
                    ]
                )
                for board in BOARDS
            ]
            own = next(row for row in omnibus if row["task"] == task and row["metric"] == metric)
            if own["f"] is not None:
                reference = anova_oneway(groups, use_var="unequal")
                max_f = max(max_f, abs(own["f"] - reference.statistic) / reference.statistic)
                max_df = max(max_df, abs(own["df2"] - reference.df[1]))
                max_p = max(max_p, abs(own["p"] - reference.pvalue))
                count_omnibus += 1
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                reference_pairs = pairwise_tukeyhsd(
                    np.concatenate(groups), np.repeat(BOARDS, 3), use_var="unequal"
                )
            library_pairs = list(combinations(list(reference_pairs.groupsunique), 2))
            indices = {frozenset(names): i for i, names in enumerate(library_pairs)}
            for row in (
                p
                for p in pairs
                if p["task"] == task and p["metric"] == metric and p["p_adjusted"] is not None
            ):
                index = indices[frozenset((row["first"], row["second"]))]
                order = library_pairs[index]
                sign = 1 if order == (row["first"], row["second"]) else -1
                interval = reference_pairs.confint[index]
                ratio = math.exp(-sign * reference_pairs.meandiffs[index])
                lower = math.exp(-sign * (interval[1] if sign == 1 else interval[0]))
                upper = math.exp(-sign * (interval[0] if sign == 1 else interval[1]))
                max_ci = max(
                    max_ci,
                    abs(row["ratio"] - ratio),
                    abs(row["lower"] - lower),
                    abs(row["upper"] - upper),
                )
                max_p = max(max_p, abs(row["p_adjusted"] - reference_pairs.pvalues[index]))
                count_pairs += 1
    assert count_omnibus == 5 and count_pairs == 17
    assert max_f < 1e-8 and max_df < 1e-8 and max_ci < 1e-7 and max_p < 1e-7
    return {
        "library": "statsmodels",
        "version": statsmodels.__version__,
        "omnibus": count_omnibus,
        "pairs": count_pairs,
        "max_relative_f": max_f,
        "max_df2": max_df,
        "max_ratio_ci": max_ci,
        "max_p": max_p,
    }


def plot(
    out: Path, sessions: list[dict], pairs: list[dict], agreement: dict, ba_points: list[dict]
) -> None:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
        }
    )
    for metric, field, unit in (
        ("latency", "latency_ms", "Milliseconds per inference"),
        ("energy", "ina_mwh_per_1000", "mWh per 1,000 inferences"),
    ):
        fig, ax = plt.subplots(figsize=(10, 6.4), layout="constrained")
        labels = []
        for ti, task in enumerate(TASKS):
            for bi, board in enumerate(BOARDS):
                y = 8 - ti * 3 - bi
                vals = [r[field] for r in sessions if r["task"] == task and r["board"] == board]
                for k, v in enumerate(vals):
                    ax.scatter(
                        v,
                        y + (k - 1) * 0.14,
                        s=65,
                        color=COLORS[board],
                        edgecolor="white",
                        linewidth=0.7,
                    )
                labels.append((y, f"{TASK_NAMES[task]}  ·  {NAMES[board]}"))
        ax.set_yticks([y for y, _ in labels], [label for _, label in labels])
        ax.set_xscale("log")
        ax.set_xlabel(unit + " (log scale)")
        ax.set_title(f"Published sessions: {metric}", loc="left", fontweight="bold")
        ax.grid(axis="x", alpha=0.2)
        save_figure(fig, out, f"{metric}_session_strip")

        fig, ax = plt.subplots(figsize=(10, 9), layout="constrained")
        these = [r for r in pairs if r["metric"] == metric]
        for index, row in enumerate(these):
            y = len(these) - 1 - index
            if row["ratio"] is None:
                ax.text(1, y, "not estimable", ha="center", va="center", fontsize=9)
            elif row["lower"] is None:
                ax.scatter(row["ratio"], y, marker="D", s=52, color=COLORS[row["first"]])
                ax.annotate("0.694, no interval", (row["ratio"], y),
                            xytext=(8, 0), textcoords="offset points", va="center", fontsize=8)
            else:
                x = row["ratio"]
                ax.errorbar(
                    x,
                    y,
                    xerr=[[x - row["lower"]], [row["upper"] - x]],
                    fmt="o",
                    capsize=3,
                    color=COLORS[row["first"]],
                    markersize=6,
                )
        ax.axvspan(0.9, 1.1, color="#86cab3", alpha=0.25, label="Within 10% of 1")
        ax.axvline(1, color="#526070", lw=1)
        ax.set_yticks(
            range(len(these) - 1, -1, -1),
            [f"{TASK_NAMES[r['task']]}: {NAMES[r['first']]} / {NAMES[r['second']]}" for r in these],
        )
        ax.set_xscale("log")
        ax.set_xlabel("Ratio of geometric means (log scale)")
        ax.set_title(f"Board ratios: {metric}", loc="left", fontweight="bold")
        ax.legend(loc="lower right", frameon=False)
        ax.grid(axis="x", alpha=0.2)
        save_figure(fig, out, f"{metric}_ratio_forest")

    fig, ax = plt.subplots(figsize=(10, 6.3), layout="constrained")
    for board in BOARDS:
        subset = [p for p in ba_points if p["board"] == board]
        ax.scatter(
            [p["log_mean"] for p in subset],
            [100 * (math.exp(p["log_difference"]) - 1) for p in subset],
            s=65,
            color=COLORS[board],
            label=NAMES[board],
        )
    for key, label, style in (
        ("ratio_bias", "Mean bias", "-"),
        ("ratio_lower", "Lower agreement limit", "--"),
        ("ratio_upper", "Upper agreement limit", "--"),
    ):
        ax.axhline(
            100 * (agreement[key] - 1), color="#3c536a", linestyle=style, lw=1.2, label=label
        )
    ax.set_xlabel("Log geometric mean energy of the two meters")
    ax.set_ylabel("FNB58 versus INA219 (%)")
    ax.set_title("Meter agreement across 15 paired sessions", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=2, fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    save_figure(fig, out, "meter_bland_altman")


def save_figure(fig: Figure, out: Path, stem: str) -> None:
    for mode, face, foreground in (("light", "#ffffff", "#172331"), ("dark", "#101820", "#edf3f8")):
        fig.set_facecolor(face)
        for ax in fig.axes:
            ax.set_facecolor(face)
            ax.title.set_color(foreground)
            ax._left_title.set_color(foreground)
            ax._right_title.set_color(foreground)
            ax.xaxis.label.set_color(foreground)
            ax.yaxis.label.set_color(foreground)
            ax.tick_params(colors=foreground)
            for item in ax.get_xticklabels() + ax.get_yticklabels():
                item.set_color(foreground)
            for spine in ax.spines.values():
                spine.set_color(foreground)
            legend = ax.get_legend()
            if legend is not None:
                legend.get_frame().set_facecolor(face)
                for item in legend.get_texts():
                    item.set_color(foreground)
            for item in ax.texts:
                item.set_color(foreground)
        svg = out / f"{stem}_{mode}.svg"
        fig.savefig(svg, facecolor=face, dpi=180)
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
        fig.savefig(out / f"{stem}_{mode}.png", facecolor=face, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "build/report1-statistics")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sessions = load_sessions()
    omnibus, pairs, agreement, points = analyze(sessions)
    pred = predictions()
    check = crosscheck_statsmodels(sessions, omnibus, pairs)
    write_csv(args.out / "cell-summaries.csv", cell_summaries(sessions))
    write_csv(args.out / "omnibus.csv", omnibus)
    write_csv(args.out / "pairwise.csv", pairs)
    write_csv(args.out / "prediction-agreement.csv", pred)
    write_csv(args.out / "meter-points.csv", points)
    (args.out / "meter-agreement.json").write_text(json.dumps(agreement, indent=2) + "\n")
    (args.out / "library-crosscheck.json").write_text(json.dumps(check, indent=2) + "\n")
    plot(args.out, sessions, pairs, agreement, points)
    print(
        f"Report No. 1 Parts IV and V rebuilt: {len(sessions)} sessions, {len(pairs)} pairs, "
        f"{agreement['n']} paired meters, {len(list(args.out.glob('*.png')))} PNG figures"
    )


if __name__ == "__main__":
    main()
