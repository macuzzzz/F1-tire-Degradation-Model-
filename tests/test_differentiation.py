"""Verification tests for the finite-difference formulas."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tyredeg.config import load_config
from tyredeg.numerics import differentiation as fd

VERIFY = load_config(Path(__file__).resolve().parents[1] / "config.yaml").verification

X0 = 1.0
FUNCTION_FORMULAS = {
    # name: (method, exact derivative of sin, theoretical order, default-step exponent)
    "forward": (fd.forward_difference, np.cos, 1, fd.FORWARD_STEP_EXPONENT),
    "backward": (fd.backward_difference, np.cos, 1, fd.FORWARD_STEP_EXPONENT),
    "central": (fd.central_difference, np.cos, 2, fd.CENTRAL_STEP_EXPONENT),
    "central 2nd": (fd.central_second_difference, lambda x: -np.sin(x), 2, fd.SECOND_STEP_EXPONENT),
}
# Steps in the truncation-dominated region (well above round-off), as in D37.
TRUNCATION_STEPS = 0.1 / 2.0 ** np.arange(4)


def slope_of_log_error(steps, errors):
    slope, _ = np.polyfit(np.log(steps), np.log(errors), 1)
    return slope


# ---------------------------------------------------------------------------
# Order of accuracy: functions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", FUNCTION_FORMULAS)
def test_order_of_accuracy_on_sin(name):
    method, exact, order, _ = FUNCTION_FORMULAS[name]
    errors = [abs(method(np.sin, X0, h) - exact(X0)) for h in TRUNCATION_STEPS]
    assert abs(slope_of_log_error(TRUNCATION_STEPS, errors) - order) <= VERIFY.difference_order_tolerance


@pytest.mark.parametrize("name", FUNCTION_FORMULAS)
def test_vectorised_points(name):
    method, exact, _, _ = FUNCTION_FORMULAS[name]
    x = np.array([0.5, 1.0, 2.0])
    result = method(np.sin, x)
    assert isinstance(result, np.ndarray) and result.shape == (3,)
    np.testing.assert_allclose(result, exact(x), atol=1e-6)


# ---------------------------------------------------------------------------
# Default step vs the empirical optimum (scripts/numerics_study.py, N3 request)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", FUNCTION_FORMULAS)
def test_default_step_is_near_the_empirical_optimum(name):
    # Error vs h on a fine grid, smoothed with a 9-point running median (the
    # round-off region is noisy), exactly as in the study at x = 1.
    method, exact, _, exponent = FUNCTION_FORMULAS[name]
    steps = np.logspace(-12, -1, 221)
    errors = np.array([abs(method(np.sin, X0, h) - exact(X0)) for h in steps])
    smooth = pd.Series(errors).rolling(9, center=True, min_periods=1).median().to_numpy()
    h_empirical = steps[int(np.argmin(smooth))]
    h_default = float(fd.default_step(X0, exponent))
    error_default = abs(method(np.sin, X0) - exact(X0))
    assert 0.1 <= h_empirical / h_default <= 10.0
    assert error_default <= 10.0 * np.min(smooth)


def test_default_step_formula():
    eps = np.finfo(float).eps
    assert fd.default_step(0.5, 0.5) == pytest.approx(np.sqrt(eps))       # max(1, |x|) = 1
    assert fd.default_step(-4.0, 1 / 3) == pytest.approx(4.0 * eps ** (1 / 3))


# ---------------------------------------------------------------------------
# Sampled arrays
# ---------------------------------------------------------------------------
def sampled_sin(n_points):
    x = np.linspace(0.0, 2.0, n_points)
    return x, np.sin(x)


@pytest.mark.parametrize(
    "method, exact, order",
    [
        (fd.central_difference_samples, np.cos, 2),
        (fd.central_second_difference_samples, lambda x: -np.sin(x), 2),
    ],
)
def test_sample_formulas_are_second_order_including_ends(method, exact, order):
    spacings, errors = [], []
    for n_points in (21, 41, 81, 161):
        x, y = sampled_sin(n_points)
        spacings.append(x[1] - x[0])
        errors.append(np.max(np.abs(method(x, y) - exact(x))))  # max includes the ends
    assert abs(slope_of_log_error(spacings, errors) - order) <= VERIFY.difference_order_tolerance


@pytest.mark.parametrize("method", [fd.forward_difference_samples, fd.backward_difference_samples])
def test_one_sided_sample_formulas_are_first_order(method):
    spacings, errors = [], []
    for n_points in (21, 41, 81, 161):
        x, y = sampled_sin(n_points)
        positions = x[:-1] if method is fd.forward_difference_samples else x[1:]
        spacings.append(x[1] - x[0])
        errors.append(np.max(np.abs(method(x, y) - np.cos(positions))))
    assert abs(slope_of_log_error(spacings, errors) - 1) <= VERIFY.difference_order_tolerance


def test_central_samples_match_numpy_gradient():
    x, y = sampled_sin(30)
    np.testing.assert_allclose(fd.central_difference_samples(x, y),
                               np.gradient(y, x, edge_order=2), rtol=1e-12, atol=1e-12)


def test_second_difference_samples_exact_for_cubic():
    # O(h^2) formulas are exact for polynomials up to degree 3 (2nd derivative of x^3 = 6x).
    x = np.arange(6.0)
    np.testing.assert_allclose(fd.central_second_difference_samples(x, x**3), 6 * x, atol=1e-10)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", FUNCTION_FORMULAS)
def test_function_input_validation(name):
    method = FUNCTION_FORMULAS[name][0]
    with pytest.raises(TypeError):
        method("sin", 1.0)
    with pytest.raises(ValueError):
        method(np.sin, np.nan)
    with pytest.raises(ValueError):
        method(np.sin, 1.0, h=0.0)
    with pytest.raises(ValueError):
        method(np.sin, 1.0, h=-1e-3)
    with pytest.raises(TypeError):
        method(np.sin, "1.0")


@pytest.mark.parametrize(
    "x, y, message",
    [
        ([0.0, 1.0, 3.0, 4.0], [0.0, 1.0, 2.0, 3.0], "uniform"),
        ([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.0], "same length"),
        ([3.0, 2.0, 1.0, 0.0], [0.0, 1.0, 2.0, 3.0], "increasing"),
        ([0.0, 1.0, 2.0, 3.0], [0.0, np.nan, 2.0, 3.0], "NaN"),
        ([0.0, 1.0], [0.0, 1.0], "At least"),
    ],
)
def test_sample_input_validation(x, y, message):
    with pytest.raises(ValueError, match=message):
        fd.central_second_difference_samples(x, y)
