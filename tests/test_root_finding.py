"""Verification tests for bisection, secant and Newton-Raphson."""

from pathlib import Path

import numpy as np
import pytest
from scipy import optimize

from tyredeg.config import load_config
from tyredeg.numerics.root_finding import (
    DivergenceError,
    NoSignChangeError,
    NotConvergedError,
    RootResult,
    ZeroDerivativeError,
    bisection,
    newton,
    secant,
)

VERIFY = load_config(Path(__file__).resolve().parents[1] / "config.yaml").verification

ROOT_2 = np.sqrt(2.0)
GOLDEN_RATIO = (1.0 + np.sqrt(5.0)) / 2.0


def square_minus_two(x):
    return x * x - 2.0


def square_minus_two_prime(x):
    return 2.0 * x


def convergence_orders(history, root):
    """Order estimates log(e_{k+1}/e_k) / log(e_k/e_{k-1}) before round-off."""
    errors = np.abs(np.asarray(history) - root)
    errors = errors[errors > 1e-15]  # below this the error is round-off noise
    return np.log(errors[2:] / errors[1:-1]) / np.log(errors[1:-1] / errors[:-2])


# ---------------------------------------------------------------------------
# Known roots, also compared with SciPy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "f, fprime, bracket, root",
    [
        (square_minus_two, square_minus_two_prime, (1.0, 2.0), ROOT_2),
        (lambda x: np.cos(x) - x, lambda x: -np.sin(x) - 1.0, (0.0, 1.0), None),
        (lambda x: np.exp(x) - 2.0, np.exp, (0.0, 1.0), np.log(2.0)),
    ],
)
def test_all_methods_find_known_roots(f, fprime, bracket, root):
    if root is None:
        root = optimize.brentq(f, *bracket, xtol=1e-15)  # SciPy benchmark
    a, b = bracket
    for result in (bisection(f, a, b), secant(f, a, b), newton(f, fprime, b)):
        assert isinstance(result, RootResult)
        assert abs(result.root - root) < 1e-9
        assert result.history[-1] == result.root


def test_newton_matches_scipy_newton():
    mine = newton(square_minus_two, square_minus_two_prime, 1.0).root
    theirs = optimize.newton(square_minus_two, 1.0, fprime=square_minus_two_prime)
    assert mine == pytest.approx(theirs, abs=1e-14)


# ---------------------------------------------------------------------------
# Convergence rates
# ---------------------------------------------------------------------------
def test_newton_converges_quadratically():
    history = newton(square_minus_two, square_minus_two_prime, 1.0).history
    orders = convergence_orders(history, ROOT_2)
    assert abs(orders[-1] - 2.0) <= VERIFY.newton_order_tolerance


def test_secant_converges_with_golden_ratio_order():
    history = secant(square_minus_two, 1.0, 2.0).history
    orders = convergence_orders(history, ROOT_2)
    assert abs(orders[-1] - GOLDEN_RATIO) <= VERIFY.secant_order_tolerance


def test_bisection_error_bound_halves_every_iteration():
    a, b = 1.0, 2.0
    history = bisection(square_minus_two, a, b).history
    for k, midpoint in enumerate(history):
        # After k+1 halvings the root lies within (b - a) / 2^(k+1) of the midpoint.
        assert abs(midpoint - ROOT_2) <= (b - a) / 2 ** (k + 1)


def test_bisection_iteration_count_matches_theory():
    # Half-width after k iterations is 1 / 2^k; it first drops to <= 1e-10 at k = 34.
    result = bisection(square_minus_two, 1.0, 2.0, xtol=1e-10, ftol=0.0)
    assert result.iterations == int(np.ceil(np.log2(1.0 / 1e-10)))


def test_newton_needs_fewer_iterations_than_secant_and_bisection():
    newton_iterations = newton(square_minus_two, square_minus_two_prime, 1.5).iterations
    secant_iterations = secant(square_minus_two, 1.0, 2.0).iterations
    bisection_iterations = bisection(square_minus_two, 1.0, 2.0).iterations
    assert newton_iterations < secant_iterations < bisection_iterations


# ---------------------------------------------------------------------------
# Stopping rule (D30, amended after OI-4: step AND residual + round-off safeguard)
# ---------------------------------------------------------------------------
def steep(x):
    """Steep function (slope ~1e5 at the root x ~ 34.01): the closest floats to
    the root leave |f| ~ 1e-11, so |f| <= 1e-12 cannot be reached."""
    return 1e4 * (np.exp(x / 10.0) - 30.0)


def steep_prime(x):
    return 1e3 * np.exp(x / 10.0)


STEEP_ROOT = 10.0 * np.log(30.0)


def test_tighter_tolerance_gives_more_accurate_root():
    loose = bisection(square_minus_two, 1.0, 2.0, xtol=1e-4, ftol=0.0)
    tight = bisection(square_minus_two, 1.0, 2.0, xtol=1e-12, ftol=0.0)
    assert tight.iterations > loose.iterations
    assert abs(tight.root - ROOT_2) < abs(loose.root - ROOT_2)


def test_both_tests_must_pass_by_default():
    result = newton(square_minus_two, square_minus_two_prime, 1.0)
    step = abs(result.history[-1] - result.history[-2])
    assert step <= 1e-10 and abs(square_minus_two(result.root)) <= 1e-12


def test_a_zero_tolerance_switches_that_test_off():
    by_step = newton(square_minus_two, square_minus_two_prime, 1.0, ftol=0.0)
    by_residual = newton(square_minus_two, square_minus_two_prime, 1.0, xtol=0.0)
    assert abs(by_step.root - ROOT_2) < 1e-10
    assert abs(square_minus_two(by_residual.root)) <= 1e-12


def test_both_rule_is_accurate_on_a_flat_function():
    # Study finding (OI-4): for (x-1)^3 the residual test alone stops with
    # |x - 1| ~ 1e-4 because |f| is tiny long before x is accurate; requiring
    # a small step as well gives ~1e-10.
    f = lambda x: (x - 1.0) ** 3  # noqa: E731
    residual_only = bisection(f, 0.5, 1.7, xtol=0.0)
    both = bisection(f, 0.5, 1.7)
    assert abs(residual_only.root - 1.0) > 1e-5
    assert abs(both.root - 1.0) < 1e-9


@pytest.mark.parametrize("method", ["bisection", "secant", "newton"])
def test_roundoff_safeguard_on_a_steep_function(method):
    # Without the safeguard, requiring |f| <= 1e-12 here never stops (bisection,
    # Newton) or ends in a misleading ZeroDerivativeError (secant).
    runs = {
        "bisection": lambda: bisection(steep, 30.0, 40.0),
        "secant": lambda: secant(steep, 30.0, 40.0),
        "newton": lambda: newton(steep, steep_prime, 35.0),
    }
    result = runs[method]()
    assert abs(steep(result.root)) > 1e-12   # the residual target was unreachable ...
    # ... yet the root is within a few floating-point spacings of the truth.
    assert abs(result.root - STEEP_ROOT) <= 8 * np.spacing(STEEP_ROOT)


# ---------------------------------------------------------------------------
# Failure cases (D31)
# ---------------------------------------------------------------------------
def test_bisection_without_sign_change():
    with pytest.raises(NoSignChangeError):
        bisection(square_minus_two, 2.0, 3.0)


def test_bisection_endpoint_root():
    result = bisection(lambda x: x - 1.0, 1.0, 2.0)
    assert result.root == 1.0 and result.iterations == 0


def test_newton_zero_derivative():
    with pytest.raises(ZeroDerivativeError):
        newton(square_minus_two, square_minus_two_prime, 0.0)


def test_secant_horizontal_secant_line():
    with pytest.raises(ZeroDerivativeError):
        secant(lambda x: x * x, -1.0, 1.0)


def test_newton_diverges_on_arctan_from_far_away():
    # Classic example: from |x0| > 1.39 Newton's iterates for arctan grow
    # without bound (1.5, -1.69, 2.32, -5.11, 32.3, ...).
    with pytest.raises(DivergenceError):
        newton(np.arctan, lambda x: 1.0 / (1.0 + x * x), 1.5)


def test_not_converged_within_max_iter():
    with pytest.raises(NotConvergedError):
        bisection(square_minus_two, 1.0, 2.0, max_iter=3)
    with pytest.raises(NotConvergedError):
        newton(square_minus_two, square_minus_two_prime, 10.0, max_iter=2)


def test_failures_are_value_errors():
    for error in (NoSignChangeError, ZeroDerivativeError, DivergenceError, NotConvergedError):
        assert issubclass(error, ValueError)


@pytest.mark.parametrize(
    "call, error",
    [
        (lambda: bisection(square_minus_two, 2.0, 1.0), ValueError),
        (lambda: bisection(square_minus_two, 1.0, 2.0, xtol=-1.0), ValueError),
        (lambda: bisection(square_minus_two, 1.0, 2.0, xtol=0.0, ftol=0.0), ValueError),
        (lambda: bisection(square_minus_two, 1.0, 2.0, max_iter=0), ValueError),
        (lambda: bisection(square_minus_two, 1.0, 2.0, xtol="small"), TypeError),
        (lambda: secant(square_minus_two, 1.0, 1.0), ValueError),
        (lambda: newton(square_minus_two, "derivative", 1.0), TypeError),
        (lambda: newton(square_minus_two, square_minus_two_prime, np.nan), ValueError),
        # f returning NaN (e.g. log of a negative number) is reported as divergence.
        (lambda: newton(lambda x: float("nan"), lambda x: 1.0, 1.0), DivergenceError),
    ],
)
def test_invalid_inputs(call, error):
    with pytest.raises(error):
        call()
