"""Phase 7: sensitivity of the strategy result (DECISIONS.md D67-D73).

Run from the repository root (after Phases 5-6):

    .venv\\Scripts\\python scripts/sensitivity_analysis.py

Writes to reports/:
  phase7_oat.csv                    one-at-a-time ranges (all outputs)
  phase7_tornado_<output>.csv/.png  tornado tables and plots
  phase7_sensitivity_coefficients.csv  central-difference derivatives and elasticities
  phase7_step_size_check.csv        derivatives with 0.1 %, 1 % and 10 % steps
  phase7_fuel_vs_rate.csv/.png      fitted degradation rate against k_fuel
"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tyredeg.config import load_config  # noqa: E402
from tyredeg.models.polynomial import PolynomialDegradationModel  # noqa: E402
from tyredeg.preparation import prepare_laps  # noqa: E402
from tyredeg.sensitivity import (  # noqa: E402
    degradation_rate_vs_fuel,
    one_at_a_time,
    plot_tornado,
    sensitivity_coefficient,
    step_size_check,
    tornado_table,
)
from tyredeg.strategy import (  # noqa: E402
    LinearDegradation,
    build_strategy_inputs,
    optimise_brute_force,
    optimise_continuous,
    optimise_two_stop,
)
from tyredeg.numerics.root_finding import bisection  # noqa: E402
from tyredeg.validation import load_selection  # noqa: E402

REPORTS = REPO_ROOT / "reports"
FIGURES = REPORTS / "figures"
OUTPUTS = {
    "L_star": "continuous optimum L* (C3 first, unconstrained) [laps]",
    "pit_lap": "optimal integer pit lap (C3 first, within stint limits)",
    "one_stop_time": "best one-stop race time [s]",
    "two_stop_time": "best two-stop race time [s]",
    "margin": "one-stop minus two-stop time [s] (> 0: two stops faster)",
}


class Scenario:
    """Evaluates the Phase 6 strategy with any inputs overridden (D67)."""

    def __init__(self, config, prepared, model_names):
        self.config = config
        self.prepared = prepared
        self.model_names = model_names
        self.cache = {}

    def inputs(self, k_fuel, model, min_laps):
        key = (k_fuel, model, min_laps)
        if key not in self.cache:
            names = dict(self.model_names) if model is None else {c: model for c in self.model_names}
            self.cache[key] = build_strategy_inputs(self.prepared.all_laps, self.prepared.clean,
                                                    self.config, names, k_fuel=k_fuel,
                                                    min_laps_at_max_age=min_laps)
        return self.cache[key]

    def evaluate(self, k_fuel=None, pit_loss=None, rate_C3=None, rate_C4=None, delta=None,
                 model=None, min_laps=None):
        k_fuel = self.config.k_fuel if k_fuel is None else k_fuel
        built = self.inputs(k_fuel, model, min_laps)
        models = dict(built.models)
        for compound, rate in (("C3", rate_C3), ("C4", rate_C4)):
            if rate is not None:
                models[compound] = replace(models[compound], model=LinearDegradation(rate))
        if delta is not None:
            models["C4"] = replace(models["C4"], base_time=models["C3"].base_time + delta)
        pit_loss = built.pit_loss if pit_loss is None else pit_loss
        n, add = built.total_laps, self.config.strategy.add_fuel_effect

        # L* is the UNCONSTRAINED optimum, so it is computed with the stint
        # limits relaxed to n - 1 laps (it must not depend on them; C7).
        relaxed = {c: replace(m, max_stint_laps=n - 1) for c, m in models.items()}
        try:
            l_star = optimise_continuous("C3", "C4", relaxed, n, pit_loss, k_fuel, add,
                                         xtol=self.config.strategy.root_xtol,
                                         ftol=self.config.strategy.root_ftol).continuous_root
        except TypeError:
            l_star = np.nan  # KNN: no closed-form integral, brute force only
        try:
            one = min((optimise_brute_force(a, b, models, n, pit_loss, k_fuel, add)
                       for a, b in (("C3", "C4"), ("C4", "C3"))), key=lambda r: r.total_time)
            c3_first = optimise_brute_force("C3", "C4", models, n, pit_loss, k_fuel, add)
            one_time, pit_lap = one.total_time, c3_first.pit_laps[0]
        except ValueError:
            # No one-stop fits within the stint limits (C7).
            one_time, pit_lap = np.nan, np.nan
        twos = []
        for sequence in (("C3", "C4", "C4"), ("C3", "C3", "C4"), ("C3", "C4", "C3"),
                         ("C4", "C3", "C4"), ("C4", "C4", "C3"), ("C4", "C3", "C3")):
            try:
                twos.append(optimise_two_stop(sequence, models, n, pit_loss, k_fuel, add))
            except ValueError:
                pass
        two = min(twos, key=lambda r: r.total_time)
        if np.isnan(one_time):
            best = "two stops (one stop infeasible)"
        else:
            best = "two stops" if two.total_time < one_time else "one stop"
        return {
            "L_star": l_star,
            "pit_lap": pit_lap,
            "one_stop_time": one_time,
            "two_stop_time": two.total_time,
            "margin": one_time - two.total_time,
            "best": best,
            "two_stop_stints": "+".join(f"{n}{c}" for c, n in zip(two.compounds, two.stint_lengths)),
        }


def per_year_rates(clean, compounds):
    """Linear rate of each compound in each strategy year (nominal k_fuel)."""
    rates = {}
    for year, group in clean.groupby("Year"):
        rates[year] = {}
        for compound in compounds:
            laps = group[group["PirelliCompound"] == compound]
            model = PolynomialDegradationModel(compound).fit(laps["TyreLife"], laps["FuelCorrectedTime"],
                                                             laps["StintId"])
            rates[year][compound] = float(model.params()["coefficients"][0])
    return rates


def main(config=None):
    """Run this stage; ``config`` defaults to the repository's config.yaml (used by run_pipeline.py)."""
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    if config is None:
        config = load_config(REPO_ROOT / "config.yaml")
    races = [race for race in config.races if race.year in config.strategy.data_years]
    prepared = prepare_laps(config, races)
    selection = load_selection(REPO_ROOT / config.validation.selection_file)["selection"]
    names = {c: selection[c]["selected"] for c in config.strategy.compounds}
    scenario = Scenario(config, prepared, names)
    nominal_inputs = scenario.inputs(config.k_fuel, None, None)
    nominal = scenario.evaluate()
    print("Nominal outputs:", nominal)

    # Fitted uncertainty of the wear rates: stint bootstrap (D45, D67).
    rates, se = {}, {}
    for compound in ("C3", "C4"):
        model = nominal_inputs.models[compound].model
        rates[compound] = float(model.params()["coefficients"][0])
        se[compound] = float(model.bootstrap(config.models.bootstrap_resamples, config.models.confidence_level,
                                             config.random_seed).standard_errors[0])
    years = per_year_rates(prepared.clean, ("C3", "C4"))
    delta_info = nominal_inputs.deltas["C4"]
    pit = nominal_inputs.pit_info
    low_k, high_k = config.k_fuel_range
    print(f"rates {rates}, bootstrap SE {se}, per-year {years}")

    variations = [
        ("fuel coefficient k_fuel", "0.015", {"k_fuel": low_k}),
        ("fuel coefficient k_fuel", "0.070", {"k_fuel": high_k}),
        ("pit loss", "q25", {"pit_loss": pit["q25"]}),
        ("pit loss", "q75", {"pit_loss": pit["q75"]}),
        ("compound delta C4-C3", "C3-first median", {"delta": delta_info["median_reference_first"]}),
        ("compound delta C4-C3", "C4-first median", {"delta": delta_info["median_other_first"]}),
    ]
    settings = config.sensitivity
    for min_laps in settings.alternative_min_laps:
        variations.append(("stint-limit rule", f">={min_laps} laps", {"min_laps": min_laps}))
    for compound in ("C3", "C4"):
        for multiple in settings.rate_se_multiples:
            variations.append((f"{compound} wear rate", f"{multiple:+d} SE",
                               {f"rate_{compound}": rates[compound] + multiple * se[compound]}))
    low_year = min(years, key=lambda y: years[y]["C3"] + years[y]["C4"])
    high_year = max(years, key=lambda y: years[y]["C3"] + years[y]["C4"])
    for label, year in (("low-wear year", low_year), ("high-wear year", high_year)):
        variations.append(("year-to-year wear", f"{label} {year}",
                           {"rate_C3": years[year]["C3"], "rate_C4": years[year]["C4"]}))
    for model in settings.alternative_models:
        variations.append(("degradation model", model, {"model": model}))

    oat = one_at_a_time(scenario.evaluate, variations)
    REPORTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    oat.to_csv(REPORTS / "phase7_oat.csv", index=False)

    for output in ("margin", "L_star", "pit_lap"):
        table = tornado_table(oat, output)
        table.to_csv(REPORTS / f"phase7_tornado_{output}.csv", index=False)
        plot_tornado(table, nominal[output], "One-at-a-time sensitivity of the\n" + OUTPUTS[output],
                     OUTPUTS[output], FIGURES / f"phase7_tornado_{output}.png")

    # Local coefficients (smooth outputs only, D69).
    continuous_inputs = {
        "fuel coefficient k_fuel": ("k_fuel", config.k_fuel, "relative"),
        "pit loss": ("pit_loss", nominal_inputs.pit_loss, "relative"),
        "C3 wear rate": ("rate_C3", rates["C3"], "relative"),
        "C4 wear rate": ("rate_C4", rates["C4"], "relative"),
        "compound delta C4-C3": ("delta", delta_info["delta"], "absolute"),
    }
    rows, checks = [], []
    for label, (argument, x0, kind) in continuous_inputs.items():
        for output in ("L_star", "one_stop_time", "two_stop_time", "margin"):
            def f(x, argument=argument, output=output):
                return scenario.evaluate(**{argument: x})[output]
            if kind == "relative":
                result = sensitivity_coefficient(f, x0, relative_step=settings.relative_step)
                check = step_size_check(f, x0, list(settings.check_relative_steps))
                checks.append(check.assign(input=label, output=output))
            else:
                result = sensitivity_coefficient(f, x0, absolute_step=settings.delta_absolute_step)
            elasticity = result.elasticity if output != "margin" else np.nan  # D70: margin ~ 0
            rows.append({"input": label, "output": output, "x0": x0, "step": result.step,
                         "y0": result.y0, "derivative": result.derivative, "elasticity": elasticity})
    coefficients = pd.DataFrame(rows)
    coefficients.to_csv(REPORTS / "phase7_sensitivity_coefficients.csv", index=False)
    pd.concat(checks).to_csv(REPORTS / "phase7_step_size_check.csv", index=False)

    # Break-even values: where one stop and two stops take the same time
    # (margin = 0), found with my bisection (D73).
    break_even = []
    for label, argument, bracket in (("fuel coefficient k_fuel", "k_fuel", (low_k, config.k_fuel)),
                                     ("pit loss", "pit_loss", (nominal_inputs.pit_loss, 40.0))):
        def margin_of(x, argument=argument):
            return scenario.evaluate(**{argument: x})["margin"]
        root = bisection(margin_of, *bracket, xtol=1e-5, ftol=0.0)
        break_even.append({"input": label, "break_even": root.root, "iterations": root.iterations,
                           "nominal": config.k_fuel if argument == "k_fuel" else nominal_inputs.pit_loss})
    pd.DataFrame(break_even).to_csv(REPORTS / "phase7_break_even.csv", index=False)

    # How the fuel coefficient changes the fitted wear rate itself (D72).
    k_grid = np.round(np.arange(0.0, 0.0801, 0.005), 3)
    fuel_rows = []
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for compound in ("C3", "C4"):
        table, slope = degradation_rate_vs_fuel(prepared.clean, compound, k_grid, config.k_fuel)
        fuel_rows.append(table.assign(compound=compound, slope=slope))
        ax.plot(table["k_fuel"], table["rate"], "o-", label=f"{compound}: d(rate)/dk = {slope:.6f}")
        print(f"{compound}: rate vs k_fuel slope {slope:.9f}")
    ax.axvspan(low_k, high_k, color="grey", alpha=0.15, label="k_fuel sensitivity range")
    ax.axvline(config.k_fuel, color="black", linestyle=":", label=f"nominal k_fuel = {config.k_fuel}")
    ax.set_xlabel("fuel coefficient k_fuel [s per lap of fuel]")
    ax.set_ylabel("fitted linear wear rate [s/lap]")
    ax.set_title("The fitted wear rate rises one-for-one with k_fuel")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase7_fuel_vs_rate.png", dpi=150)
    plt.close(fig)
    pd.concat(fuel_rows).to_csv(REPORTS / "phase7_fuel_vs_rate.csv", index=False)

    pd.set_option("display.width", 220)
    print("\nOne-at-a-time:\n", oat.round(3).to_string(index=False))
    print("\nTornado (margin):\n", tornado_table(oat, "margin").round(3).to_string(index=False))
    print("\nCoefficients:\n", coefficients.round(5).to_string(index=False))
    print("\nStep-size check (derivative by relative step):\n",
          pd.concat(checks).pivot_table(index=["input", "output"], columns="relative_step",
                                        values="derivative").round(5).to_string())


if __name__ == "__main__":
    main()
