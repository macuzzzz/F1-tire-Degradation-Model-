"""Tests for the three degradation models (polynomial, wear ODE, KNN).

Synthetic stints are generated from KNOWN parameters (seed 42, rule 11):
each stint gets its own base offset (car pace), the tyre ages of a real
stint, and noise of 0.3-0.4 s like the real data. Each model must recover
the parameters within tolerance.
"""

import warnings

import numpy as np
import pytest
from scipy.optimize import least_squares as scipy_least_squares
from sklearn.neighbors import KNeighborsRegressor

from tyredeg.models.common import (
    NotFittedError,
    check_non_negative,
    prepare_stint_data,
    stint_labels_from_laps,
)
from tyredeg.models.knn import KNNDegradationModel, KNNRegressor
from tyredeg.models.polynomial import PolynomialDegradationModel
from tyredeg.models.wear_ode import (
    WearODEModel,
    exact_degradation,
    exact_unit_response,
    unit_response,
)

SEED = 42
NOISE = 0.35  # s


def synthetic_stints(degradation, n_stints=40, noise=NOISE, seed=SEED, ar1=0.0):
    """Stints of 15-30 laps starting at tyre age 2-4 with offsets ~ N(85, 0.6) s.

    ``ar1`` > 0 makes the noise within a stint correlated (like real data).
    Returns (tyre_age, lap_time, stint_id, offsets).
    """
    rng = np.random.default_rng(seed)
    ages, times, ids, offsets = [], [], [], []
    for stint in range(n_stints):
        start = rng.integers(2, 5)
        length = rng.integers(15, 31)
        age = np.arange(start, start + length, dtype=float)
        offset = rng.normal(85.0, 0.6)
        e = np.zeros(length)
        e[0] = rng.normal(0.0, noise)
        for i in range(1, length):
            e[i] = ar1 * e[i - 1] + np.sqrt(1 - ar1**2) * rng.normal(0.0, noise)
        ages.append(age)
        times.append(offset + degradation(age) + e)
        ids.append(np.full(length, stint))
        offsets.append(offset)
    return np.concatenate(ages), np.concatenate(times), np.concatenate(ids), np.array(offsets)


# ---------------------------------------------------------------------------
# Shared input validation (all three models)
# ---------------------------------------------------------------------------
MODEL_FACTORIES = {
    "polynomial": lambda: PolynomialDegradationModel("C3", degree=1),
    "wear_ode": lambda: WearODEModel("C3"),
    "knn": lambda: KNNDegradationModel("C3", k=3),
}


@pytest.mark.parametrize("name", MODEL_FACTORIES)
@pytest.mark.parametrize(
    "ages, times, ids",
    [
        ([], [], None),                                    # empty
        ([1.0, 2.0, 3.0], [80.0, 80.1], None),              # mismatched lengths
        ([1.0, np.nan, 3.0, 4.0], [80.0, 80.1, 80.2, 80.3], None),
        ([1.0, -2.0, 3.0, 4.0], [80.0, 80.1, 80.2, 80.3], None),  # negative age
        ([1.0, 2.0, 3.0, 4.0], [80.0, 0.0, 80.2, 80.3], None),    # non-positive time
        ([1.0, 2.0, 3.0, 4.0], [80.0, 80.1, 80.2, 80.3], [0, 1]),  # stint_id length
        ([1.0, 2.0], [80.0, 80.1], ["a", "b"]),              # no residual dof
    ],
)
def test_invalid_training_inputs(name, ages, times, ids):
    with pytest.raises(ValueError):
        MODEL_FACTORIES[name]().fit(ages, times, ids)


@pytest.mark.parametrize("compound, error", [("HARD", ValueError), ("C9", ValueError), (3, TypeError)])
@pytest.mark.parametrize("cls", [PolynomialDegradationModel, WearODEModel, KNNDegradationModel])
def test_unknown_compound(cls, compound, error):
    with pytest.raises(error):
        cls(compound)


@pytest.mark.parametrize("name", MODEL_FACTORIES)
def test_use_before_fit(name):
    model = MODEL_FACTORIES[name]()
    with pytest.raises(NotFittedError):
        model.predict([5.0])
    with pytest.raises(NotFittedError):
        model.params()


@pytest.mark.parametrize("name", MODEL_FACTORIES)
def test_predict_is_base_plus_degradation(name):
    ages, times, ids, _ = synthetic_stints(lambda n: 0.07 * n, n_stints=10)
    model = MODEL_FACTORIES[name]().fit(ages, times, ids)
    query = np.array([5.0, 10.0])
    np.testing.assert_allclose(model.predict(query, base_time=90.0), 90.0 + model.degradation(query))
    np.testing.assert_allclose(model.predict(query), model.base_time + model.degradation(query))
    with pytest.raises(ValueError):
        model.predict(query, base_time=-1.0)
    with pytest.raises(ValueError):
        model.degradation([-1.0])
    assert isinstance(model.summary(), str)


def test_stint_labels_from_laps():
    import pandas as pd

    laps = pd.DataFrame({"RaceId": ["r1", "r1"], "Driver": ["VER", "HAM"], "Stint": [1.0, 2.0]})
    assert stint_labels_from_laps(laps).tolist() == ["r1|VER|1", "r1|HAM|2"]


def test_constraint_check():
    assert not check_non_negative(lambda n: 0.07 * n, 40.0, 0.01).violated
    result = check_non_negative(lambda n: -0.05 * n, 40.0, 0.01)
    assert result.violated and result.age_of_minimum == 40.0


# ---------------------------------------------------------------------------
# Polynomial model
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["normal", "qr"])
def test_polynomial_recovers_linear_rate(method):
    ages, times, ids, offsets = synthetic_stints(lambda n: 0.07 * n)
    model = PolynomialDegradationModel("C3", degree=1, method=method).fit(ages, times, ids)
    p = model.params()
    assert abs(p["coefficients"][0] - 0.07) <= 3 * p["standard_errors"][0]
    assert p["residual_std"] == pytest.approx(NOISE, rel=0.1)
    # Each stint offset is recovered to within the noise of a stint mean.
    assert np.max(np.abs(model._offsets - offsets)) < 0.5
    assert model.degradation([0.0]).tolist() == [0.0]


def test_polynomial_recovers_quadratic():
    true = (0.03, 0.002)  # d = 0.03 n + 0.002 n^2
    ages, times, ids, _ = synthetic_stints(lambda n: true[0] * n + true[1] * n**2, n_stints=60)
    p = PolynomialDegradationModel("C3", degree=2).fit(ages, times, ids).params()
    for k in range(2):
        assert abs(p["coefficients"][k] - true[k]) <= 3 * p["standard_errors"][k]


@pytest.mark.parametrize("degree", [1, 2, 3])
def test_polynomial_matches_full_dummy_variable_regression(degree):
    # Frisch-Waugh-Lovell check: fitting one column per stint plus the powers of
    # tyre age with numpy.linalg.lstsq must give the same coefficients and the
    # same standard errors as the within-stint fit.
    ages, times, ids, _ = synthetic_stints(lambda n: 0.05 * n + 0.001 * n**2, n_stints=12)
    p = PolynomialDegradationModel("C3", degree=degree).fit(ages, times, ids).params()
    dummies = (ids[:, None] == np.unique(ids)[None, :]).astype(float)
    powers = np.column_stack([ages**k for k in range(1, degree + 1)])
    X = np.column_stack([dummies, powers])
    beta, residuals, _, _ = np.linalg.lstsq(X, times, rcond=None)
    sigma2 = residuals[0] / (X.shape[0] - X.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))[-degree:]
    np.testing.assert_allclose(p["coefficients"], beta[-degree:], rtol=1e-6, atol=1e-12)
    np.testing.assert_allclose(p["standard_errors"], se, rtol=1e-6)


def test_polynomial_flags_negative_degradation():
    ages, times, ids, _ = synthetic_stints(lambda n: -0.05 * n, n_stints=10)
    p = PolynomialDegradationModel("C3").fit(ages, times, ids).params()
    assert p["negative_degradation_flag"]
    assert p["min_degradation"] < -1.0


def test_polynomial_invalid_settings():
    with pytest.raises(ValueError):
        PolynomialDegradationModel("C3", degree=0)
    with pytest.raises(ValueError):
        PolynomialDegradationModel("C3", method="svd")
    with pytest.raises(ValueError, match="distinct"):
        PolynomialDegradationModel("C3", degree=3).fit([1, 1, 2, 2, 1, 2], [80.0] * 6)


# ---------------------------------------------------------------------------
# Wear ODE: solutions
# ---------------------------------------------------------------------------
AGES = np.arange(0.0, 56.0)


@pytest.mark.parametrize("b", [-0.1, -0.02, 0.0, 0.03, 0.1])
def test_rk4_unit_response_matches_exact(b):
    # RK4 with 1-lap steps vs the exact solution (D42, D36).
    g_rk4 = unit_response(AGES, b, solver="rk4")
    g_exact = exact_unit_response(AGES, b)
    assert np.max(np.abs(g_rk4 - g_exact) / np.maximum(1.0, np.abs(g_exact))) < 1e-5


@pytest.mark.parametrize("b", [-0.05, 0.0, 0.03])
def test_rk45_unit_response_matches_exact(b):
    g_rk45 = unit_response([3.0, 10.0, 25.0, 41.0], b, solver="rk45")
    np.testing.assert_allclose(g_rk45, exact_unit_response([3.0, 10.0, 25.0, 41.0], b), rtol=1e-8)


def test_exact_solution_b_to_zero_limit():
    n = np.array([1.0, 20.0, 41.0])
    # Taylor series g_b(n) = n + b n^2 / 2 + b^2 n^3 / 6 + O(b^3 n^4): the
    # limit n and its first two corrections (the third is < 1e-13 relative here).
    for b in (1e-14, 1e-9, -1e-9, 1e-6):
        series = n + b * n**2 / 2 + b**2 * n**3 / 6
        np.testing.assert_allclose(exact_unit_response(n, b), series, rtol=1e-12)
    np.testing.assert_array_equal(exact_unit_response(n, 0.0), n)


def test_exact_solution_satisfies_the_ode():
    # dd/dn = a + b d checked with a central difference of the exact solution.
    a, b, n = 0.05, 0.03, 20.0
    h = 1e-5
    slope = (exact_degradation([n + h], a, b) - exact_degradation([n - h], a, b)) / (2 * h)
    assert slope[0] == pytest.approx(a + b * exact_degradation([n], a, b)[0], rel=1e-8)


def test_unit_response_rejects_bad_input():
    with pytest.raises(ValueError, match="multiple"):
        unit_response([1.5], 0.02, solver="rk4")
    with pytest.raises(ValueError):
        unit_response([1.0], 0.02, solver="euler")
    with pytest.raises(ValueError):
        unit_response([1.0], np.nan)


# ---------------------------------------------------------------------------
# Wear ODE: fitting
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a, b", [(0.05, 0.03), (0.07, 0.0), (0.12, -0.03)])
def test_wear_ode_recovers_parameters(a, b):
    ages, times, ids, _ = synthetic_stints(lambda n: exact_degradation(n, a, b), n_stints=60)
    p = WearODEModel("C3").fit(ages, times, ids).params()
    assert abs(p["a"] - a) <= 3 * p["standard_errors"][0]
    assert abs(p["b"] - b) <= 3 * p["standard_errors"][1]
    assert not p["b_at_bracket_boundary"] and not p["a_clamped_to_zero"]
    assert p["ode_check_max_error"] < 1e-4


def test_wear_ode_noise_free_exact_recovery():
    ages, times, ids, _ = synthetic_stints(lambda n: exact_degradation(n, 0.05, 0.03), noise=0.0)
    p = WearODEModel("C3", solver="exact").fit(ages, times, ids).params()
    assert p["a"] == pytest.approx(0.05, rel=1e-6)
    assert p["b"] == pytest.approx(0.03, abs=1e-7)


def test_wear_ode_matches_scipy_least_squares_benchmark():
    # Benchmark: scipy.optimize.least_squares on the FULL nonlinear problem
    # (one offset per stint + a + b) must find the same a and b.
    ages, times, ids, _ = synthetic_stints(lambda n: exact_degradation(n, 0.05, 0.03), n_stints=25)
    p = WearODEModel("C3", solver="exact").fit(ages, times, ids).params()
    stints = np.unique(ids)

    def residuals(theta):
        offsets, a, b = theta[:-2], theta[-2], theta[-1]
        return offsets[np.searchsorted(stints, ids)] + exact_degradation(ages, a, b) - times

    start = np.concatenate([np.full(stints.size, 85.0), [0.07, 0.0]])
    reference = scipy_least_squares(residuals, start, xtol=1e-14, ftol=1e-14, gtol=1e-14)
    assert p["a"] == pytest.approx(reference.x[-2], rel=1e-5)
    assert p["b"] == pytest.approx(reference.x[-1], abs=1e-6)
    assert p["rss"] == pytest.approx(np.sum(reference.fun**2), rel=1e-9)


@pytest.mark.parametrize("root_finder", ["bisection", "secant", "newton"])
@pytest.mark.parametrize("solver", ["rk4", "rk45", "exact"])
def test_wear_ode_solvers_and_root_finders_agree(solver, root_finder):
    ages, times, ids, _ = synthetic_stints(lambda n: exact_degradation(n, 0.05, 0.03), n_stints=12)
    reference = WearODEModel("C3", solver="exact").fit(ages, times, ids).params()
    p = WearODEModel("C3", solver=solver, root_finder=root_finder).fit(ages, times, ids).params()
    assert p["b"] == pytest.approx(reference["b"], abs=1e-4)
    assert p["a"] == pytest.approx(reference["a"], rel=1e-3)


def test_wear_ode_flags_bracket_boundary():
    # True b = 0.2 lies outside the default bracket [-0.1, 0.1].
    ages, times, ids, _ = synthetic_stints(lambda n: exact_degradation(n, 0.01, 0.2), n_stints=10,
                                           noise=0.05)
    assert WearODEModel("C3").fit(ages, times, ids).params()["b_at_bracket_boundary"]


def test_wear_ode_clamps_negative_wear_rate():
    # Lap times that FALL with tyre age: unconstrained a would be negative.
    ages, times, ids, _ = synthetic_stints(lambda n: -0.05 * n, n_stints=10)
    model = WearODEModel("C3").fit(ages, times, ids)
    p = model.params()
    assert p["a"] == 0.0 and p["a_clamped_to_zero"] and p["negative_degradation_flag"]
    assert np.all(model.degradation([0.0, 20.0]) == 0.0)
    assert "clamped" in model.summary()


def test_wear_ode_invalid_settings():
    with pytest.raises(ValueError):
        WearODEModel("C3", solver="euler")
    with pytest.raises(ValueError):
        WearODEModel("C3", root_finder="brent")
    with pytest.raises(ValueError):
        WearODEModel("C3", b_bracket=(0.1, -0.1))
    with pytest.raises(ValueError):
        WearODEModel("C3", b_grid_points=2)
    with pytest.raises(ValueError, match="does not vary"):
        # Enough laps for the degrees of freedom, but every stint has one tyre age.
        WearODEModel("C3").fit([5.0, 5.0, 5.0, 7.0, 7.0, 7.0], [80.0, 80.1, 80.2, 80.3, 80.4, 80.5],
                               ["a", "a", "a", "b", "b", "b"])


# ---------------------------------------------------------------------------
# Uncertainty: stint bootstrap (D45)
# ---------------------------------------------------------------------------
def test_bootstrap_is_reproducible_with_a_seed():
    ages, times, ids, _ = synthetic_stints(lambda n: 0.07 * n, n_stints=15)
    model = PolynomialDegradationModel("C3").fit(ages, times, ids)
    first = model.bootstrap(30, seed=SEED).estimates
    second = model.bootstrap(30, seed=SEED).estimates
    np.testing.assert_array_equal(first, second)
    assert model.params()["bootstrap_standard_errors"] is not None


def test_bootstrap_agrees_with_analytic_se_for_independent_noise():
    ages, times, ids, _ = synthetic_stints(lambda n: 0.07 * n, n_stints=40)
    model = PolynomialDegradationModel("C3").fit(ages, times, ids)
    ratio = model.bootstrap(200, seed=SEED).standard_errors[0] / model.params()["standard_errors"][0]
    assert 0.7 < ratio < 1.4


def test_bootstrap_exceeds_analytic_se_for_correlated_noise():
    # With within-stint correlation (as in the real data, rho ~ 0.45-0.6) the
    # analytic SE, which assumes independent laps, is too small.
    ages, times, ids, _ = synthetic_stints(lambda n: 0.07 * n, n_stints=40, ar1=0.6)
    model = PolynomialDegradationModel("C3").fit(ages, times, ids)
    ratio = model.bootstrap(200, seed=SEED).standard_errors[0] / model.params()["standard_errors"][0]
    assert ratio > 1.2


def test_wear_ode_bootstrap_runs_and_brackets_estimate():
    ages, times, ids, _ = synthetic_stints(lambda n: exact_degradation(n, 0.05, 0.03), n_stints=20)
    model = WearODEModel("C3").fit(ages, times, ids)
    result = model.bootstrap(20, seed=SEED)
    assert result.estimates.shape == (20, 2)
    assert np.all(result.lower <= result.upper)
    assert "SE(bootstrap)" in model.summary()


# ---------------------------------------------------------------------------
# KNN regressor vs scikit-learn
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("k", [1, 5, 15])
@pytest.mark.parametrize("weights", ["uniform", "distance"])
def test_knn_matches_sklearn_on_tie_free_data(k, weights):
    rng = np.random.default_rng(SEED)
    X = rng.uniform(0, 40, size=(200, 2))      # continuous: no tied distances
    y = np.sin(X[:, 0] / 5) + 0.1 * X[:, 1] + rng.normal(0, 0.1, 200)
    queries = rng.uniform(0, 40, size=(50, 2))
    mine = KNNRegressor(k, weights).fit(X, y).predict(queries)
    reference = KNeighborsRegressor(n_neighbors=k, weights=weights, algorithm="brute").fit(X, y)
    np.testing.assert_allclose(mine, reference.predict(queries), rtol=1e-12, atol=1e-12)


def test_knn_includes_all_tied_neighbours():
    # Query 2.0: k = 2 nearest are the two points at age 2; with k = 3 the
    # 3rd distance (1.0) is shared by ages 1 and 3, so all 4 points are used.
    X = np.array([1.0, 2.0, 2.0, 3.0, 10.0])
    y = np.array([1.0, 2.0, 4.0, 5.0, 100.0])
    assert KNNRegressor(2).fit(X, y).predict([2.0]).tolist() == [3.0]
    assert KNNRegressor(3).fit(X, y).predict([2.0]).tolist() == [3.0]  # (1+2+4+5)/4
    # The result does not depend on the order of the training rows.
    order = np.array([4, 2, 0, 3, 1])
    assert KNNRegressor(3).fit(X[order], y[order]).predict([2.0]).tolist() == [3.0]


def test_knn_distance_weighting_with_exact_match():
    X = np.array([0.0, 1.0, 1.0, 5.0])
    y = np.array([0.0, 2.0, 4.0, 10.0])
    # Exact matches at distance 0 get all the weight (scikit-learn's rule).
    assert KNNRegressor(3, "distance").fit(X, y).predict([1.0]).tolist() == [3.0]


def test_knn_regressor_invalid_inputs():
    with pytest.raises(ValueError):
        KNNRegressor(0)
    with pytest.raises(ValueError):
        KNNRegressor(3, "gaussian")
    with pytest.raises(ValueError, match="larger"):
        KNNRegressor(5).fit([1.0, 2.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        KNNRegressor(1).fit([[1.0, 2.0]], [1.0, 2.0])
    with pytest.raises(ValueError, match="features"):
        KNNRegressor(1).fit([[1.0, 2.0], [3.0, 4.0]], [1.0, 2.0]).predict([[1.0]])
    with pytest.raises(NotFittedError):
        KNNRegressor(1).predict([1.0])


# ---------------------------------------------------------------------------
# KNN degradation model
# ---------------------------------------------------------------------------
def test_knn_model_recovers_degradation_curve():
    true = lambda n: exact_degradation(n, 0.05, 0.03)  # noqa: E731  (curved)
    ages, times, ids, _ = synthetic_stints(true, n_stints=80)
    model = KNNDegradationModel("C3", k=50).fit(ages, times, ids)
    query = np.arange(5.0, 30.0)
    assert np.max(np.abs(model.degradation(query) - true(query))) < 0.25
    assert not model.params()["negative_degradation_flag"]


def test_knn_model_flags_negative_degradation():
    ages, times, ids, _ = synthetic_stints(lambda n: -0.05 * n, n_stints=10)
    assert KNNDegradationModel("C3", k=10).fit(ages, times, ids).params()["negative_degradation_flag"]


def test_knn_model_rejects_k_larger_than_data():
    with pytest.raises(ValueError):
        KNNDegradationModel("C3", k=50).fit([1.0, 2.0, 3.0], [80.0, 80.1, 80.2])


def test_prepare_stint_data_encodes_stints():
    data = prepare_stint_data([1, 2, 1], [80.0, 80.1, 81.0], ["b", "b", "a"])
    assert data.n_stints == 2
    assert data.stint_labels.tolist() == ["a", "b"]
    np.testing.assert_allclose(data.demean(np.array([1.0, 3.0, 5.0])), [-1.0, 1.0, 0.0])
