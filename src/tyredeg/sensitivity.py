"""Sensitivity analysis of the strategy result (Phase 7, DECISIONS.md D67-D73).

Two complementary tools:

1. **One-at-a-time (OAT) ranges.** Each input is set to a low and a high
   value while every other input stays at its nominal value, and the outputs
   are recomputed. A tornado plot ranks the inputs by how far they move an
   output. This also works for categorical inputs (the choice of model) and
   for outputs that only take integer values (the optimal pit lap).

2. **Local sensitivity coefficients** by my central difference:

       dy/dx ~ (y(x + h) - y(x - h)) / (2h)

   and the dimensionless elasticity

       S = (dy/dx) * (x / y)  = relative change in y / relative change in x,

   e.g. S = 2 means "1 % more x gives 2 % more y". Elasticity is undefined
   when x or y is 0 (returned as NaN); then the plain derivative is used.

The optimal pit lap is an integer, so a finite difference of it is usually
0 and occasionally a jump of 1 lap: meaningless as a derivative. Derivatives
are therefore taken of SMOOTH outputs only: the continuous optimum L* from
the relaxation (Phase 6), and the race times. The integer pit lap is
reported only through the OAT ranges (D69).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tyredeg.models.polynomial import PolynomialDegradationModel
from tyredeg.numerics.differentiation import central_difference
from tyredeg.numerics.least_squares import fit_linear_least_squares

# Default relative perturbation for central differences (D68).
DEFAULT_RELATIVE_STEP = 0.01


@dataclass(frozen=True)
class SensitivityResult:
    """A local sensitivity coefficient.

    Attributes
    ----------
    x0, y0 : float
        Nominal input and output.
    step : float
        Perturbation h used in the central difference (same unit as x).
    derivative : float
        dy/dx (units of y per unit of x).
    elasticity : float
        (dy/dx) x0 / y0 (dimensionless); NaN if x0 or y0 is 0.
    """

    x0: float
    y0: float
    step: float
    derivative: float
    elasticity: float


def sensitivity_coefficient(func, x0, relative_step=None, absolute_step=None):
    """Derivative and elasticity of ``func`` at ``x0`` by my central difference.

    Parameters
    ----------
    func : callable
        Scalar function y = func(x).
    x0 : float
        Nominal input, finite.
    relative_step : float, optional
        Step h = relative_step * |x0| (> 0; needs x0 != 0).
    absolute_step : float, optional
        Step h in the units of x (> 0). Exactly one of the two must be given.

    Returns
    -------
    SensitivityResult

    Raises
    ------
    ValueError
        If both or neither step is given, a step is <= 0, x0 is not finite,
        or a relative step is requested at x0 = 0.

    Example
    -------
    >>> r = sensitivity_coefficient(lambda x: x**2, 3.0, relative_step=0.01)
    >>> round(r.derivative, 9), round(r.elasticity, 9)   # exact: 6 and 2
    (6.0, 2.0)
    """
    if (relative_step is None) == (absolute_step is None):
        raise ValueError("Give exactly one of relative_step and absolute_step.")
    x0 = float(x0)
    if not np.isfinite(x0):
        raise ValueError(f"x0 must be finite, got {x0}.")
    if relative_step is not None:
        if not relative_step > 0:
            raise ValueError(f"relative_step must be > 0, got {relative_step}.")
        if x0 == 0:
            raise ValueError("A relative step is undefined at x0 = 0; use absolute_step.")
        step = relative_step * abs(x0)
    else:
        if not absolute_step > 0:
            raise ValueError(f"absolute_step must be > 0, got {absolute_step}.")
        step = float(absolute_step)
    y0 = float(func(x0))
    derivative = float(central_difference(func, x0, step))
    elasticity = derivative * x0 / y0 if x0 != 0 and y0 != 0 else float("nan")
    return SensitivityResult(x0, y0, step, derivative, elasticity)


def step_size_check(func, x0, relative_steps):
    """Derivative estimated with several relative steps (to detect step-size problems).

    Too small a step amplifies round-off; too large a step adds truncation
    error or straddles a kink. Agreement across steps shows the estimate is
    trustworthy.

    Returns
    -------
    pandas.DataFrame
        Columns relative_step, step, derivative.

    Example
    -------
    >>> table = step_size_check(lambda x: 2 * x + 1, 5.0, [0.1, 0.01])
    >>> table["derivative"].round(9).tolist()
    [2.0, 2.0]
    """
    rows = []
    for relative in relative_steps:
        result = sensitivity_coefficient(func, x0, relative_step=relative)
        rows.append({"relative_step": relative, "step": result.step, "derivative": result.derivative})
    return pd.DataFrame(rows)


def one_at_a_time(evaluate, variations):
    """Evaluate the outputs for every one-at-a-time variation.

    Parameters
    ----------
    evaluate : callable
        ``evaluate(**overrides) -> dict`` of outputs; with no overrides it
        must return the nominal outputs.
    variations : sequence of (input, label, overrides)
        E.g. ``("pit loss", "q25", {"pit_loss": 19.8})``.

    Returns
    -------
    pandas.DataFrame
        One row per variation plus a first "nominal" row; columns input,
        label, then every output.

    Example
    -------
    >>> f = lambda x=1.0: {"y": 2 * x}
    >>> one_at_a_time(f, [("x", "low", {"x": 0.5})])["y"].tolist()
    [2.0, 1.0]
    """
    rows = [{"input": "nominal", "label": "nominal", **evaluate()}]
    for name, label, overrides in variations:
        rows.append({"input": name, "label": label, **evaluate(**overrides)})
    return pd.DataFrame(rows)


def tornado_table(oat, output):
    """Lowest and highest value of ``output`` per input, sorted by span (largest first).

    Parameters
    ----------
    oat : pandas.DataFrame
        Output of :func:`one_at_a_time` (first row = nominal).
    output : str
        Column to analyse.

    Returns
    -------
    pandas.DataFrame
        Columns input, low, high, low_change, high_change (relative to the
        nominal), span = high - low.

    Example
    -------
    >>> oat = pd.DataFrame({"input": ["nominal", "a", "a", "b"], "label": ["n", "l", "h", "h"],
    ...                     "y": [1.0, 0.0, 3.0, 1.5]})
    >>> tornado_table(oat, "y")["input"].tolist()
    ['a', 'b']
    """
    nominal = float(oat[oat["input"] == "nominal"][output].iloc[0])
    rows = []
    for name, group in oat[oat["input"] != "nominal"].groupby("input", sort=False):
        values = group[output].astype(float).dropna()
        if values.empty:
            continue
        low, high = float(min(values.min(), nominal)), float(max(values.max(), nominal))
        rows.append({"input": name, "low": low, "high": high, "low_change": low - nominal,
                     "high_change": high - nominal, "span": high - low})
    table = pd.DataFrame(rows)
    return table.sort_values("span", ascending=False).reset_index(drop=True)


def plot_tornado(table, nominal, title, xlabel, path):
    """Horizontal tornado bars (largest span on top), saved to ``path``."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 0.45 * len(table) + 1.6))
    positions = np.arange(len(table))[::-1]
    ax.barh(positions, table["high_change"], left=nominal, color="tab:red", label="raises output")
    ax.barh(positions, table["low_change"], left=nominal, color="tab:blue", label="lowers output")
    ax.axvline(nominal, color="black", linewidth=1)
    ax.set_yticks(positions)
    ax.set_yticklabels(table["input"])
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def degradation_rate_vs_fuel(clean, compound, k_values, nominal_k):
    """Refit the linear degradation rate for several fuel coefficients.

    The fuel-corrected time is t + k (n - 1). Within ONE stint, lap number n
    and tyre age rise together (n = age + constant), so changing k by dk
    adds dk * age + constant to every lap of the stint: the constant goes
    into the stint offset and the degradation slope rises by exactly dk.
    The fitted rate therefore satisfies d(rate)/dk = 1: the data within a
    stint cannot separate fuel burn from tyre wear (D72).

    Parameters
    ----------
    clean : pandas.DataFrame
        Clean laps with LapTime, LapNumber, TyreLife, PirelliCompound, StintId
        and a fuel-corrected time computed with ``nominal_k``.
    compound : str
    k_values : sequence of float
        Fuel coefficients to test [s per lap of fuel], >= 0.
    nominal_k : float
        The k used for the existing FuelCorrectedTime column.

    Returns
    -------
    rates : pandas.DataFrame
        Columns k_fuel, rate.
    slope : float
        d(rate)/dk from a straight-line fit (my least squares).

    Example
    -------
    >>> rates, slope = degradation_rate_vs_fuel(clean, "C3", [0.0, 0.046, 0.07], 0.046)  # doctest: +SKIP
    >>> round(slope, 6)  # doctest: +SKIP
    1.0
    """
    laps = clean[clean["PirelliCompound"] == compound]
    if laps.empty:
        raise ValueError(f"No laps of compound {compound}.")
    rows = []
    for k_fuel in k_values:
        # Undo the nominal correction and apply the new one (exact, no refetch).
        time = laps["FuelCorrectedTime"].to_numpy(float) + (k_fuel - nominal_k) * (laps["LapNumber"].to_numpy(float) - 1)
        model = PolynomialDegradationModel(compound, degree=1).fit(laps["TyreLife"], time, laps["StintId"])
        rows.append({"k_fuel": float(k_fuel), "rate": float(model.params()["coefficients"][0])})
    rates = pd.DataFrame(rows)
    design = np.column_stack([np.ones(len(rates)), rates["k_fuel"].to_numpy()])
    slope = float(fit_linear_least_squares(design, rates["rate"].to_numpy()).coefficients[1])
    return rates, slope
