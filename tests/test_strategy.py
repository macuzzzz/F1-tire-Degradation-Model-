"""Tests for tyredeg.strategy (race-time model and pit-stop optimisation).

Analytic case used throughout (linear degradation, new tyres every stint):
compound A ("C3"): base b1 = 80.0 s, rate a1 = 0.06 s/lap
compound B ("C4"): base b2 = 79.7 s, rate a2 = 0.09 s/lap
race N = 70 laps, pit loss P = 21 s.

With L laps on A and M = N - L on B, the race time is
    T(L) = b1 L + a1 L(L+1)/2 + b2 M + a2 M(M+1)/2 + P
(sum of j over a stint = n(n+1)/2). Setting dT/dL = 0:
    b1 + a1 (L + 1/2) - b2 - a2 (M + 1/2) = 0
    L* = (b2 - b1 + a2 (N + 1/2) - a1/2) / (a1 + a2)
       = (-0.3 + 0.09 * 70.5 - 0.03) / 0.15 = 6.015 / 0.15 = 40.1 laps.
T is a convex parabola in L, symmetric about 40.1, so the best integer pit
lap is 40.
"""

import numpy as np
import pandas as pd
import pytest

from tyredeg.models.knn import KNNDegradationModel
from tyredeg.models.polynomial import PolynomialDegradationModel
from tyredeg.models.wear_ode import WearODEModel, exact_degradation
from tyredeg.strategy import (
    CompoundModel,
    compare_strategies,
    compound_pace_delta,
    cumulative_degradation,
    feasible_pit_laps,
    fuel_effect_total,
    max_stint_from_data,
    optimise_brute_force,
    optimise_continuous,
    optimise_two_stop,
    race_time,
    race_time_continuous,
    stint_time,
    total_race_time,
)

B1, A1, B2, A2, N, P = 80.0, 0.06, 79.7, 0.09, 70, 21.0
L_STAR = (B2 - B1 + A2 * (N + 0.5) - A1 / 2) / (A1 + A2)  # 40.1


def linear_model(compound, rate):
    """A real PolynomialDegradationModel fitted to noise-free linear data: d(n) = rate * n."""
    ages = np.arange(1.0, 11.0)
    return PolynomialDegradationModel(compound, degree=1).fit(ages, 80.0 + rate * ages)


def analytic_models(max_a=69, max_b=69):
    """Analytic compounds; the default limit of N - 1 = 69 laps leaves every pit lap feasible."""
    return {
        "C3": CompoundModel("C3", linear_model("C3", A1), B1, max_a),
        "C4": CompoundModel("C4", linear_model("C4", A2), B2, max_b),
    }


def analytic_time(pit_lap):
    m = N - pit_lap
    return B1 * pit_lap + A1 * pit_lap * (pit_lap + 1) / 2 + B2 * m + A2 * m * (m + 1) / 2 + P


# ---------------------------------------------------------------------------
# Race time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pit_lap", [1, 20, 40, 69])
def test_race_time_matches_analytic_formula(pit_lap):
    assert race_time(pit_lap, "C3", "C4", analytic_models(), N, P, add_fuel_effect=False) == \
        pytest.approx(analytic_time(pit_lap), rel=1e-12)


def test_fuel_effect_shifts_every_strategy_by_the_same_amount():
    models, k_fuel = analytic_models(), 0.046
    for pit_lap in (25, 40, 55):
        with_fuel = race_time(pit_lap, "C3", "C4", models, N, P, k_fuel=k_fuel, add_fuel_effect=True)
        without = race_time(pit_lap, "C3", "C4", models, N, P, k_fuel=k_fuel, add_fuel_effect=False)
        assert without - with_fuel == pytest.approx(k_fuel * N * (N - 1) / 2)
    assert fuel_effect_total(N, k_fuel) == pytest.approx(111.09)
    best_with = optimise_brute_force("C3", "C4", models, N, P, k_fuel, True).pit_laps
    best_without = optimise_brute_force("C3", "C4", models, N, P, k_fuel, False).pit_laps
    assert best_with == best_without


def test_compound_order_is_symmetric():
    # No order-dependent effect is modelled: A for L laps then B equals B first then A.
    models = analytic_models()
    for pit_lap in (10, 33, 60):
        assert race_time(pit_lap, "C3", "C4", models, N, P) == \
            pytest.approx(race_time(N - pit_lap, "C4", "C3", models, N, P))


def test_stint_time_and_total_race_time():
    models = analytic_models()
    assert stint_time(models["C3"], 0) == 0.0
    assert stint_time(models["C3"], 3) == pytest.approx(3 * B1 + A1 * 6)
    three = total_race_time(("C3", "C4", "C3"), (20, 25, 25), models, P, add_fuel_effect=False)
    expected = (20 * B1 + A1 * 210) + (25 * B2 + A2 * 325) + (25 * B1 + A1 * 325) + 2 * P
    assert three == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Optimisation: the analytic case
# ---------------------------------------------------------------------------
def test_brute_force_finds_analytic_optimum():
    result = optimise_brute_force("C3", "C4", analytic_models(), N, P)
    assert result.pit_laps == (40,)
    assert result.stint_lengths == (40, 30)
    assert result.total_time == pytest.approx(analytic_time(40))
    assert result.nfev == 69  # every pit lap 1..69 is feasible here


@pytest.mark.parametrize("root_finder", ["secant", "newton"])
def test_continuous_relaxation_finds_analytic_optimum(root_finder):
    result = optimise_continuous("C3", "C4", analytic_models(), N, P, root_finder=root_finder)
    assert result.continuous_root == pytest.approx(L_STAR, abs=1e-5)
    assert result.pit_laps == (40,)
    assert result.total_time == pytest.approx(analytic_time(40))
    assert not result.constraint_active and result.note == ""
    # T is quadratic, so dT/dL is linear: the root is found in very few steps.
    assert result.iterations <= 3
    assert result.nfev < 69  # far fewer evaluations than brute force


def test_continuous_relaxation_equals_race_time_at_integers_for_linear_models():
    models = analytic_models()
    for pit_lap in (5, 40, 64):
        assert race_time_continuous(float(pit_lap), "C3", "C4", models, N, P) == \
            pytest.approx(race_time(pit_lap, "C3", "C4", models, N, P), rel=1e-12)


def test_rounding_checks_neighbours():
    # Shift L* to 40.5 + 0.4 = 40.9 by changing b2: the best integer is then 41.
    models = analytic_models()
    shifted = {"C3": models["C3"], "C4": CompoundModel("C4", models["C4"].model, B2 + 0.12, 60)}
    brute = optimise_brute_force("C3", "C4", shifted, N, P)
    for finder in ("secant", "newton"):
        assert optimise_continuous("C3", "C4", shifted, N, P, root_finder=finder).pit_laps == brute.pit_laps


def test_stint_limit_moves_optimum_to_window_edge():
    # C4 may run at most 25 laps, so the first stint must be >= 45 laps,
    # but the unconstrained optimum is 40.1: the best feasible lap is 45.
    models = analytic_models(max_a=69, max_b=25)
    assert feasible_pit_laps("C3", "C4", models, N)[0] == 45
    brute = optimise_brute_force("C3", "C4", models, N, P)
    assert brute.pit_laps == (45,)
    for finder in ("secant", "newton"):
        result = optimise_continuous("C3", "C4", models, N, P, root_finder=finder)
        assert result.pit_laps == (45,) and result.constraint_active


def test_no_feasible_one_stop():
    models = analytic_models(max_a=30, max_b=30)  # 30 + 30 < 70
    assert feasible_pit_laps("C3", "C4", models, N).size == 0
    with pytest.raises(ValueError, match="No feasible"):
        optimise_brute_force("C3", "C4", models, N, P)
    with pytest.raises(ValueError, match="No feasible"):
        optimise_continuous("C3", "C4", models, N, P)


# ---------------------------------------------------------------------------
# Other model types
# ---------------------------------------------------------------------------
def test_wear_ode_cumulative_degradation_is_close_to_the_sum():
    ages = np.tile(np.arange(1.0, 31.0), 2)
    model = WearODEModel("C3", solver="exact").fit(ages, 80.0 + exact_degradation(ages, 0.05, 0.03),
                                                   [0] * 30 + [1] * 30)
    for n in (5, 20, 40):
        exact_sum = float(np.sum(model.degradation(np.arange(1.0, n + 1.0))))
        assert cumulative_degradation(model, float(n)) == pytest.approx(exact_sum, rel=1e-3)


def test_wear_ode_continuous_optimum_matches_brute_force():
    ages = np.tile(np.arange(1.0, 31.0), 2)
    ids = [0] * 30 + [1] * 30
    models = {
        "C3": CompoundModel("C3", WearODEModel("C3", solver="exact").fit(
            ages, 80 + exact_degradation(ages, 0.05, 0.02), ids), 80.0, 60),
        "C4": CompoundModel("C4", WearODEModel("C4", solver="exact").fit(
            ages, 80 + exact_degradation(ages, 0.07, 0.03), ids), 79.6, 60),
    }
    brute = optimise_brute_force("C3", "C4", models, N, P)
    for finder in ("secant", "newton"):
        assert optimise_continuous("C3", "C4", models, N, P, root_finder=finder).pit_laps == brute.pit_laps


def test_knn_has_no_continuous_relaxation_but_brute_force_works():
    ages = np.tile(np.arange(1.0, 41.0), 3)
    knn = KNNDegradationModel("C3", k=3).fit(ages, 80 + 0.06 * ages, [0] * 40 + [1] * 40 + [2] * 40)
    models = {"C3": CompoundModel("C3", knn, B1, 40), "C4": analytic_models()["C4"]}
    with pytest.raises(TypeError, match="brute-force"):
        optimise_continuous("C3", "C4", models, N, P)
    assert optimise_brute_force("C3", "C4", models, N, P).pit_laps[0] in feasible_pit_laps("C3", "C4", models, N)
    methods, _ = compare_strategies(models, N, P, include_two_stop=False)
    assert set(methods["method"]) == {"brute force"}


# ---------------------------------------------------------------------------
# Two-stop strategies and comparison
# ---------------------------------------------------------------------------
def test_two_stop_matches_exhaustive_enumeration():
    models = analytic_models()
    result = optimise_two_stop(("C3", "C4", "C3"), models, N, P)
    best = min(
        (total_race_time(("C3", "C4", "C3"), (a, b, N - a - b), models, P), a, b)
        for a in range(1, N - 1) for b in range(1, N - a)
    )
    assert result.total_time == pytest.approx(best[0])
    assert result.stint_lengths[:2] == (best[1], best[2])
    assert result.pit_laps == (best[1], best[1] + best[2])


def test_pit_loss_decides_between_one_and_two_stops():
    models = analytic_models()
    one = optimise_brute_force("C3", "C4", models, N, 5.0).total_time
    two = optimise_two_stop(("C3", "C4", "C3"), models, N, 5.0).total_time
    assert two < one  # cheap stops: more stops pay off
    one = optimise_brute_force("C3", "C4", models, N, 60.0).total_time
    two = optimise_two_stop(("C3", "C4", "C3"), models, N, 60.0).total_time
    assert one < two  # expensive stops: one stop is best


def test_compare_strategies_ranks_and_agrees_across_methods():
    methods, ranking = compare_strategies(analytic_models(), N, P, include_two_stop=True)
    one_stop = methods[methods["strategy"] == "C3 -> C4"]
    assert set(one_stop["method"]) == {"brute force", "secant", "newton"}
    assert one_stop["total_time"].nunique() == 1  # all methods agree
    assert ranking["total_time"].is_monotonic_increasing
    assert ranking["gap_to_best_s"].iloc[0] == 0.0
    assert not (ranking["strategy"] == "C3 -> C3 -> C3").any()  # single compound not allowed


# ---------------------------------------------------------------------------
# Inputs built from data
# ---------------------------------------------------------------------------
def test_max_stint_from_data():
    assert max_stint_from_data([1, 2, 2, 3, 3, 3, 40], min_laps=2) == 3
    with pytest.raises(ValueError):
        max_stint_from_data([1, 2], min_laps=5)


def test_order_balanced_compound_delta_removes_order_effect():
    # True delta (C4 - C3) = -0.1 s; the EARLIER stint is 0.25 s slower.
    rows = []
    rng = np.random.default_rng(42)
    for driver in range(20):
        car = rng.normal(85.0, 0.5)
        c4_first = driver < 15  # most drivers start on C4, as in the real data
        order = ("C4", "C3") if c4_first else ("C3", "C4")
        for stint, compound in enumerate(order, start=1):
            pace = car + (-0.1 if compound == "C4" else 0.0) + (0.25 if stint == 1 else 0.0)
            rows.append({"race": "r", "driver": f"D{driver}", "stint": stint, "compound": compound,
                         "offset": pace})
    result = compound_pace_delta(pd.DataFrame(rows), "C3", "C4")
    assert result["delta"] == pytest.approx(-0.1)
    assert result["median_other_first"] == pytest.approx(0.15)       # biased one way
    assert result["median_reference_first"] == pytest.approx(-0.35)  # biased the other way
    assert (result["n_other_first"], result["n_reference_first"]) == (15, 5)


def test_compound_delta_needs_both_orders():
    df = pd.DataFrame({"race": ["r", "r"], "driver": ["A", "A"], "stint": [1, 2],
                       "compound": ["C4", "C3"], "offset": [80.2, 80.0]})
    with pytest.raises(ValueError, match="Both stint orders"):
        compound_pace_delta(df, "C3", "C4")


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs, error",
    [
        (dict(compound_2="C3"), ValueError),           # same compound twice (dry-race rule)
        (dict(pit_lap=0), ValueError),
        (dict(pit_lap=70), ValueError),                 # must be < total_laps
        (dict(pit_lap=40.5), TypeError),
        (dict(pit_lap=True), TypeError),
        (dict(compound_2="C5"), ValueError),           # unknown compound
        (dict(pit_loss=0.0), ValueError),
        (dict(pit_loss=-5.0), ValueError),
        (dict(k_fuel=-0.01), ValueError),
        (dict(total_laps=1), ValueError),
    ],
)
def test_race_time_invalid_inputs(kwargs, error):
    arguments = dict(pit_lap=40, compound_1="C3", compound_2="C4", models=analytic_models(),
                     total_laps=N, pit_loss=P)
    arguments.update(kwargs)
    with pytest.raises(error):
        race_time(**arguments)


def test_stint_longer_than_limit_is_rejected():
    models = analytic_models(max_a=30, max_b=69)
    with pytest.raises(ValueError, match="exceeds its limit"):
        race_time(40, "C3", "C4", models, N, P)
    # Allowed when explicitly not enforced (used for plotting the full curve).
    assert race_time(40, "C3", "C4", models, N, P, enforce_max_stint=False) > 0


def test_other_invalid_inputs():
    models = analytic_models()
    with pytest.raises(ValueError):
        optimise_continuous("C3", "C4", models, N, P, root_finder="bisection")
    with pytest.raises(ValueError):
        optimise_two_stop(("C3", "C3", "C3"), models, N, P)
    with pytest.raises(ValueError):
        optimise_two_stop(("C3", "C4"), models, N, P)
    with pytest.raises(ValueError):
        race_time_continuous(0.0, "C3", "C4", models, N, P)
    with pytest.raises(TypeError):
        race_time(40, "C3", "C4", [models["C3"]], N, P)
    with pytest.raises(ValueError):
        CompoundModel("C3", models["C3"].model, -1.0, 40)
    with pytest.raises(ValueError):
        cumulative_degradation(models["C3"].model, -1.0)
