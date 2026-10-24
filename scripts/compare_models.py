"""Phase 5 model comparison in two stages (DECISIONS.md D47-D55).

Stage 1 - cross-validation (training races ONLY; the test race is never loaded):

    .venv\\Scripts\\python scripts/compare_models.py --stage cv

  writes reports/phase5_cv_folds.csv, phase5_cv_summary.csv,
  phase5_compound_ranking.csv, phase5_residual_bins.csv,
  phase5_fuel_diagnostic.csv, figures/phase5_*.png and the frozen model
  selection reports/model_selection.json.

Stage 2 - final test (run ONCE, after stage 1):

    .venv\\Scripts\\python scripts/compare_models.py --stage test

  refuses to run without model_selection.json, refuses to repeat unless
  --force is given (every run is logged in reports/test_runs.log), fits the
  SELECTED models on all training races and scores the test race(s).
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tyredeg.config import load_config  # noqa: E402
from tyredeg.models.common import check_non_negative  # noqa: E402
from tyredeg.models.polynomial import PolynomialDegradationModel  # noqa: E402
from tyredeg.preparation import prepare_laps  # noqa: E402
from tyredeg.validation import (  # noqa: E402
    AGE_COLUMN,
    BASELINE_NAME,
    LAP_COLUMN,
    RACE_COLUMN,
    binned_residuals,
    candidate_models,
    check_monotonic,
    compute_metrics,
    cross_validate,
    fit_on,
    guard_cv_rerun,
    guard_test_run,
    leave_one_race_out,
    leftover_fuel_effect,
    load_selection,
    predict_held_out,
    rank_compounds,
    select_models,
    summarize_folds,
    write_selection,
)

REPORTS = REPO_ROOT / "reports"
FIGURES = REPORTS / "figures"
AGE_BINS = [0, 5, 10, 15, 20, 25, 30, 35, 45]
LAP_BINS = [0, 10, 20, 30, 40, 50, 60, 70]


def git_commit():
    """Current git commit (recorded with the selection), or 'unknown'."""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# ---------------------------------------------------------------------------
# Stage 1: cross-validation on the training races
# ---------------------------------------------------------------------------
def physical_checks(spec, laps, config):
    """Fit a candidate on all training laps; non-negativity and monotonicity (D53)."""
    model = fit_on(spec, laps)
    max_age = float(laps[AGE_COLUMN].max())
    nonneg = check_non_negative(model.degradation, max_age,
                                config.models.negative_degradation_tolerance_s,
                                ages=np.arange(0.0, np.floor(max_age) + 1.0))
    mono = check_monotonic(model.degradation, max_age, config.validation.monotonic_tolerance_s)
    return {"model": spec.name, "min_degradation": nonneg.min_degradation_s,
            "non_negative_ok": not nonneg.violated, "largest_drop": mono.largest_drop_s,
            "drops_over_tolerance": mono.n_drops_over_tolerance, "monotonic_ok": mono.ok}, model


def run_cv(config, force=False):
    # After the test stage has run, the frozen selection must not be overwritten (C16).
    guard_cv_rerun(REPO_ROOT / config.validation.selection_file,
                   REPO_ROOT / config.validation.test_results_file, force)
    races = config.train_races
    assert all(race.role == "train" for race in races)
    print(f"Cross-validation on TRAINING races only: {[r.year for r in races]} (test race not loaded)")
    clean = prepare_laps(config, races).clean
    test_years = {race.year for race in config.test_races}
    assert not set(clean["Year"]) & test_years, "a test race leaked into the CV data"

    fold_tables, summaries, residual_rows, rates, curves = [], [], [], [], {}
    selection = {}
    for compound in config.pirelli_compounds:
        laps = clean[clean["PirelliCompound"] == compound]
        folds = leave_one_race_out(laps[RACE_COLUMN])
        specs = candidate_models(compound, config.models)
        predictions = {}
        for spec in specs:
            table, scored = cross_validate(laps, spec, folds, config.validation.anchor_laps)
            fold_tables.append(table.assign(compound=compound))
            predictions[spec.name] = scored
        summary = summarize_folds(pd.concat([t for t in fold_tables if t["compound"].iloc[0] == compound]),
                                  config.validation.max_abs_bias_s_per_lap)
        checks, fitted = [], {}
        for spec in specs:
            if spec.name in set(summary["model"]):
                row, fitted[spec.name] = physical_checks(spec, laps, config)
                checks.append(row)
        summary = summary.merge(pd.DataFrame(checks), on="model")
        summary["accepted"] = (summary["family"] != "baseline") & summary["beats_baseline_all_folds"] \
            & summary["bias_ok"] & summary["non_negative_ok"] & summary["monotonic_ok"]
        summary.insert(0, "compound", compound)
        summaries.append(summary)

        complexity = {spec.name: spec.complexity for spec in specs}
        accepted = summary[summary["accepted"] | (summary["family"] == "baseline")]
        choice = select_models(accepted, complexity)
        choice["n_training_laps"] = int(len(laps))
        choice["n_training_stints"] = int(laps["StintId"].nunique())
        selection[compound] = choice
        curves[compound] = (laps, {name: fitted[name] for name in choice["family_winners"].values()})

        selected_predictions = predictions[choice["selected"]]
        for label, column, bins in (("tyre age", AGE_COLUMN, AGE_BINS), ("lap number", LAP_COLUMN, LAP_BINS)):
            binned = binned_residuals(selected_predictions[column], selected_predictions["residual"], bins)
            residual_rows.append(binned.assign(compound=compound, versus=label, model=choice["selected"]))

        linear = PolynomialDegradationModel(compound, degree=1).fit(
            laps[AGE_COLUMN], laps["FuelCorrectedTime"], laps["StintId"])
        boot = linear.bootstrap(config.models.bootstrap_resamples, config.models.confidence_level,
                                config.random_seed)
        rates.append({"compound": compound, "rate": float(linear.params()["coefficients"][0]),
                      "lower": float(boot.lower[0]), "upper": float(boot.upper[0]),
                      "bootstrap_se": float(boot.standard_errors[0]), "n_laps": int(len(laps))})

    fuel = leftover_fuel_effect(clean, list(config.pirelli_compounds), config.models.bootstrap_resamples,
                                config.models.confidence_level, config.random_seed)

    REPORTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    pd.concat(fold_tables).to_csv(REPORTS / "phase5_cv_folds.csv", index=False)
    summary_all = pd.concat(summaries)
    summary_all.to_csv(REPORTS / "phase5_cv_summary.csv", index=False)
    ranking = rank_compounds(pd.DataFrame(rates))
    ranking.to_csv(REPORTS / "phase5_compound_ranking.csv", index=False)
    residuals = pd.concat(residual_rows)
    residuals.to_csv(REPORTS / "phase5_residual_bins.csv", index=False)
    pd.DataFrame([fuel.__dict__]).to_csv(REPORTS / "phase5_fuel_diagnostic.csv", index=False)
    write_selection(config.validation.selection_file if config.validation.selection_file.is_absolute()
                    else REPO_ROOT / config.validation.selection_file, selection, {
                        "training_races": [f"{r.year} {r.event}" for r in races],
                        "test_races_not_used": [f"{r.year} {r.event}" for r in config.test_races],
                        "compounds": list(config.pirelli_compounds),
                        "anchor_laps": config.validation.anchor_laps,
                        "k_fuel": config.k_fuel,
                        "git_commit": git_commit(),
                        "rule": "best per family by mean LORO RMSE, then simplest accepted family "
                                "winner within one SE of the best (D48, D51)",
                    })
    plot_cv(summary_all)
    plot_curves(curves)
    plot_residuals(residuals)

    pd.set_option("display.width", 220)
    columns = ["model", "rmse_mean", "rmse_se", "mae_mean", "bias_mean", "bias_max_abs_fold",
               "beats_baseline_all_folds", "bias_ok", "monotonic_ok", "largest_drop", "accepted"]
    for compound in config.pirelli_compounds:
        print(f"\n=== {compound}: LORO CV summary (anchor {config.validation.anchor_laps} laps) ===")
        print(summary_all[summary_all["compound"] == compound][columns].round(4).to_string(index=False))
        print(f"selection: {selection[compound]}")
    print("\nCompound ranking (linear rate, training races):\n", ranking.round(5).to_string(index=False))
    print(f"\nLeftover fuel effect: {fuel.estimate:+.5f} s/lap, 95% CI [{fuel.lower:+.5f}, {fuel.upper:+.5f}], "
          f"flagged = {fuel.flagged} ({fuel.n_groups} driver-races)")


def plot_cv(summary):
    compounds = summary["compound"].unique()
    fig, axes = plt.subplots(1, len(compounds), figsize=(6.5 * len(compounds), 5), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, compound in zip(axes, compounds):
        rows = summary[summary["compound"] == compound]
        colours = ["grey" if f == "baseline" else ("tab:green" if ok else "tab:red")
                   for f, ok in zip(rows["family"], rows["accepted"])]
        ax.barh(rows["model"], rows["rmse_mean"], xerr=rows["rmse_se"], color=colours)
        ax.invert_yaxis()
        ax.set_title(f"{compound}: leave-one-race-out CV RMSE (green = accepted)")
        ax.set_xlabel("mean RMSE over held-out races [s]  (error bar = 1 SE)")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase5_cv_rmse.png", dpi=150)
    plt.close(fig)


def plot_curves(curves):
    fig, axes = plt.subplots(1, len(curves), figsize=(6.5 * len(curves), 4.5), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (compound, (laps, models)) in zip(axes, curves.items()):
        linear = PolynomialDegradationModel(compound, degree=1).fit(
            laps[AGE_COLUMN], laps["FuelCorrectedTime"], laps["StintId"])
        index = np.searchsorted(np.unique(laps["StintId"]), laps["StintId"])
        adjusted = laps["FuelCorrectedTime"].to_numpy() - linear._offsets[index]
        means = pd.Series(adjusted).groupby(laps[AGE_COLUMN].to_numpy()).mean()
        ax.plot(means.index, means.to_numpy(), "k.", label="data: mean per tyre age (offsets removed)")
        ages = np.arange(0.0, laps[AGE_COLUMN].max() + 1.0)
        for name, model in models.items():
            ax.plot(ages, model.degradation(ages), label=name)
        ax.set_title(f"{compound}: fitted degradation (family winners)")
        ax.set_xlabel("tyre age [laps]")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    axes[0].set_ylabel("degradation d [s]")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase5_degradation_curves.png", dpi=150)
    plt.close(fig)


def plot_residuals(residuals):
    compounds = residuals["compound"].unique()
    fig, axes = plt.subplots(len(compounds), 2, figsize=(11, 3.8 * len(compounds)), squeeze=False)
    for row, compound in enumerate(compounds):
        for col, versus in enumerate(("tyre age", "lap number")):
            data = residuals[(residuals["compound"] == compound) & (residuals["versus"] == versus)]
            centres = (data["bin_low"] + data["bin_high"]) / 2
            axes[row, col].errorbar(centres, data["mean"], yerr=2 * data["se"], fmt="o-", capsize=3)
            axes[row, col].axhline(0, color="grey", linewidth=0.8)
            axes[row, col].set_title(f"{compound}, {data['model'].iloc[0]}: CV residual vs {versus}")
            axes[row, col].set_xlabel(f"{versus} [laps]")
            axes[row, col].set_ylabel("mean residual +/- 2 SE [s]")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase5_residuals.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage 2: the single final test
# ---------------------------------------------------------------------------
def run_test(config, force):
    selection_path = REPO_ROOT / config.validation.selection_file
    results_path = REPO_ROOT / config.validation.test_results_file
    saved = load_selection(selection_path)
    guard_test_run(results_path, REPO_ROOT / config.validation.test_run_log, force)
    print(f"Model selection loaded from {selection_path.name} (created {saved['created_utc']}, "
          f"commit {saved['git_commit'][:7]}); it was fixed before this test run.")
    train = prepare_laps(config, config.train_races).clean
    test = prepare_laps(config, config.test_races).clean
    rows = []
    for compound in config.pirelli_compounds:
        choice = saved["selection"][compound]
        names = [BASELINE_NAME] + list(choice["family_winners"].values())
        specs = {spec.name: spec for spec in candidate_models(compound, config.models)}
        train_c = train[train["PirelliCompound"] == compound]
        test_c = test[test["PirelliCompound"] == compound]
        for name in names:
            scored = predict_held_out(fit_on(specs[name], train_c), test_c, config.validation.anchor_laps)
            rows.append({"compound": compound, "model": name, "selected": name == choice["selected"],
                         "test_races": ",".join(sorted(test_c[RACE_COLUMN].unique())),
                         **compute_metrics(scored["actual"], scored["predicted"])})
    results = pd.DataFrame(rows)
    results.to_csv(results_path, index=False)
    pd.set_option("display.width", 200)
    print(results.round(4).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Phase 5 model comparison (two stages).")
    parser.add_argument("--stage", choices=("cv", "test"), required=True)
    parser.add_argument("--force", action="store_true",
                        help="allow a repeated test run (logged), or a CV re-run after the test")
    parser.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    args = parser.parse_args()
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    config = load_config(args.config)
    if args.stage == "cv":
        run_cv(config, args.force)
    else:
        run_test(config, args.force)


if __name__ == "__main__":
    main()
