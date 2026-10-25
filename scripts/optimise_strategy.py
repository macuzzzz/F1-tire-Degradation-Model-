"""Phase 6: optimise the pit-stop strategy for the Hungarian GP (DECISIONS.md D56-D66).

Run from the repository root:

    .venv\\Scripts\\python scripts/optimise_strategy.py

Steps:
1. Refit the model form SELECTED in Phase 5 (reports/model_selection.json)
   for each strategy compound on the 2023-2025 races (D56).
2. Build the strategy inputs: base pace of the typical car (median C3 stint
   offset), order-balanced compound pace delta (D60), stint limits (D63),
   pit loss estimated from the same races (D58), fuel coefficient.
3. Optimise every one-stop order with brute force, secant and Newton, and
   every two-stop sequence by brute force; rank all strategies.
4. Write reports/phase6_*.csv and reports/figures/phase6_*.png.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import matplotlib

# Draw figures to files only (no window).
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Make the package in src/ importable when this script is run directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tyredeg.config import load_config  # noqa: E402
from tyredeg.models.polynomial import PolynomialDegradationModel  # noqa: E402
from tyredeg.preparation import prepare_laps  # noqa: E402
from tyredeg.strategy import (  # noqa: E402
    build_strategy_inputs,
    compare_strategies,
    feasible_pit_laps,
    race_time,
    total_race_time,
)
from tyredeg.validation import load_selection  # noqa: E402

REPORTS = REPO_ROOT / "reports"
FIGURES = REPORTS / "figures"


def build_inputs(config):
    """Prepare the strategy races and build the inputs with the shared builder (D56-D63)."""
    # Strategy races (2023-2025), prepared and cleaned, and the model form frozen in Phase 5.
    races = [race for race in config.races if race.year in config.strategy.data_years]
    prepared = prepare_laps(config, races)
    selection = load_selection(REPO_ROOT / config.validation.selection_file)["selection"]
    names = {c: selection[c]["selected"] for c in config.strategy.compounds}
    # Refit the models and build the race-time inputs (base pace, stint limits, pit loss).
    inputs = build_strategy_inputs(prepared.all_laps, prepared.clean, config, names)
    return (inputs.models, inputs.total_laps, inputs.pit_loss, inputs.pit_info, inputs.deltas,
            inputs.info, prepared.clean)


def team_spread(clean, compounds):
    """OI-8 diagnostic: linear degradation rate per team (teams with >= 4 stints)."""
    # Diagnostic: the linear wear rate of each team with enough stints (at least 4).
    rows = []
    for compound in compounds:
        laps = clean[clean["PirelliCompound"] == compound]
        for team, group in laps.groupby("Team"):
            if group["StintId"].nunique() < 4:
                continue
            model = PolynomialDegradationModel(compound).fit(group["TyreLife"], group["FuelCorrectedTime"],
                                                             group["StintId"])
            p = model.params()
            rows.append({"compound": compound, "team": team, "rate_s_per_lap": p["coefficients"][0],
                         "analytic_se": p["standard_errors"][0], "n_stints": group["StintId"].nunique()})
    return pd.DataFrame(rows).sort_values(["compound", "rate_s_per_lap"])


def plot_race_time(models, total_laps, pit_loss, k_fuel, add_fuel, methods):
    # One panel per compound order (C3 then C4, and C4 then C3).
    compounds = sorted(models)
    orders = [(a, b) for a in compounds for b in compounds if a != b]
    fig, axes = plt.subplots(1, len(orders), figsize=(6.5 * len(orders), 4.6), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (first, second) in zip(axes, orders):
        # Race time for every possible pit lap, including those outside the stint limits (dashed).
        laps = np.arange(1, total_laps)
        times = np.array([race_time(int(lap), first, second, models, total_laps, pit_loss, k_fuel, add_fuel,
                                    enforce_max_stint=False) for lap in laps])
        # Highlight the pit laps allowed by the stint limits and mark the brute-force optimum.
        window = feasible_pit_laps(first, second, models, total_laps)
        inside = np.isin(laps, window)
        ax.plot(laps, times, color="lightgrey", linestyle="--", label="outside stint limits (extrapolated)")
        ax.plot(laps[inside], times[inside], color="tab:blue", linewidth=2, label="feasible pit laps")
        rows = methods[methods["strategy"] == f"{first} -> {second}"]
        best = rows[rows["method"] == "brute force"].iloc[0]
        lap = int(best["pit_laps"])
        ax.plot(lap, best["total_time"], "r*", markersize=14, label=f"optimum: lap {lap}")
        # Mark where the continuous slope dT/dL is zero (the relaxed optimum).
        root = rows[rows["method"] == "secant"]["continuous_root"]
        if len(root) and pd.notna(root.iloc[0]):
            ax.axvline(root.iloc[0], color="tab:green", linestyle=":", label=f"dT/dL = 0 at {root.iloc[0]:.2f}")
        ax.set_title(f"One stop: {first} then {second}")
        ax.set_xlabel("pit lap (laps on the first set)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        # Zoom the y-axis onto the region around the optimum.
        lowest = times[inside].min() if inside.any() else times.min()
        ax.set_ylim(lowest - 5, lowest + 60)
    axes[0].set_ylabel("predicted race time [s]")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase6_race_time_vs_pit_lap.png", dpi=150)
    plt.close(fig)


def plot_degradation_models(models, clean):
    """Fitted degradation curve of each strategy compound over the observed data (D56, D63).

    Points: mean of (fuel-corrected lap time - stint offset) per tyre age, ages
    with at least 5 laps. The dotted line marks the stint limit.
    """
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    # For each compound: observed degradation (stint offsets removed), averaged per tyre age.
    for (compound, cm), colour in zip(sorted(models.items()), ("tab:blue", "tab:orange", "tab:green")):
        laps = clean[clean["PirelliCompound"] == compound]
        offsets = laps["StintId"].map(cm.model.stint_offsets()).to_numpy(float)
        adjusted = laps["FuelCorrectedTime"].to_numpy(float) - offsets
        table = pd.DataFrame({"age": laps["TyreLife"].to_numpy(float), "d": adjusted})
        means = table.groupby("age")["d"].agg(["mean", "count"])
        # Show only ages with at least 5 laps, the same rule as the stint limit.
        means = means[means["count"] >= 5]
        ax.plot(means.index, means["mean"], "o", ms=3, color=colour, alpha=0.6)
        # Fitted curve up to the stint limit, and the limit itself as a dotted line.
        ages = np.linspace(0, cm.max_stint_laps, 100)
        ax.plot(ages, cm.model.degradation(ages), color=colour,
                label=f"{compound} (stint limit {cm.max_stint_laps} laps, dotted)")
        ax.axvline(cm.max_stint_laps, color=colour, linestyle=":")
    ax.set_xlabel("tyre age [laps]")
    ax.set_ylabel("degradation d(age) [s]")
    ax.set_title("Strategy models: tyre degradation, Hungary 2023-2025")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase6_degradation_models.png", dpi=150)
    plt.close(fig)


def plot_two_stop(models, total_laps, pit_loss, k_fuel, add_fuel, ranking):
    # Use the fastest two-stop sequence from the ranking.
    two = ranking[ranking["stops"] == "2-stop"]
    if two.empty:
        return
    sequence = tuple(two.iloc[0]["strategy"].split(" -> "))
    # Race time for every pair of pit laps that keeps all three stints within their limits.
    first_stops = np.arange(1, total_laps - 1)
    grid = np.full((total_laps, total_laps), np.nan)
    for a in first_stops:
        for b in range(a + 1, total_laps):
            lengths = (a, b - a, total_laps - b)
            if all(n <= models[c].max_stint_laps for c, n in zip(sequence, lengths)):
                grid[a, b] = total_race_time(sequence, lengths, models, pit_loss, k_fuel, add_fuel)
    # Colour = time above the best combination; the star marks the optimum.
    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    best = np.nanmin(grid)
    image = ax.imshow(grid.T - best, origin="lower", cmap="viridis", vmax=20, aspect="auto")
    a, b = np.unravel_index(np.nanargmin(grid), grid.shape)
    ax.plot(a, b, "r*", markersize=14)
    ax.set_title(f"Two stops {' -> '.join(sequence)}: time above best [s]")
    ax.set_xlabel("first pit lap")
    ax.set_ylabel("second pit lap")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase6_two_stop.png", dpi=150)
    plt.close(fig)


def main(config=None):
    """Run this stage; ``config`` defaults to the repository's config.yaml (used by run_pipeline.py)."""
    # FastF1 logs every cache access; keep only its errors. Load the config unless given.
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    if config is None:
        config = load_config(REPO_ROOT / "config.yaml")
    strategy = config.strategy
    # Build the inputs and optimise every one-stop and two-stop strategy.
    models, total_laps, pit_loss, pit_info, deltas, info, clean = build_inputs(config)
    k_fuel, add_fuel = config.k_fuel, strategy.add_fuel_effect

    methods, ranking = compare_strategies(models, total_laps, pit_loss, k_fuel, add_fuel,
                                          strategy.include_two_stop, strategy.root_xtol, strategy.root_ftol)
    # Team-by-team wear rates (reported only, not used in the optimisation).
    spread = team_spread(clean, strategy.compounds)

    # Save the tables and draw the strategy figures.
    REPORTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    inputs = info
    inputs.to_csv(REPORTS / "phase6_inputs.csv", index=False)
    methods.to_csv(REPORTS / "phase6_methods.csv", index=False)
    ranking.to_csv(REPORTS / "phase6_strategy_ranking.csv", index=False)
    spread.to_csv(REPORTS / "phase6_team_degradation.csv", index=False)
    plot_race_time(models, total_laps, pit_loss, k_fuel, add_fuel, methods)
    plot_two_stop(models, total_laps, pit_loss, k_fuel, add_fuel, ranking)
    plot_degradation_models(models, clean)

    # Print the inputs and results.
    pd.set_option("display.width", 220)
    print(f"Strategy inputs (refit on {list(strategy.data_years)}): {total_laps} laps, pit loss "
          f"{pit_loss:.2f} s ({pit_info}), k_fuel {k_fuel}, fuel added back: {add_fuel}")
    print(inputs.round(4).to_string(index=False))
    for compound, delta in deltas.items():
        print(f"pace delta {compound} - {strategy.compounds[0]}: {delta}")
    print("\nOne-stop methods:\n", methods[methods["stops"] == "1-stop"].drop(columns=["stops"])
          .round(4).to_string(index=False))
    print("\nStrategy ranking:\n", ranking.round(3).to_string(index=False))
    print("\nC3 / C4 degradation rate by team (OI-8):\n", spread.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
