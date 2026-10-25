"""Figures of the data preparation steps (DECISIONS.md D91).

Run from the repository root (also run by run_pipeline.py in the "data" stage):

    .venv\\Scripts\\python scripts/data_figures.py

Writes to reports/figures/:
- data_cleaning.png         every lap of one race, kept vs removed by the cleaning rules (D17-D20);
- data_fuel_correction.png  median clean lap time per lap, raw vs fuel-corrected (D21, D22);
- data_degradation_raw.png  fuel-corrected lap time vs tyre age for all training laps per compound;
- data_pit_loss.png         distribution of the measured pit losses with median and IQR (D24, D58).
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

# Make the package in src/ importable when this script is run directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tyredeg.config import load_config  # noqa: E402
from tyredeg.fuel_correction import estimate_pit_loss  # noqa: E402
from tyredeg.preparation import prepare_laps  # noqa: E402

FIGURES = REPO_ROOT / "reports" / "figures"
# The race shown in the single-race figures: a training race with a dry, green race.
EXAMPLE_YEAR = 2024


def plot_cleaning(prepared, year):
    laps = prepared.all_laps
    # Mark each lap of the race as kept (in the clean table) or removed.
    kept = set(zip(prepared.clean["Driver"], prepared.clean["LapNumber"]))
    is_kept = np.array([(d, n) in kept for d, n in zip(laps["Driver"], laps["LapNumber"])])
    # Median clean lap time, used to zoom the y-axis.
    median = float(np.nanmedian(prepared.clean["LapTime"]))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    # Removed laps in red, kept laps in blue.
    ax.scatter(laps.loc[~is_kept, "LapNumber"], laps.loc[~is_kept, "LapTime"], s=6, color="tab:red",
               alpha=0.5, label=f"removed ({(~is_kept).sum()} laps)")
    ax.scatter(laps.loc[is_kept, "LapNumber"], laps.loc[is_kept, "LapTime"], s=6, color="tab:blue",
               alpha=0.5, label=f"kept ({is_kept.sum()} laps)")
    # Pit laps and safety-car laps are far slower; cut the axis so normal laps are visible.
    ax.set_ylim(0.97 * median, 1.25 * median)
    ax.set_xlabel("lap number")
    ax.set_ylabel("lap time [s]")
    ax.set_title(f"{year} Hungarian GP: laps kept and removed by the cleaning rules")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "data_cleaning.png", dpi=150)
    plt.close(fig)


def plot_fuel_correction(clean, year, k_fuel):
    # Median lap time per lap number, before and after fuel correction.
    per_lap = clean.groupby("LapNumber")[["LapTime", "FuelCorrectedTime"]].median()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(per_lap.index, per_lap["LapTime"], "o-", ms=3, label="raw lap time")
    ax.plot(per_lap.index, per_lap["FuelCorrectedTime"], "o-", ms=3,
            label=f"fuel-corrected: + {k_fuel} x (lap - 1)")
    ax.set_xlabel("lap number")
    ax.set_ylabel("median clean lap time [s]")
    ax.set_title(f"{year} Hungarian GP: fuel correction (the rising trend is tyre wear)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "data_fuel_correction.png", dpi=150)
    plt.close(fig)


def plot_raw_degradation(clean, compounds):
    # One panel per compound: every clean training lap, coloured by year.
    fig, axes = plt.subplots(1, len(compounds), figsize=(5.5 * len(compounds), 4), sharey=True)
    for ax, compound in zip(np.atleast_1d(axes), compounds):
        laps = clean[clean["PirelliCompound"] == compound]
        for year, group in laps.groupby("Year"):
            ax.scatter(group["TyreLife"], group["FuelCorrectedTime"], s=4, alpha=0.3, label=str(year))
        ax.set_title(f"{compound}: every clean lap (each car has its own base pace)")
        ax.set_xlabel("tyre age [laps]")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, markerscale=3)
    np.atleast_1d(axes)[0].set_ylabel("fuel-corrected lap time [s]")
    fig.tight_layout()
    fig.savefig(FIGURES / "data_degradation_raw.png", dpi=150)
    plt.close(fig)


def plot_pit_loss(estimate, years):
    fig, ax = plt.subplots(figsize=(7, 4))
    # Histogram of all measured pit losses with the median and the interquartile range.
    ax.hist(estimate.stops["PitLoss"], bins=30, color="tab:grey", edgecolor="white")
    ax.axvline(estimate.median_s, color="tab:red", label=f"median {estimate.median_s:.2f} s")
    ax.axvspan(estimate.q25_s, estimate.q75_s, color="tab:red", alpha=0.15,
               label=f"IQR {estimate.q25_s:.2f}-{estimate.q75_s:.2f} s")
    ax.set_xlabel("pit loss [s]")
    ax.set_ylabel("number of stops")
    ax.set_title(f"Pit loss of {estimate.n_stops} green-flag stops, {years[0]}-{years[-1]}")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "data_pit_loss.png", dpi=150)
    plt.close(fig)


def main(config=None):
    """Make the data figures; ``config`` defaults to the repository's config.yaml."""
    # FastF1 logs every cache access; keep only its errors. Load the config unless given.
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    if config is None:
        config = load_config(REPO_ROOT / "config.yaml")
    FIGURES.mkdir(parents=True, exist_ok=True)
    # Cleaning and fuel-correction figures for one example race.
    example = [race for race in config.races if race.year == EXAMPLE_YEAR]
    prepared = prepare_laps(config, example)
    plot_cleaning(prepared, EXAMPLE_YEAR)
    plot_fuel_correction(prepared.clean, EXAMPLE_YEAR, config.k_fuel)

    # Raw degradation scatter for the training races.
    training = prepare_laps(config, config.train_races).clean
    plot_raw_degradation(training, config.pirelli_compounds)

    # Same races as the strategy pit loss (D58), so the figure shows the value used.
    # Pit-loss distribution from the strategy races (the value the strategy uses).
    years = list(config.strategy.data_years)
    strategy_data = prepare_laps(config, [race for race in config.races if race.year in years])
    plot_pit_loss(estimate_pit_loss(strategy_data.all_laps, strategy_data.clean), years)


if __name__ == "__main__":
    main()
