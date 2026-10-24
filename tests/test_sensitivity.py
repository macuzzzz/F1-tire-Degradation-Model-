"""Tests for tyredeg.sensitivity: coefficients of analytic functions match exact derivatives."""

import numpy as np
import pandas as pd
import pytest

from tyredeg.sensitivity import (
    degradation_rate_vs_fuel,
    one_at_a_time,
    sensitivity_coefficient,
    step_size_check,
    tornado_table,
)
from tyredeg.strategy import CompoundModel, LinearDegradation, cumulative_degradation, optimise_continuous


# ---------------------------------------------------------------------------
# Sensitivity coefficients vs exact derivatives
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "func, derivative, x0",
    [
        (lambda x: 3 * x**2 + 2, lambda x: 6 * x, 2.0),        # dy/dx = 12, S = 12*2/14
        (np.exp, np.exp, 0.7),                                  # S = x for exp
        (lambda x: 5 * x + 1, lambda x: 5.0, 4.0),              # linear: exact for any h
        (lambda x: x**3, lambda x: 3 * x**2, -1.5),             # S = 3 for any power x^3
        (np.log, lambda x: 1 / x, 2.5),
    ],
)
def test_coefficient_matches_exact_derivative(func, derivative, x0):
    result = sensitivity_coefficient(func, x0, relative_step=1e-3)
    assert result.derivative == pytest.approx(derivative(x0), rel=1e-6)
    assert result.elasticity == pytest.approx(derivative(x0) * x0 / func(x0), rel=1e-6)
    assert result.y0 == pytest.approx(func(x0))


def test_known_elasticities():
    # Power law y = c x^p has elasticity exactly p, at any x.
    assert sensitivity_coefficient(lambda x: 7 * x**2.5, 3.0, relative_step=1e-4).elasticity \
        == pytest.approx(2.5, rel=1e-7)
    # Exponential y = e^x has elasticity x.
    assert sensitivity_coefficient(np.exp, 2.0, relative_step=1e-4).elasticity == pytest.approx(2.0, rel=1e-7)


def test_central_difference_error_is_second_order():
    # Error of the central difference ~ h^2 y'''/6: halving h quarters it.
    func, x0, exact = np.exp, 1.0, np.exp(1.0)
    errors = [abs(sensitivity_coefficient(func, x0, relative_step=h).derivative - exact) for h in (0.1, 0.05)]
    assert errors[0] / errors[1] == pytest.approx(4.0, rel=0.02)


def test_absolute_step_and_zero_cases():
    result = sensitivity_coefficient(lambda x: x**2 + 1, 0.0, absolute_step=0.01)
    assert result.derivative == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(result.elasticity)  # x0 = 0: elasticity undefined
    assert np.isnan(sensitivity_coefficient(lambda x: x - 2, 2.0, relative_step=0.01).elasticity)  # y0 = 0


@pytest.mark.parametrize(
    "kwargs",
    [dict(), dict(relative_step=0.01, absolute_step=0.01), dict(relative_step=0.0),
     dict(absolute_step=-1.0)],
)
def test_invalid_steps(kwargs):
    with pytest.raises(ValueError):
        sensitivity_coefficient(lambda x: x, 1.0, **kwargs)


def test_relative_step_at_zero_is_rejected():
    with pytest.raises(ValueError, match="x0 = 0"):
        sensitivity_coefficient(lambda x: x, 0.0, relative_step=0.01)


def test_step_size_check_detects_a_kink():
    # |x - 1| has a kink at 1: from x0 = 1.05 a large step straddles it.
    table = step_size_check(lambda x: abs(x - 1.0), 1.05, [0.001, 0.01, 0.1])
    assert table["derivative"].iloc[0] == pytest.approx(1.0)
    assert table["derivative"].iloc[2] < 0.9  # the 10 % step crosses the kink


# ---------------------------------------------------------------------------
# One-at-a-time and tornado
# ---------------------------------------------------------------------------
def evaluate(a=1.0, b=2.0):
    return {"y": a * b, "z": a + b}


def test_one_at_a_time_and_tornado():
    oat = one_at_a_time(evaluate, [("a", "low", {"a": 0.5}), ("a", "high", {"a": 2.0}),
                                   ("b", "low", {"b": 1.9}), ("b", "high", {"b": 2.1})])
    assert oat["y"].tolist() == pytest.approx([2.0, 1.0, 4.0, 1.9, 2.1])
    table = tornado_table(oat, "y")
    assert table["input"].tolist() == ["a", "b"]           # a moves y most
    assert table.iloc[0]["low_change"] == pytest.approx(-1.0)
    assert table.iloc[0]["high_change"] == pytest.approx(2.0)
    assert table.iloc[0]["span"] == pytest.approx(3.0)


def test_tornado_includes_nominal_when_both_variations_move_the_same_way():
    oat = pd.DataFrame({"input": ["nominal", "m", "m"], "label": ["n", "x", "y"], "y": [5.0, 6.0, 7.0]})
    row = tornado_table(oat, "y").iloc[0]
    assert (row["low"], row["high"], row["low_change"]) == (5.0, 7.0, 0.0)


# ---------------------------------------------------------------------------
# Strategy-specific checks used in Phase 7
# ---------------------------------------------------------------------------
def test_linear_degradation_integral_and_optimum_sensitivity():
    # Analytic one-stop optimum L* = (b2 - b1 + a2 (N + 1/2) - a1 / 2) / (a1 + a2).
    def l_star(a1, a2=0.09, b1=80.0, b2=79.7, n=70):
        return (b2 - b1 + a2 * (n + 0.5) - a1 / 2) / (a1 + a2)

    def numeric(a1):
        models = {"C3": CompoundModel("C3", LinearDegradation(a1), 80.0, 69),
                  "C4": CompoundModel("C4", LinearDegradation(0.09), 79.7, 69)}
        return optimise_continuous("C3", "C4", models, 70, 21.0, xtol=1e-10).continuous_root

    assert numeric(0.06) == pytest.approx(l_star(0.06), abs=1e-6)
    # dL*/da1 from my central difference vs the exact derivative of the formula.
    exact = -(0.5 * (0.06 + 0.09) + (-0.3 + 0.09 * 70.5 - 0.03)) / (0.06 + 0.09) ** 2
    result = sensitivity_coefficient(numeric, 0.06, relative_step=0.01)
    assert result.derivative == pytest.approx(exact, rel=1e-4)
    assert cumulative_degradation(LinearDegradation(0.1), 4.0) == pytest.approx(0.1 * 10)


def test_margin_against_pit_loss_has_slope_minus_one():
    # Two stops minus one stop has one more pit loss: d(margin)/dP = -1 exactly
    # (while the optimal laps do not change).
    from tyredeg.strategy import optimise_brute_force, optimise_two_stop

    models = {"C3": CompoundModel("C3", LinearDegradation(0.06), 80.0, 69),
              "C4": CompoundModel("C4", LinearDegradation(0.09), 79.7, 69)}

    def margin(pit_loss):
        one = optimise_brute_force("C3", "C4", models, 70, pit_loss).total_time
        two = optimise_two_stop(("C3", "C4", "C3"), models, 70, pit_loss).total_time
        return one - two

    assert sensitivity_coefficient(margin, 21.0, relative_step=0.001).derivative == pytest.approx(-1.0)


def synthetic_clean(rate=0.06, nominal_k=0.046, seed=42):
    """Stints at different points of a 70-lap race; true wear rate known."""
    rng = np.random.default_rng(seed)
    rows = []
    for stint in range(30):
        start = int(rng.integers(2, 40))
        for i in range(int(rng.integers(12, 25))):
            lap, age = start + i, 2.0 + i
            raw = 85.0 + rate * age - 0.05 * (lap - 1) + rng.normal(0, 0.3)
            rows.append({"LapNumber": float(lap), "TyreLife": age, "PirelliCompound": "C3",
                         "StintId": f"s{stint}", "LapTime": raw,
                         "FuelCorrectedTime": raw + nominal_k * (lap - 1)})
    return pd.DataFrame(rows)


def test_fitted_rate_rises_one_for_one_with_fuel_coefficient():
    # Within a stint, lap number = tyre age + constant, so d(rate)/dk = 1 exactly.
    rates, slope = degradation_rate_vs_fuel(synthetic_clean(), "C3", [0.0, 0.02, 0.046, 0.07], 0.046)
    assert slope == pytest.approx(1.0, abs=1e-9)
    np.testing.assert_allclose(np.diff(rates["rate"]), np.diff(rates["k_fuel"]), atol=1e-9)
    with pytest.raises(ValueError):
        degradation_rate_vs_fuel(synthetic_clean(), "C4", [0.0], 0.046)
