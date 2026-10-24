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
# Stopping rule (D30)
# ---------------------------------------------------------------------------
def test_tighter_tolerance_gives_more_accurate_root():
    loose = bisection(square_minus_two, 1.0, 2.0, xtol=1e-4, ftol=0.0)
    tight = bisection(square_minus_two, 1.0, 2.0, xtol=1e-12, ftol=0.0)
    assert tight.iterations > loose.iterations
    assert abs(tight.root - ROOT_2) < abs(loose.root - ROOT_2)


def test_either_tolerance_alone_can_stop_the_iteration():
    by_step = newton(square_minus_two, square_minus_two_prime, 1.0, ftol=0.0)
    by_residual = newton(square_minus_two, square_minus_two_prime, 1.0, xtol=0.0)
    assert abs(by_step.root - ROOT_2) < 1e-10
    assert abs(square_minus_two(by_residual.root)) <= 1e-12


def test_residual_test_stops_early_on_a_flat_function():
    # Documented weakness of the residual test (study, N7): for (x-1)^3 the
    # residual is tiny long before x is accurate, so the "either" rule stops
    # with |x - 1| ~ 1e-4, whereas the step test alone reaches ~1e-10.
    f = lambda x: (x - 1.0) ** 3  # noqa: E731
    either = bisection(f, 0.5, 1.7)
    step_only = bisection(f, 0.5, 1.7, ftol=0.0)
    assert abs(either.root - 1.0) > 1e-5
    assert abs(step_only.root - 1.0) < 1e-9


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
