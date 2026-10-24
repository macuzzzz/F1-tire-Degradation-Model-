"""Phase 3 accuracy study of the from-scratch numerical methods.

Run from the repository root:

    .venv\\Scripts\\python scripts/numerics_study.py

Produces CSV tables in ``reports/`` and figures in ``reports/figures/``:

1. ``phase3_ode_fixed_step``   - error vs step size h for Euler, Heun, RK4
                                 (finds the h with the smallest error).
2. ``phase3_rk45``             - RK45 error vs function evaluations for a range
                                 of tolerances and step-controller settings,
                                 compared with SciPy.
3. ``phase3_finite_differences`` - error vs h ("V-curves"), theoretical vs
                                 empirical optimal step.
4. ``phase3_root_finding``     - error vs iteration, and a comparison of
                                 stopping rules.
5. ``phase3_least_squares``    - normal equations vs QR vs SVD on polynomial
                                 fits of increasing degree, scaled and unscaled.

No randomness is used, so the results are exactly reproducible.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only; no window needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.integrate import solve_ivp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tyredeg.numerics import differentiation as fd  # noqa: E402
from tyredeg.numerics.least_squares import (  # noqa: E402
    fit_linear_least_squares,
    fit_linear_least_squares_qr,
    polynomial_design_matrix,
)
from tyredeg.numerics.linear_solvers import NearSingularWarning  # noqa: E402
from tyredeg.numerics.ode_solvers import euler, heun, rk4, rk45  # noqa: E402
from tyredeg.numerics.root_finding import bisection, newton, secant  # noqa: E402

REPORTS = REPO_ROOT / "reports"
FIGURES = REPORTS / "figures"

# Wear-like test problem (same form as the Phase 4 model): dd/dn = a + b d,
# d(0) = 0 over a 40-lap stint, exact solution d(n) = (a/b)(exp(b n) - 1).
A_WEAR, B_WEAR, LAPS = 0.05, 0.03, 40.0


def wear_rhs(t, d):
    return A_WEAR + B_WEAR * d


WEAR_EXACT = A_WEAR / B_WEAR * (np.exp(B_WEAR * LAPS) - 1.0)


# ---------------------------------------------------------------------------
# 1. Fixed-step ODE solvers: error vs h
# ---------------------------------------------------------------------------
def study_fixed_step():
    rows = []
    step_counts = 2 ** np.arange(2, 17)  # 4 ... 65536 steps over 40 laps
    for name, solver in (("Euler", euler), ("Heun", heun), ("RK4", rk4)):
        for n in step_counts:
            h = LAPS / n
            _, d, nfev = solver(wear_rhs, (0.0, LAPS), 0.0, h)
            rows.append({"method": name, "h": h, "nfev": nfev,
                         "error": abs(d[-1] - WEAR_EXACT)})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase3_ode_fixed_step.csv", index=False)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    summary = []
    for name, group in table.groupby("method", sort=False):
        ax.loglog(group["h"], group["error"], "o-", label=name)
        best = group.loc[group["error"].idxmin()]
        ax.plot(best["h"], best["error"], "k*", markersize=12)
        within_1ms = group[group["error"] <= 1e-3]
        summary.append({
            "method": name,
            "h_min_error": best["h"],
            "min_error": best["error"],
            "largest_h_error_below_1ms": within_1ms["h"].max() if len(within_1ms) else np.nan,
        })
    ax.axhline(1e-3, color="grey", linestyle="--", label="1 ms (timing resolution)")
    ax.set_xlabel("step size h [laps]")
    ax.set_ylabel("|error at lap 40| [s]")
    ax.set_title("Fixed-step solvers on dd/dn = 0.05 + 0.03 d (star = smallest error)")
    ax.legend()
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_ode_fixed_step.png", dpi=150)
    plt.close(fig)
    return pd.DataFrame(summary)


# ---------------------------------------------------------------------------
# 2. RK45: accuracy vs cost, controller settings, SciPy
# ---------------------------------------------------------------------------
def study_rk45():
    controllers = {
        "approved (0.9, 0.2, 10)": dict(safety=0.9, min_factor=0.2, max_factor=10.0),
        "conservative (0.8, 0.2, 5)": dict(safety=0.8, min_factor=0.2, max_factor=5.0),
        "cautious growth (0.9, 0.2, 2)": dict(safety=0.9, min_factor=0.2, max_factor=2.0),
    }
    rows = []
    for rtol in 10.0 ** -np.arange(2, 13):
        atol = rtol * 1e-3
        for label, settings in controllers.items():
            _, d, nfev, stats = rk45(wear_rhs, (0.0, LAPS), 0.0, rtol=rtol, atol=atol, **settings)
            rows.append({"solver": label, "rtol": rtol, "nfev": nfev,
                         "rejected": stats.n_rejected, "error": abs(d[-1] - WEAR_EXACT)})
        reference = solve_ivp(wear_rhs, (0.0, LAPS), [0.0], method="RK45", rtol=rtol, atol=atol)
        rows.append({"solver": "SciPy RK45", "rtol": rtol, "nfev": reference.nfev, "rejected": np.nan,
                     "error": abs(reference.y[0, -1] - WEAR_EXACT)})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase3_rk45.csv", index=False)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for label, group in table.groupby("solver", sort=False):
        style = "k--x" if label == "SciPy RK45" else "o-"
        ax.loglog(group["nfev"], group["error"], style, label=label)
    ax.axhline(1e-3, color="grey", linestyle=":", label="1 ms")
    ax.set_xlabel("function evaluations")
    ax.set_ylabel("|error at lap 40| [s]")
    ax.set_title("RK45: error vs cost for rtol = 1e-2 ... 1e-12")
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_rk45.png", dpi=150)
    plt.close(fig)
    return table


# ---------------------------------------------------------------------------
# 3. Finite differences: error vs h
# ---------------------------------------------------------------------------
def study_finite_differences():
    formulas = {
        "forward": (fd.forward_difference, np.cos, fd.FORWARD_STEP_EXPONENT),
        "backward": (fd.backward_difference, np.cos, fd.FORWARD_STEP_EXPONENT),
        "central": (fd.central_difference, np.cos, fd.CENTRAL_STEP_EXPONENT),
        "central 2nd": (fd.central_second_difference, lambda x: -np.sin(x), fd.SECOND_STEP_EXPONENT),
    }
    steps = np.logspace(-12, -1, 221)
    rows, summary = [], []
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for ax, x in zip(axes, (1.0, 10.0)):
        for name, (method, exact, exponent) in formulas.items():
            errors = np.array([abs(method(np.sin, x, h) - exact(x)) for h in steps])
            for h, error in zip(steps, errors):
                rows.append({"x": x, "formula": name, "h": h, "error": error})
            # Smooth the noisy round-off region with a 9-point running median
            # before locating the minimum, so one lucky value does not decide.
            smooth = pd.Series(errors).rolling(9, center=True, min_periods=1).median().to_numpy()
            h_empirical = steps[int(np.argmin(smooth))]
            h_default = float(fd.default_step(x, exponent))
            error_default = abs(method(np.sin, x) - exact(x))
            summary.append({"x": x, "formula": name, "h_theory": h_default,
                            "h_empirical": h_empirical,
                            "ratio_empirical_to_theory": h_empirical / h_default,
                            "error_at_default": error_default,
                            "min_smoothed_error": float(np.min(smooth))})
            if name != "backward":
                line, = ax.loglog(steps, errors, label=name, linewidth=1)
                ax.axvline(h_default, color=line.get_color(), linestyle="--", linewidth=0.8)
        ax.set_title(f"d/dx sin(x) at x = {x:g} (dashed = default h)")
        ax.set_xlabel("step h")
        ax.grid(True, which="both", alpha=0.3)
    axes[0].set_ylabel("|error|")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_finite_differences.png", dpi=150)
    plt.close(fig)
    pd.DataFrame(rows).to_csv(REPORTS / "phase3_finite_differences.csv", index=False)
    return pd.DataFrame(summary)


# ---------------------------------------------------------------------------
# 4. Root finding: convergence and stopping rules
# ---------------------------------------------------------------------------
def study_root_finding():
    root = np.sqrt(2.0)
    f = lambda x: x**2 - 2.0  # noqa: E731
    fprime = lambda x: 2.0 * x  # noqa: E731
    histories = {
        "bisection": bisection(f, 1.0, 2.0).history,
        "secant": secant(f, 1.0, 2.0).history,
        "newton": newton(f, fprime, 1.0).history,
    }
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for name, history in histories.items():
        errors = np.maximum(np.abs(history - root), 1e-17)
        ax.semilogy(np.arange(len(errors)), errors, "o-", label=name)
    ax.set_xlabel("iteration")
    ax.set_ylabel("|x_k - sqrt(2)|")
    ax.set_title("Root finding on x^2 - 2 (default tolerances)")
    ax.legend()
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_root_finding.png", dpi=150)
    plt.close(fig)

    # Stopping rules: step only (ftol = 0), residual only (xtol = 0), either.
    problems = {
        "x^2 - 2 (simple root)": (f, fprime, 1.0, 2.0, root),
        "(x - 1)^3 (flat, triple root)": (lambda x: (x - 1.0) ** 3, lambda x: 3.0 * (x - 1.0) ** 2,
                                          0.5, 1.7, 1.0),
        "exp(10 x) - 2 (steep)": (lambda x: np.exp(10 * x) - 2.0, lambda x: 10 * np.exp(10 * x),
                                  0.0, 0.2, np.log(2.0) / 10),
    }
    rules = {"step only": dict(ftol=0.0), "residual only": dict(xtol=0.0), "either (approved)": {}}
    rows = []
    for problem, (g, gprime, a, b, true_root) in problems.items():
        for rule, tolerances in rules.items():
            runs = {
                "bisection": lambda: bisection(g, a, b, max_iter=200, **tolerances),
                "secant": lambda: secant(g, a, b, max_iter=200, **tolerances),
                "newton": lambda: newton(g, gprime, b, max_iter=200, **tolerances),
            }
            for method, run in runs.items():
                try:
                    result = run()
                    rows.append({"problem": problem, "rule": rule, "method": method,
                                 "iterations": result.iterations,
                                 "abs_error": abs(result.root - true_root), "status": "ok"})
                except ValueError as error:
                    rows.append({"problem": problem, "rule": rule, "method": method,
                                 "iterations": np.nan, "abs_error": np.nan,
                                 "status": type(error).__name__})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase3_root_finding_stopping_rules.csv", index=False)
    return table


# ---------------------------------------------------------------------------
# 5. Least squares: normal equations vs QR vs SVD
# ---------------------------------------------------------------------------
def scaled_coefficients(unscaled, centre, half_range):
    """Coefficients b_k of sum_k b_k s^k equal to sum_j a_j x^j with x = c + r s."""
    from math import comb

    scaled = np.zeros(len(unscaled))
    for j, a_j in enumerate(unscaled):
        for k in range(j + 1):
            scaled[k] += a_j * comb(j, k) * centre ** (j - k) * half_range**k
    return scaled


def study_least_squares():
    age = np.arange(1, 42, dtype=float)  # tyre ages 1-41 laps, as in the data
    rows = []
    for degree in range(1, 7):
        # Noise-free data from known coefficients, so the exact answer is known.
        true_unscaled = np.array([80.0, 0.05] + [1e-4 * (-1) ** k for k in range(degree - 1)])
        y = polynomial_design_matrix(age, degree) @ true_unscaled
        for scaled in (False, True):
            centre, half_range = (21.0, 20.0) if scaled else (0.0, 1.0)
            X = polynomial_design_matrix(age, degree, centre, half_range)
            # Reference coefficients in this basis: substitute x = c + r s into
            # sum_j a_j x^j and expand with the binomial theorem (exact algebra,
            # no ill-conditioned solve), so the reference is not the weak link.
            reference = scaled_coefficients(true_unscaled, centre, half_range)
            methods = {
                "normal (mine)": lambda: fit_linear_least_squares(X, y).coefficients,
                "QR (numpy QR + my back subst.)": lambda: fit_linear_least_squares_qr(X, y).coefficients,
                "SVD (numpy lstsq)": lambda: np.linalg.lstsq(X, y, rcond=None)[0],
            }
            for method, run in methods.items():
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", NearSingularWarning)
                    beta = run()
                relative_error = np.linalg.norm(beta - reference) / np.linalg.norm(reference)
                rows.append({"degree": degree, "scaled": scaled, "method": method,
                             "cond_X": np.linalg.cond(X), "relative_error": relative_error,
                             "warned": any(issubclass(w.category, NearSingularWarning) for w in caught)})
    table = pd.DataFrame(rows)
    table.to_csv(REPORTS / "phase3_least_squares.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for ax, scaled in zip(axes, (False, True)):
        subset = table[table["scaled"] == scaled]
        for method, group in subset.groupby("method", sort=False):
            ax.semilogy(group["degree"], np.maximum(group["relative_error"], 1e-17), "o-", label=method)
        ax.set_title("scaled x in [-1, 1]" if scaled else "unscaled x = tyre age 1-41")
        ax.set_xlabel("polynomial degree")
        ax.grid(True, which="both", alpha=0.3)
    axes[0].set_ylabel("relative coefficient error")
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_least_squares.png", dpi=150)
    plt.close(fig)
    return table


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda v: f"{v:.3g}")
    print("1. Fixed-step ODE solvers (wear ODE, 40 laps)\n", study_fixed_step().to_string(index=False))
    rk = study_rk45()
    print("\n2. RK45 (error at lap 40)\n",
          rk.pivot_table(index="rtol", columns="solver", values=["nfev", "error"]).to_string())
    print("\n3. Finite differences\n", study_finite_differences().to_string(index=False))
    print("\n4. Root finding stopping rules\n",
          study_root_finding().pivot_table(index=["problem", "method"], columns="rule",
                                           values=["iterations", "abs_error"]).to_string())
    ls = study_least_squares()
    print("\n5. Least squares (relative coefficient error)\n",
          ls.pivot_table(index=["scaled", "degree"], columns="method",
                         values="relative_error").to_string())
    print("   near-singular warnings issued for:",
          ls.loc[ls["warned"], ["degree", "scaled", "method"]].values.tolist())


if __name__ == "__main__":
    main()
