"""Verification tests for linear and polynomial least squares."""

import warnings
from pathlib import Path

import numpy as np
import pytest

from tyredeg.config import load_config
from tyredeg.numerics.least_squares import (
    LeastSquaresResult,
    fit_linear_least_squares,
    fit_linear_least_squares_qr,
    fit_polynomial,
    polynomial_design_matrix,
)
from tyredeg.numerics.linear_solvers import NearSingularWarning, SingularMatrixError

VERIFY = load_config(Path(__file__).resolve().parents[1] / "config.yaml").verification
SEED = 42  # rule 11: every random test uses this recorded seed
NOISE_STD = 0.4  # s; similar to real lap-time noise (Phase 2)
FITTERS = {"normal": fit_linear_least_squares, "qr": fit_linear_least_squares_qr}


def synthetic_stints(n=400):
    """Lap time = 80 + 0.05 * tyre age + noise, tyre ages 1-40 laps."""
    rng = np.random.default_rng(SEED)
    age = rng.integers(1, 41, size=n).astype(float)
    X = np.column_stack([np.ones(n), age])
    y = X @ np.array([80.0, 0.05]) + rng.normal(0.0, NOISE_STD, size=n)
    return X, y


@pytest.mark.parametrize("method", FITTERS)
def test_recovers_known_coefficients_from_noisy_data(method):
    # Each method recovers the true coefficients to within a few standard errors.
    X, y = synthetic_stints()
    result = FITTERS[method](X, y)
    assert isinstance(result, LeastSquaresResult)
    truth = np.array([80.0, 0.05])
    assert np.all(np.abs(result.coefficients - truth)
                  <= VERIFY.least_squares_se_multiple * result.standard_errors)


@pytest.mark.parametrize("method", FITTERS)
def test_matches_numpy_lstsq(method):
    # Each method gives the same coefficients as numpy.linalg.lstsq (the benchmark).
    X, y = synthetic_stints()
    reference, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    np.testing.assert_allclose(FITTERS[method](X, y).coefficients, reference,
                               rtol=VERIFY.least_squares_rtol)


@pytest.mark.parametrize("method", FITTERS)
def test_standard_errors_and_rss_match_textbook_formulas(method):
    # Residual sum of squares and standard errors follow the textbook formulas.
    X, y = synthetic_stints()
    result = FITTERS[method](X, y)
    beta, residuals, _, _ = np.linalg.lstsq(X, y, rcond=None)
    sigma_squared = residuals[0] / (X.shape[0] - X.shape[1])
    expected_se = np.sqrt(np.diag(sigma_squared * np.linalg.inv(X.T @ X)))
    assert result.residual_sum_of_squares == pytest.approx(residuals[0], rel=1e-9)
    np.testing.assert_allclose(result.standard_errors, expected_se, rtol=1e-8)


def test_exact_fit_has_no_standard_errors():
    # With as many points as parameters the fit is exact and no error can be estimated.
    result = fit_linear_least_squares([[1.0, 0.0], [1.0, 1.0]], [1.0, 3.0])
    np.testing.assert_allclose(result.coefficients, [1.0, 2.0])
    assert np.all(np.isnan(result.standard_errors))


# ---------------------------------------------------------------------------
# Polynomials and scaling (D35)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["normal", "qr"])
@pytest.mark.parametrize("scale", [True, False])
def test_polynomial_recovers_quadratic(method, scale):
    rng = np.random.default_rng(SEED)
    age = np.tile(np.arange(1.0, 41.0), 10)
    true = np.array([80.0, 0.02, 0.001])  # 80 + 0.02 n + 0.001 n^2
    y = true[0] + true[1] * age + true[2] * age**2 + rng.normal(0.0, NOISE_STD, age.size)
    fit = fit_polynomial(age, y, 2, scale=scale, method=method)
    reference = np.polynomial.polynomial.polyfit(age, y, 2)  # NumPy benchmark
    np.testing.assert_allclose(fit.unscaled_coefficients(), reference, rtol=1e-6)
    np.testing.assert_allclose(fit.predict(age), np.polynomial.polynomial.polyval(age, reference),
                               rtol=1e-12)


def test_scaling_maps_inputs_to_unit_interval():
    # Scaling maps the tyre ages onto [-1, 1]; unscaled leaves them as they are.
    fit = fit_polynomial([1.0, 21.0, 41.0], [1.0, 2.0, 3.0], 1)
    assert (fit.centre, fit.half_range) == (21.0, 20.0)
    unscaled = fit_polynomial([1.0, 21.0, 41.0], [1.0, 2.0, 3.0], 1, scale=False)
    assert (unscaled.centre, unscaled.half_range) == (0.0, 1.0)


def test_scaling_reduces_condition_number():
    # Scaling the ages makes the design matrix far better conditioned.
    age = np.arange(1.0, 42.0)
    y = 80.0 + 0.05 * age
    unscaled = fit_polynomial(age, y, 3, scale=False).result.condition_estimate
    scaled = fit_polynomial(age, y, 3, scale=True).result.condition_estimate
    assert scaled < 1e3 < 1e9 < unscaled


def test_normal_equations_warn_for_unscaled_quartic_but_qr_does_not():
    # cond(X) ~ 6e6, so cond(X^T X) ~ 3.6e13 > 1e12: only the normal equations warn.
    age = np.arange(1.0, 42.0)
    y = 80.0 + 0.05 * age
    with pytest.warns(NearSingularWarning):
        fit_polynomial(age, y, 4, scale=False, method="normal")
    with warnings.catch_warnings():
        warnings.simplefilter("error", NearSingularWarning)
        fit_polynomial(age, y, 4, scale=False, method="qr")
        fit_polynomial(age, y, 4, scale=True, method="normal")


def test_qr_more_accurate_than_normal_on_ill_conditioned_fit():
    # Noise-free degree-6 data in the unscaled basis: the exact answer is known.
    age = np.arange(1.0, 42.0)
    true = np.array([80.0, 0.05, 1e-4, -1e-4, 1e-4, -1e-4, 1e-4])
    X = polynomial_design_matrix(age, 6)
    y = X @ true
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NearSingularWarning)
        normal = fit_linear_least_squares(X, y).coefficients
    qr = fit_linear_least_squares_qr(X, y).coefficients
    normal_error = np.linalg.norm(normal - true) / np.linalg.norm(true)
    qr_error = np.linalg.norm(qr - true) / np.linalg.norm(true)
    assert qr_error < normal_error


def test_design_matrix_columns():
    # The design matrix holds 1, s, s^2 for each scaled age s.
    X = polynomial_design_matrix([0.0, 2.0], 2, centre=1.0, half_range=1.0)
    np.testing.assert_allclose(X, [[1.0, -1.0, 1.0], [1.0, 1.0, 1.0]])


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "X, y",
    [
        ([1.0, 2.0], [1.0, 2.0]),                         # X not 2-D
        ([[1.0], [2.0]], [1.0, 2.0, 3.0]),                # length mismatch
        ([[1.0, 2.0, 3.0]], [1.0]),                       # n < p
        ([[1.0, np.nan], [1.0, 2.0]], [1.0, 2.0]),        # NaN
    ],
)
@pytest.mark.parametrize("method", FITTERS)
def test_invalid_least_squares_inputs(method, X, y):
    # Invalid matrices and data are rejected by every method.
    with pytest.raises(ValueError):
        FITTERS[method](X, y)


def test_dependent_columns_are_singular():
    # Linearly dependent columns make the problem singular.
    X = np.column_stack([np.ones(5), np.arange(5.0), 2 * np.arange(5.0)])
    with pytest.raises(SingularMatrixError):
        fit_linear_least_squares(X, np.arange(5.0))


@pytest.mark.parametrize(
    "kwargs, error",
    [
        (dict(degree=-1), ValueError),
        (dict(degree=2.0), ValueError),
        (dict(degree=3), ValueError),          # only 3 distinct x values
        (dict(degree=1, method="svd"), ValueError),
        (dict(degree=1, scale="yes"), TypeError),
    ],
)
def test_invalid_polynomial_inputs(kwargs, error):
    # Invalid polynomial settings are rejected with the expected error type.
    with pytest.raises(error):
        fit_polynomial([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], **kwargs)
