"""Credibility audit of the final results (DECISIONS.md D89-D91).

Run from the repository root (also run by run_pipeline.py as the "audit" stage):

    .venv\\Scripts\\python scripts/audit.py

Three parts, all DESCRIPTIVE: nothing here changes the frozen model selection,
the test results or the strategy result.

A. 2025 test diagnostics. Why were the models biased on the test race? The
   selected models are refitted on the training races exactly as in the test
   stage; the residuals are split by tyre age, by team and into ages inside /
   beyond the training range, and the bias expected from the change in wear
   rate alone is computed.
B. Leakage checks. Is any information from the test race used before or in
   the test evaluation?
C. Strategy constraint checks. Does the reported optimum obey every rule, and
   is it really the best strategy? An independent exhaustive search re-derives it.

Writes reports/audit_checks.csv (one row per check: passed / failed / info),
reports/audit_2025_*.csv and reports/figures/audit_*.png. Raises an error if
any check fails, so the pipeline stops.
"""

from __future__ import annotations

import datetime
import json
import logging
import subprocess
import sys
from itertools import product
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from tyredeg.config import load_config  # noqa: E402
from tyredeg.preparation import prepare_laps  # noqa: E402
from tyredeg.validation import (  # noqa: E402
    RACE_COLUMN,
    STINT_COLUMN,
    binned_residuals,
    candidate_models,
    compute_metrics,
    fit_on,
    leave_one_race_out,
    leftover_fuel_effect,
    load_selection,
    predict_held_out,
)

REPORTS = REPO_ROOT / "reports"
FIGURES = REPORTS / "figures"
# Tyre-age bins for the residual analysis [laps]; the last bin holds ages beyond
# the training range (the training maximum is 41 laps).
AGE_BIN_EDGES = [0, 10, 20, 30, 41, 60]
# Agreement required between independently recomputed and reported values [s].
TOLERANCE_S = 1e-6

logger = logging.getLogger("audit")


def check(rows, name, passed, detail):
    """Record one check; ``passed`` is True, False or None (information only)."""
    status = "info" if passed is None else ("passed" if passed else "FAILED")
    rows.append({"check": name, "status": status, "detail": detail})
    logger.info("[%s] %s: %s", status, name, detail)


# ---------------------------------------------------------------------------
# A. 2025 test diagnostics
# ---------------------------------------------------------------------------
def anchor_mean_degradation(model, laps, anchor_laps):
    """Mean d(age) over the first ``anchor_laps`` laps of each stint (as in D49)."""
    ordered = laps.sort_values([STINT_COLUMN, "LapNumber"], kind="stable")
    anchors = ordered.groupby(STINT_COLUMN, sort=False).head(anchor_laps)
    values = pd.Series(model.degradation(anchors["TyreLife"].to_numpy(float)), index=anchors.index)
    return values.groupby(anchors[STINT_COLUMN]).mean()


def wear_rate_bias(train_model, test_model, test_laps, scored, anchor_laps):
    """Bias [s/lap] expected if the ONLY difference were the degradation curve.

    Each prediction is anchored on its stint's first laps, so a wrong curve
    causes an error of [d_train(age) - d_train(anchor)] - [d_test(age) - d_test(anchor)].
    """
    anchor_train = anchor_mean_degradation(train_model, test_laps, anchor_laps)
    anchor_test = anchor_mean_degradation(test_model, test_laps, anchor_laps)
    ages = scored["TyreLife"].to_numpy(float)
    stints = scored[STINT_COLUMN]
    error = (train_model.degradation(ages) - anchor_train.loc[stints].to_numpy()) \
        - (test_model.degradation(ages) - anchor_test.loc[stints].to_numpy())
    return float(np.mean(error))


def anchor_lap_residual(test_model, test_laps, anchor_laps):
    """Mean of (actual - 2025 fit) over the anchor laps [s]; > 0 means they were slow.

    The 2025 fit includes each stint's own offset, so this measures how far the
    first laps of a stint (tyre warm-up, traffic after the stop) sit above the
    curve that describes the rest of the stint.
    """
    ordered = test_laps.sort_values([STINT_COLUMN, "LapNumber"], kind="stable")
    anchors = ordered.groupby(STINT_COLUMN, sort=False).head(anchor_laps)
    offsets = anchors[STINT_COLUMN].map(test_model.stint_offsets()).to_numpy(float)
    fitted = offsets + test_model.degradation(anchors["TyreLife"].to_numpy(float))
    return float(np.mean(anchors["FuelCorrectedTime"].to_numpy(float) - fitted))


def diagnose_test(config, rows):
    selection = load_selection(REPO_ROOT / config.validation.selection_file)["selection"]
    reported = pd.read_csv(REPO_ROOT / config.validation.test_results_file)
    train = prepare_laps(config, config.train_races).clean
    test = prepare_laps(config, config.test_races).clean
    anchor = config.validation.anchor_laps
    summary, bins, teams, curves = [], [], [], {}
    for compound in config.pirelli_compounds:
        name = selection[compound]["selected"]
        spec = {s.name: s for s in candidate_models(compound, config.models)}[name]
        train_c = train[train["PirelliCompound"] == compound]
        test_c = test[test["PirelliCompound"] == compound]
        model = fit_on(spec, train_c)
        scored = predict_held_out(model, test_c, anchor)
        metrics = compute_metrics(scored["actual"], scored["predicted"])

        # The recomputed test result must equal the one reported once (D55).
        saved = reported[(reported["compound"] == compound) & (reported["model"] == name)].iloc[0]
        same = abs(metrics["rmse"] - saved["rmse"]) < 1e-9 and abs(metrics["bias"] - saved["bias"]) < 1e-9
        check(rows, f"A1 {compound}: test result reproduced", same,
              f"RMSE {metrics['rmse']:.4f} s, bias {metrics['bias']:+.4f} s/lap (reported "
              f"{saved['rmse']:.4f}, {saved['bias']:+.4f})")

        # Same model form fitted on the test race itself: the 2025 degradation curve.
        test_model = fit_on(spec, test_c)
        expected = wear_rate_bias(model, test_model, test_c, scored, anchor)
        max_train_age = float(train_c["TyreLife"].max())
        inside = scored["TyreLife"] <= max_train_age
        inside_metrics = compute_metrics(scored.loc[inside, "actual"], scored.loc[inside, "predicted"])
        rate_train = float(model.params()["coefficients"][0])
        rate_test = float(test_model.params()["coefficients"][0])
        summary.append({
            "compound": compound, "model": name, "n_scored": metrics["n"],
            "rmse": metrics["rmse"], "bias": metrics["bias"],
            "rate_train_s_per_lap": rate_train, "rate_2025_s_per_lap": rate_test,
            "bias_expected_from_rate_change": expected,
            # Exact split: the rest of the bias comes from the anchor laps (see D90).
            "bias_from_anchor_laps": metrics["bias"] - expected,
            "anchor_laps_mean_residual_2025": anchor_lap_residual(test_model, test_c, anchor),
            "share_of_bias_explained": expected / metrics["bias"] if metrics["bias"] else float("nan"),
            "max_training_age": max_train_age,
            "laps_beyond_training_age": int((~inside).sum()),
            "rmse_within_training_ages": inside_metrics["rmse"],
            "bias_within_training_ages": inside_metrics["bias"],
        })
        check(rows, f"A2 {compound}: bias explained by the lower 2025 wear rate", None,
              f"rate {rate_train:.4f} (train) vs {rate_test:.4f} s/lap (2025); expected bias "
              f"{expected:+.3f} of the observed {metrics['bias']:+.3f} s/lap (rest {metrics['bias'] - expected:+.3f} "
              f"from the anchor laps, which sat {anchor_lap_residual(test_model, test_c, anchor):+.3f} s "
              f"from the 2025 curve); "
              f"{int((~inside).sum())} laps beyond the training age {max_train_age:.0f}; bias within "
              f"training ages {inside_metrics['bias']:+.3f} s/lap")

        table = binned_residuals(scored["TyreLife"], scored["residual"], AGE_BIN_EDGES)
        bins.append(table.assign(compound=compound))
        stint_team = test_c.drop_duplicates(STINT_COLUMN).set_index(STINT_COLUMN)["Team"]
        by_team = scored.assign(Team=stint_team.loc[scored[STINT_COLUMN]].to_numpy())
        for team, group in by_team.groupby("Team"):
            teams.append({"compound": compound, "team": team, "n": len(group),
                          "bias": float(group["residual"].mean())})
        curves[compound] = (model, test_model, train_c, test_c)

    # Fuel correction on the test race alone (D54 method; descriptive only).
    fuel = leftover_fuel_effect(test, list(config.pirelli_compounds), config.models.bootstrap_resamples,
                                config.models.confidence_level, config.random_seed)
    check(rows, "A3 leftover fuel effect on the 2025 race", None,
          f"{fuel.estimate:+.4f} s/lap, 95% CI [{fuel.lower:+.4f}, {fuel.upper:+.4f}] "
          f"(0 = the fuel correction fits 2025 too)")
    team_table = pd.DataFrame(teams)
    positive = int((team_table["bias"] > 0).sum())
    check(rows, "A4 bias by team", None,
          f"{positive} of {len(team_table)} team/compound groups have a positive bias "
          f"(a common cause, not one car)")

    pd.DataFrame(summary).to_csv(REPORTS / "audit_2025_summary.csv", index=False)
    pd.concat(bins, ignore_index=True).to_csv(REPORTS / "audit_2025_bias_by_age.csv", index=False)
    team_table.to_csv(REPORTS / "audit_2025_bias_by_team.csv", index=False)
    plot_bias_by_age(pd.concat(bins, ignore_index=True))
    plot_train_vs_test(curves)
    return pd.DataFrame(summary)


def binned_degradation(model, laps):
    """Mean of (lap time - stint offset) per integer tyre age: the observed degradation."""
    offsets = model.stint_offsets()
    adjusted = laps["FuelCorrectedTime"].to_numpy(float) - laps[STINT_COLUMN].map(offsets).to_numpy(float)
    table = pd.DataFrame({"age": laps["TyreLife"].to_numpy(float), "d": adjusted})
    grouped = table.groupby("age")["d"].agg(["mean", "count"]).reset_index()
    return grouped[grouped["count"] >= 5]


def plot_train_vs_test(curves):
    fig, axes = plt.subplots(1, len(curves), figsize=(5.5 * len(curves), 4), sharey=True)
    for ax, (compound, (model, test_model, train_c, test_c)) in zip(np.atleast_1d(axes), curves.items()):
        for label, fitted, laps, colour in (("training 2022-24", model, train_c, "tab:blue"),
                                            ("test 2025", test_model, test_c, "tab:red")):
            data = binned_degradation(fitted, laps)
            ax.plot(data["age"], data["mean"], "o", ms=3, color=colour, alpha=0.6)
            ages = np.linspace(0, laps["TyreLife"].max(), 100)
            ax.plot(ages, fitted.degradation(ages), color=colour, label=f"{label} (fit)")
        ax.set_title(f"{compound}: degradation, training vs 2025")
        ax.set_xlabel("tyre age [laps]")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    np.atleast_1d(axes)[0].set_ylabel("lap time - stint offset [s]")
    fig.tight_layout()
    fig.savefig(FIGURES / "audit_2025_degradation_train_vs_test.png", dpi=150)
    plt.close(fig)


def plot_bias_by_age(bins):
    fig, ax = plt.subplots(figsize=(7, 4))
    for offset, (compound, group) in zip((-0.8, 0.8), bins.groupby("compound")):
        centres = (group["bin_low"] + group["bin_high"]) / 2 + offset
        ax.errorbar(centres, group["mean"], yerr=2 * group["se"], fmt="o-", capsize=3, label=compound)
    ax.axhline(0, color="black", linewidth=1)
    ax.axvline(41, color="grey", linestyle="--", label="training max age (41)")
    ax.set_xlabel("tyre age bin centre [laps]")
    ax.set_ylabel("mean residual, predicted - actual [s] (+/- 2 SE)")
    ax.set_title("2025 test: bias by tyre age")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "audit_2025_bias_by_age.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# B. Leakage checks
# ---------------------------------------------------------------------------
def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def lap_keys(laps):
    return set(zip(laps[RACE_COLUMN], laps["Driver"], laps["LapNumber"]))


def check_leakage(config, rows):
    train_years = {race.year for race in config.train_races}
    test_years = {race.year for race in config.test_races}
    check(rows, "B1 train and test races are disjoint", not train_years & test_years,
          f"train {sorted(train_years)}, test {sorted(test_years)}")

    saved = load_selection(REPO_ROOT / config.validation.selection_file)
    used = " ".join(saved.get("training_races", []))
    check(rows, "B2 selection was fitted without the test race",
          all(str(year) not in used for year in test_years), f"training races: {saved.get('training_races')}")

    log_lines = (REPO_ROOT / config.validation.test_run_log).read_text(encoding="utf-8").splitlines()
    first_test = datetime.datetime.fromisoformat(log_lines[0].split()[0])
    selected = datetime.datetime.fromisoformat(saved["created_utc"])
    check(rows, "B3 selection frozen before the first test run", selected < first_test,
          f"selection {saved['created_utc']}, first test run {log_lines[0].split()[0]}, "
          f"{len(log_lines)} test run(s) logged")

    added = git("log", "--diff-filter=A", "--format=%H", "--", str(config.validation.test_results_file))
    if added and added.split():
        test_commit = added.split()[-1]
        ancestor = git("merge-base", "--is-ancestor", saved["git_commit"], test_commit) is not None
        check(rows, "B4 selection committed before the test results (git history)", ancestor,
              f"selection commit {saved['git_commit'][:7]} is an ancestor of {test_commit[:7]}")
    else:
        check(rows, "B4 selection committed before the test results (git history)", None,
              "skipped: git history not available")

    # Cleaning and fuel correction must treat every race on its own: a statistic
    # computed over several races would let the test race shape the training data.
    together = prepare_laps(config, config.races).clean
    independent = True
    for race in config.races:
        alone = prepare_laps(config, [race]).clean
        joint = together[together["Year"] == race.year]
        independent &= lap_keys(alone) == lap_keys(joint) and np.allclose(
            alone.sort_values(["Driver", "LapNumber"])["FuelCorrectedTime"].to_numpy(),
            joint.sort_values(["Driver", "LapNumber"])["FuelCorrectedTime"].to_numpy())
    check(rows, "B5 cleaning and fuel correction are per race", independent,
          "each race prepared alone gives the same clean laps and times as all races together")

    train = prepare_laps(config, config.train_races).clean
    test_ids = set(prepare_laps(config, config.test_races).clean[RACE_COLUMN])
    folds = leave_one_race_out(train[RACE_COLUMN])
    clean_folds = all(not set(f.train_races) & set(f.test_races) for f in folds)
    check(rows, "B6 CV data and folds exclude the test race",
          not set(train[RACE_COLUMN]) & test_ids and clean_folds,
          f"{len(folds)} folds over {sorted(set(train[RACE_COLUMN]))}")

    # Anchor laps set each held-out stint's base pace and must never be scored.
    compound = config.pirelli_compounds[0]
    spec = candidate_models(compound, config.models)[1]
    laps_c = train[train["PirelliCompound"] == compound]
    scored = predict_held_out(fit_on(spec, laps_c), laps_c, config.validation.anchor_laps)
    first_laps = laps_c.sort_values("LapNumber").groupby(STINT_COLUMN).head(config.validation.anchor_laps)
    overlap = lap_keys_scored(scored) & set(zip(first_laps[STINT_COLUMN], first_laps["LapNumber"]))
    check(rows, "B7 anchor laps are never scored", not overlap,
          f"{len(scored)} scored laps, {len(first_laps)} anchor laps, overlap {len(overlap)}")

    # k_fuel was chosen in Phase 2 from the training data (D22). Re-estimate the
    # leftover fuel effect on the training races only (D54 method).
    fuel = leftover_fuel_effect(train, list(config.pirelli_compounds), config.models.bootstrap_resamples,
                                config.models.confidence_level, config.random_seed)
    check(rows, "B8 k_fuel consistent with the training races alone", not fuel.flagged,
          f"leftover {fuel.estimate:+.4f} s/lap, 95% CI [{fuel.lower:+.4f}, {fuel.upper:+.4f}]: "
          f"training data imply k_fuel = {config.k_fuel - fuel.estimate:.4f} (config {config.k_fuel})")
    check(rows, "B9 strategy refit includes 2025 (by design, after the test)", None,
          "D56/D58: the strategy models and pit loss use 2023-2025; the strategy is never scored "
          "against the test race, so this is not validation leakage")


def lap_keys_scored(scored):
    return set(zip(scored[STINT_COLUMN], scored["LapNumber"]))


# ---------------------------------------------------------------------------
# C. Strategy constraint checks
# ---------------------------------------------------------------------------
def stint_time_table(models, total_laps):
    """table[c][n] = time of an n-lap stint on new tyres of compound c [s], by explicit sums."""
    table = {}
    for compound, cm in models.items():
        times = np.full(total_laps + 1, np.inf)
        times[0] = 0.0
        for n in range(1, min(cm.max_stint_laps, total_laps) + 1):
            ages = np.arange(1.0, n + 1.0)
            times[n] = n * cm.base_time + float(np.sum(cm.model.degradation(ages)))
        table[compound] = times  # inf = longer than the stint limit (infeasible)
    return table


def best_by_enumeration(table, compounds, total_laps, stops, pit_loss, fuel_total):
    """Fastest race with ``stops`` stops by trying every stint-length combination."""
    best = (np.inf, None, None)
    for sequence in product(compounds, repeat=stops + 1):
        if len(set(sequence)) < 2:
            continue  # a dry race must use two different compounds
        grids = np.meshgrid(*[np.arange(1, total_laps) for _ in range(stops)], indexing="ij")
        last = total_laps - sum(grids)
        valid = last >= 1
        time = np.zeros(last.shape)
        for compound, lengths in zip(sequence, list(grids) + [np.clip(last, 0, total_laps)]):
            time = time + table[compound][lengths]
        time = np.where(valid, time + stops * pit_loss - fuel_total, np.inf)
        position = np.unravel_index(np.argmin(time), time.shape)
        if time[position] < best[0]:
            lengths = [int(g[position]) for g in grids] + [int(last[position])]
            best = (float(time[position]), sequence, lengths)
    return best


def check_strategy(config, rows):
    import optimise_strategy

    models, total_laps, pit_loss, _, _, _, _ = optimise_strategy.build_inputs(config)
    k_fuel = config.k_fuel
    fuel_total = k_fuel * total_laps * (total_laps - 1) / 2.0 if config.strategy.add_fuel_effect else 0.0
    table = stint_time_table(models, total_laps)
    ranking = pd.read_csv(REPORTS / "phase6_strategy_ranking.csv")

    problems = []
    for row in ranking.itertuples():
        sequence = row.strategy.split(" -> ")
        lengths = [int(n) for n in str(row.stint_lengths).split("+")]
        pits = [int(p) for p in str(row.pit_laps).split(" & ")]
        if sum(lengths) != total_laps:
            problems.append(f"{row.strategy}: stints sum to {sum(lengths)}")
        if len(set(sequence)) < 2:
            problems.append(f"{row.strategy}: one compound only")
        if pits != list(np.cumsum(lengths)[:-1]):
            problems.append(f"{row.strategy}: pit laps {pits} do not match stints {lengths}")
        for compound, n in zip(sequence, lengths):
            if not 1 <= n <= models[compound].max_stint_laps:
                problems.append(f"{row.strategy}: {n}-lap {compound} stint breaks its limit")
        recomputed = sum(table[c][n] for c, n in zip(sequence, lengths)) + len(pits) * pit_loss - fuel_total
        if abs(recomputed - row.total_time) > TOLERANCE_S:
            problems.append(f"{row.strategy}: time {row.total_time:.6f} vs recomputed {recomputed:.6f}")
    limits = {c: m.max_stint_laps for c, m in models.items()}
    check(rows, "C1 every ranked strategy obeys the rules", not problems,
          "; ".join(problems) if problems else
          f"{len(ranking)} strategies: {total_laps} laps, >= 2 compounds, stint limits {limits}, "
          f"pit loss {pit_loss:.2f} s per stop, times recomputed lap by lap within {TOLERANCE_S} s")

    for stops in (1, 2):
        time, sequence, lengths = best_by_enumeration(table, list(models), total_laps, stops,
                                                      pit_loss, fuel_total)
        reported = ranking[ranking["stops"] == f"{stops}-stop"]["total_time"].min()
        check(rows, f"C{stops + 1} exhaustive search confirms the best {stops}-stop",
              abs(time - reported) < TOLERANCE_S,
              f"{' -> '.join(sequence)} stints {lengths}: {time:.3f} s (reported {reported:.3f} s)")
    time, sequence, lengths = best_by_enumeration(table, list(models), total_laps, 3, pit_loss, fuel_total)
    best = ranking["total_time"].min()
    check(rows, "C4 three stops are not faster (outside the modelled strategies)", time > best - TOLERANCE_S,
          f"best 3-stop {' -> '.join(sequence)} stints {lengths}: {time:.3f} s vs best {best:.3f} s")


# ---------------------------------------------------------------------------
def main(config=None):
    """Run all checks; raise RuntimeError if any fails (outputs are written first)."""
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    if config is None:
        config = load_config(REPO_ROOT / "config.yaml")
    REPORTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    rows = []
    diagnose_test(config, rows)
    check_leakage(config, rows)
    check_strategy(config, rows)
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "audit_checks.csv", index=False)
    failed = table[table["status"] == "FAILED"]
    if not failed.empty:
        raise RuntimeError(f"{len(failed)} audit check(s) failed: {', '.join(failed['check'])}")
    logger.info("Audit: %d checks passed, %d information rows.", (table["status"] == "passed").sum(),
                (table["status"] == "info").sum())


if __name__ == "__main__":
    main()
