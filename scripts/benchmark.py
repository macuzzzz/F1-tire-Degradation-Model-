"""Phase 8 benchmarks (DECISIONS.md D74-D81). Run from the repository root:

    .venv\\Scripts\\python scripts/benchmark.py

Sections (each writes reports/phase8_<name>.csv and, where useful, a figure):
  machine        machine / Python / library versions (phase8_machine.json)
  ode            accuracy vs cost of Euler, Heun, RK4, RK45 and the exact solution
  knn            my brute-force KNN vs scikit-learn's kd-tree: time and memory vs n
  least_squares  normal equations vs QR vs SVD on ill-conditioned polynomial fits
  strategy       brute force vs secant vs Newton for the pit-lap optimisation
  profile        cProfile of the compute pipeline, before/after the one optimisation

Timings use time.perf_counter with a warm-up run and repeats (config
`performance`); they depend on the machine and on other running programs.
"""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import matplotlib

# Draw figures to files only (no window).
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.neighbors import KNeighborsRegressor  # noqa: E402

# Make the package in src/ importable when this script is run directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tyredeg.config import load_config  # noqa: E402
from tyredeg.models.knn import KNNRegressor  # noqa: E402
from tyredeg.models.wear_ode import exact_degradation  # noqa: E402
from tyredeg.numerics.least_squares import (  # noqa: E402
    fit_linear_least_squares,
    fit_linear_least_squares_qr,
    polynomial_design_matrix,
)
from tyredeg.numerics.linear_solvers import NearSingularWarning, SingularMatrixError  # noqa: E402
from tyredeg.numerics.ode_solvers import euler, heun, rk4, rk45  # noqa: E402
from tyredeg.performance import (  # noqa: E402
    machine_info,
    peak_memory,
    profile_function,
    solver_flops,
    time_function,
)
from tyredeg.preparation import prepare_laps  # noqa: E402
from tyredeg.strategy import (  # noqa: E402
    build_strategy_inputs,
    compare_strategies,
    optimise_brute_force,
    optimise_continuous,
    optimise_two_stop,
)
from tyredeg.validation import candidate_models, cross_validate, leave_one_race_out  # noqa: E402

# Output folders (main() can redirect them, e.g. to benchmarks_latest).
REPORTS = REPO_ROOT / "reports"
FIGURES = REPORTS / "figures"

# Wear ODE used for the solver benchmark (same as the Phase 3 study, D75).
# Test ODE with a known exact solution, the same as in the Phase 3 study.
A_WEAR, B_WEAR, LAPS = 0.05, 0.03, 40.0
EXACT_END = float(exact_degradation([LAPS], A_WEAR, B_WEAR)[0])


def wear_rhs(t, d):
    # Right-hand side of the wear ODE dd/dn = a + b*d.
    return A_WEAR + B_WEAR * d


# ---------------------------------------------------------------------------
# ODE solvers: accuracy vs cost
# ---------------------------------------------------------------------------
def bench_ode(perf):
    # Each fixed-step method at every step count: error, f-evaluations, FLOPs and run time.
    rows = []
    for name, solver in (("euler", euler), ("heun", heun), ("rk4", rk4)):
        for n in perf.ode_step_counts:
            h = LAPS / n
            _, d, nfev = solver(wear_rhs, (0.0, LAPS), 0.0, h)
            timing = time_function(lambda: solver(wear_rhs, (0.0, LAPS), 0.0, h), perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
            rows.append({"method": name, "setting": f"h = {h:.4g}", "steps": n, "rejected": 0, "nfev": nfev,
                         "flops": solver_flops(name, n), "error": abs(d[-1] - EXACT_END),
                         "time_mean_s": timing.mean, "time_std_s": timing.std, "time_min_s": timing.minimum})
    # RK45 at every tolerance: steps, rejections, evaluations, FLOPs, error and time.
    for rtol in perf.rk45_rtols:
        atol = rtol * 1e-3
        _, d, nfev, stats = rk45(wear_rhs, (0.0, LAPS), 0.0, rtol=rtol, atol=atol)
        timing = time_function(lambda: rk45(wear_rhs, (0.0, LAPS), 0.0, rtol=rtol, atol=atol),
                               perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
        rows.append({"method": "rk45", "setting": f"rtol = {rtol:.0e}", "steps": stats.n_accepted,
                     "rejected": stats.n_rejected, "nfev": nfev,
                     "flops": solver_flops("rk45", stats.n_accepted, n_rejected=stats.n_rejected),
                     "error": abs(d[-1] - EXACT_END), "time_mean_s": timing.mean,
                     "time_std_s": timing.std, "time_min_s": timing.minimum})
    # The closed-form solution as the reference point (error 0).
    ages = np.arange(0.0, LAPS + 1.0)
    timing = time_function(lambda: exact_degradation(ages, A_WEAR, B_WEAR), perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
    rows.append({"method": "exact", "setting": "closed form, 41 ages", "steps": 0, "rejected": 0, "nfev": 0,
                 "flops": 41 * 4, "error": 0.0, "time_mean_s": timing.mean, "time_std_s": timing.std,
                 "time_min_s": timing.minimum})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase8_ode.csv", index=False)

    # Accuracy against cost (evaluations) and against run time, on log-log axes.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for method, group in table[table["method"] != "exact"].groupby("method", sort=False):
        errors = np.maximum(group["error"], 1e-17)
        axes[0].loglog(group["nfev"], errors, "o-", label=method)
        axes[1].loglog(group["time_mean_s"], errors, "o-", label=method)
    exact_time = table[table["method"] == "exact"]["time_mean_s"].iloc[0]
    axes[1].axvline(exact_time, color="black", linestyle=":", label="exact solution (error 0)")
    for ax, xlabel in zip(axes, ("function evaluations", "mean run time [s]")):
        ax.axhline(1e-3, color="grey", linestyle="--", linewidth=0.8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("|error at lap 40| [s]")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    axes[0].set_title("Accuracy vs cost (function evaluations)")
    axes[1].set_title("Accuracy vs run time")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase8_ode_error_vs_cost.png", dpi=150)
    plt.close(fig)
    return table


# ---------------------------------------------------------------------------
# KNN: brute force vs kd-tree
# ---------------------------------------------------------------------------
def bench_knn(perf, seed):
    # Seed from config.yaml (random_seed, rule 11) so the synthetic data are reproducible.
    # Seeded random data (rule 11): queries and training sets of increasing size.
    rng = np.random.default_rng(seed)
    queries = rng.uniform(0, 60, size=perf.knn_queries)
    rows = []
    for n in perf.knn_train_sizes:
        X = rng.uniform(0, 60, size=n)              # continuous ages: no tied distances
        y = 0.06 * X + rng.normal(0, 0.4, size=n)

        # My brute-force KNN against scikit-learn's kd-tree on the same data.
        def mine():
            return KNNRegressor(perf.knn_k).fit(X, y).predict(queries)

        def tree():
            # scikit-learn's kd-tree KNN, the benchmark (it needs 2-D inputs).
            model = KNeighborsRegressor(n_neighbors=perf.knn_k, algorithm="kd_tree")
            return model.fit(X.reshape(-1, 1), y).predict(queries.reshape(-1, 1))

        # Time and peak memory of each; check both give the same predictions.
        for name, func in (("mine (brute force)", mine), ("sklearn kd_tree", tree)):
            timing = time_function(func, perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
            prediction, peak = peak_memory(func)
            rows.append({"method": name, "n_train": n, "n_queries": perf.knn_queries, "k": perf.knn_k,
                         "time_mean_s": timing.mean, "time_std_s": timing.std, "time_min_s": timing.minimum,
                         "peak_memory_bytes": peak, "prediction_mean": float(np.mean(prediction))})
        rows[-1]["max_abs_difference"] = rows[-2]["max_abs_difference"] = float(
            np.max(np.abs(mine() - tree())))
    table = pd.DataFrame(rows)

    # Empirical scaling exponent: slope of log(time) vs log(n), fitted with my least squares.
    # Scaling exponent: slope of log(time) against log(n), fitted with my least squares.
    exponents = {}
    for method, group in table.groupby("method"):
        design = np.column_stack([np.ones(len(group)), np.log(group["n_train"].to_numpy(float))])
        exponents[method] = float(fit_linear_least_squares(design, np.log(group["time_min_s"].to_numpy())).coefficients[1])
    table["time_exponent"] = table["method"].map(exponents)
    table.to_csv(REPORTS / "phase8_knn.csv", index=False)

    # Time and memory against training-set size, on log-log axes.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    for method, group in table.groupby("method"):
        axes[0].loglog(group["n_train"], group["time_min_s"], "o-",
                       label=f"{method} (slope {exponents[method]:.2f})")
        axes[1].loglog(group["n_train"], group["peak_memory_bytes"] / 1e6, "o-", label=method)
    axes[0].set_ylabel("fit + predict time [s] (min of repeats)")
    axes[1].set_ylabel("peak traced memory [MB]")
    for ax in axes:
        ax.set_xlabel("training points n")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    axes[0].set_title(f"KNN, {perf.knn_queries} queries, k = {perf.knn_k}")
    axes[1].set_title("Memory (tracemalloc; misses untracked C memory)")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase8_knn_scaling.png", dpi=150)
    plt.close(fig)
    return table


# ---------------------------------------------------------------------------
# Least squares: conditioning
# ---------------------------------------------------------------------------
def scaled_coefficients(unscaled, centre, half_range):
    """Exact coefficients in s = (x - c) / r of the polynomial sum_j a_j x^j (binomial expansion)."""
    # Convert true coefficients in powers of x into powers of the scaled variable.
    scaled = np.zeros(len(unscaled))
    for j, a_j in enumerate(unscaled):
        for k in range(j + 1):
            scaled[k] += a_j * math.comb(j, k) * centre ** (j - k) * half_range**k
    return scaled


def bench_least_squares(perf):
    # For each degree: exact coefficients and noise-free data, unscaled and scaled.
    age = np.arange(1.0, 42.0)
    rows = []
    for degree in perf.lsq_degrees:
        true = np.array([80.0, 0.05] + [1e-4 * (-1) ** k for k in range(degree - 1)])[: degree + 1]
        y = polynomial_design_matrix(age, degree) @ true   # noise-free: exact answer known
        for scaled in (False, True):
            centre, half_range = (21.0, 20.0) if scaled else (0.0, 1.0)
            X = polynomial_design_matrix(age, degree, centre, half_range)
            reference = scaled_coefficients(true, centre, half_range)
            # My normal equations, QR with my back substitution, and NumPy's lstsq.
            methods = {
                "normal equations (mine)": lambda: fit_linear_least_squares(X, y).coefficients,
                "QR (numpy QR + my back substitution)": lambda: fit_linear_least_squares_qr(X, y).coefficients,
                "SVD (numpy lstsq)": lambda: np.linalg.lstsq(X, y, rcond=None)[0],
            }
            for name, method in methods.items():
                # Record accuracy, whether my solver refused (singular) or warned, and the run
                # time.
                status, error, timing = "ok", np.nan, None
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", NearSingularWarning)
                    try:
                        beta = method()
                        error = float(np.linalg.norm(beta - reference) / np.linalg.norm(reference))
                    except SingularMatrixError:
                        status = "singular (refused)"
                if any(issubclass(w.category, NearSingularWarning) for w in caught):
                    status = "near-singular warning"
                if status != "singular (refused)":
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", NearSingularWarning)
                        timing = time_function(method, perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
                rows.append({"degree": degree, "scaled": scaled, "method": name,
                             "cond_X": float(np.linalg.cond(X)), "cond_XtX": float(np.linalg.cond(X.T @ X)),
                             "relative_error": error, "status": status,
                             "time_mean_s": timing.mean if timing else np.nan,
                             "time_std_s": timing.std if timing else np.nan})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase8_least_squares.csv", index=False)

    # Error against the condition number of X, unscaled (left) and scaled (right).
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, scaled in zip(axes, (False, True)):
        subset = table[table["scaled"] == scaled]
        for method, group in subset.groupby("method", sort=False):
            ax.semilogy(group["cond_X"], np.maximum(group["relative_error"], 1e-17), "o-", label=method)
        ax.set_xscale("log")
        ax.set_xlabel("cond(X)")
        ax.set_title("unscaled tyre age" if not scaled else "scaled to [-1, 1]")
        ax.grid(True, which="both", alpha=0.3)
    axes[0].set_ylabel("relative coefficient error")
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase8_least_squares_conditioning.png", dpi=150)
    plt.close(fig)
    return table


# ---------------------------------------------------------------------------
# Strategy optimiser
# ---------------------------------------------------------------------------
def bench_strategy(perf, config, prepared, names):
    # Build the real strategy inputs, plus a version with the stint limits removed.
    inputs = build_strategy_inputs(prepared.all_laps, prepared.clean, config, names)
    n, pit, k = inputs.total_laps, inputs.pit_loss, config.k_fuel
    relaxed = {c: replace(m, max_stint_laps=n - 1) for c, m in inputs.models.items()}
    rows = []
    # Time brute force, secant and Newton with and without the limits.
    for label, models in (("with stint limits (6 feasible laps)", inputs.models),
                          ("limits relaxed (69 pit laps)", relaxed)):
        cases = {
            "brute force": lambda m=models: optimise_brute_force("C3", "C4", m, n, pit, k),
            "secant": lambda m=models: optimise_continuous("C3", "C4", m, n, pit, k, root_finder="secant"),
            "newton": lambda m=models: optimise_continuous("C3", "C4", m, n, pit, k, root_finder="newton"),
        }
        for method, func in cases.items():
            result = func()
            timing = time_function(func, perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
            rows.append({"case": label, "method": method, "pit_lap": result.pit_laps[0],
                         "total_time_s": result.total_time, "iterations": result.iterations,
                         "nfev": result.nfev, "time_mean_s": timing.mean, "time_std_s": timing.std})
    # Two-stop brute force for comparison.
    func = lambda: optimise_two_stop(("C3", "C4", "C4"), inputs.models, n, pit, k)  # noqa: E731
    result, timing = func(), time_function(func, perf.repeats, perf.warmup, perf.min_time_per_repeat_s)
    rows.append({"case": "two stops C3-C4-C4", "method": "brute force (pairs of laps)",
                 "pit_lap": result.pit_laps[0], "total_time_s": result.total_time,
                 "iterations": result.iterations, "nfev": result.nfev,
                 "time_mean_s": timing.mean, "time_std_s": timing.std})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase8_strategy.csv", index=False)
    return table


# ---------------------------------------------------------------------------
# Profiling and the optimisation
# ---------------------------------------------------------------------------
def compute_pipeline(config, train, strategy_data, names, implementation):
    """The compute part of the pipeline (no I/O): Phase 5 CV + Phase 6 strategy."""
    # The full computation that was optimised: cross-validation of every candidate plus the
    # strategy.
    folds_tables = []
    for compound in config.pirelli_compounds:
        laps = train.clean[train.clean["PirelliCompound"] == compound]
        folds = leave_one_race_out(laps["RaceId"])
        for spec in candidate_models(compound, config.models):
            table, _ = cross_validate(laps, spec, folds, config.validation.anchor_laps, implementation)
            folds_tables.append(table.assign(compound=compound))
    inputs = build_strategy_inputs(strategy_data.all_laps, strategy_data.clean, config, names)
    _, ranking = compare_strategies(inputs.models, inputs.total_laps, inputs.pit_loss, config.k_fuel)
    return pd.concat(folds_tables, ignore_index=True), ranking


def bench_profile(perf, config, names):
    # Data preparation (I/O bound) is timed separately, then excluded from the comparison.
    strategy_races = [r for r in config.races if r.year in config.strategy.data_years]
    # Data preparation reads the warm caches (no network). It is I/O and
    # parsing, timed separately with fewer repeats and NOT optimised (D79).
    prep_timing = time_function(lambda: prepare_laps(config, config.train_races), 3, 1)
    train = prepare_laps(config, config.train_races)
    strategy_data = prepare_laps(config, strategy_races)

    results, timings, rows = {}, {}, []
    # Profile and time the original (loop) and the vectorised versions.
    for implementation in ("loop", "vectorised"):
        def run(implementation=implementation):
            # The default argument fixes this loop's implementation inside the function.
            return compute_pipeline(config, train, strategy_data, names, implementation)
        results[implementation], table = profile_function(run, top=perf.profile_top)
        table.to_csv(REPORTS / f"phase8_profile_{'before' if implementation == 'loop' else 'after'}.csv",
                     index=False)
        timings[implementation] = time_function(run, perf.repeats, perf.warmup, perf.min_time_per_repeat_s)

    # The two versions must give the same results: largest difference in metrics and race times.
    before_folds, before_rank = results["loop"]
    after_folds, after_rank = results["vectorised"]
    metric_columns = ["rmse", "mae", "max_abs_error", "bias", "r_squared"]
    applicable = before_folds["applicable"].astype(bool)
    difference = float(np.nanmax(np.abs(before_folds.loc[applicable, metric_columns].to_numpy(float)
                                        - after_folds.loc[applicable, metric_columns].to_numpy(float))))
    rank_difference = float(np.max(np.abs(before_rank["total_time"].to_numpy() - after_rank["total_time"].to_numpy())))
    # Time per version and the speed-up.
    for implementation, label in (("loop", "before (stint-by-stint loop)"), ("vectorised", "after (vectorised)")):
        t = timings[implementation]
        rows.append({"version": label, "time_mean_s": t.mean, "time_std_s": t.std, "time_min_s": t.minimum,
                     "repeats": t.repeats})
    table = pd.DataFrame(rows)
    table["speedup_vs_before"] = table["time_mean_s"].iloc[0] / table["time_mean_s"]
    table["max_abs_difference_cv_metrics"] = difference
    table["max_abs_difference_strategy_times_s"] = rank_difference
    table["data_preparation_mean_s"] = prep_timing.mean
    table["data_preparation_std_s"] = prep_timing.std
    table.to_csv(REPORTS / "phase8_optimisation.csv", index=False)
    return table


def main(config=None, sections=None, output_dir=None):
    """Run the benchmarks.

    ``sections`` defaults to the command-line arguments (or all sections);
    ``output_dir`` replaces reports/ so that a pipeline run does not overwrite
    the committed Phase 8 evidence (D80) with this machine's timings.
    """
    # Redirect the outputs if requested (the pipeline writes to benchmarks_latest).
    global REPORTS, FIGURES
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    if config is None:
        config = load_config(REPO_ROOT / "config.yaml")
    if output_dir is not None:
        REPORTS = Path(output_dir)
        FIGURES = REPORTS / "figures"
    perf = config.performance
    FIGURES.mkdir(parents=True, exist_ok=True)
    # Save the machine details next to the timings.
    info = machine_info()
    (REPORTS / "phase8_machine.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("Machine:", info)

    # Sections to run: from the caller, the command line, or all.
    if sections is None:
        sections = sys.argv[1:] or ["ode", "knn", "least_squares", "strategy", "profile"]
    # The frozen model selection is needed for the strategy benchmarks.
    from tyredeg.validation import load_selection
    selection = load_selection(REPO_ROOT / config.validation.selection_file)["selection"]
    names = {c: selection[c]["selected"] for c in config.strategy.compounds}
    pd.set_option("display.width", 220)
    # Run the requested sections and print their tables.
    if "ode" in sections:
        print("\nODE solvers:\n", bench_ode(perf).round(8).to_string(index=False))
    if "knn" in sections:
        print("\nKNN:\n", bench_knn(perf, config.random_seed).round(6).to_string(index=False))
    if "least_squares" in sections:
        print("\nLeast squares:\n", bench_least_squares(perf).to_string(index=False))
    if "strategy" in sections:
        strategy_races = [r for r in config.races if r.year in config.strategy.data_years]
        prepared = prepare_laps(config, strategy_races)
        print("\nStrategy optimiser:\n", bench_strategy(perf, config, prepared, names).round(6).to_string(index=False))
    if "profile" in sections:
        print("\nOptimisation (before/after):\n", bench_profile(perf, config, names).to_string(index=False))


if __name__ == "__main__":
    main()
