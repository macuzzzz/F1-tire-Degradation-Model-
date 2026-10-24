"""From-scratch root finding: bisection, secant and Newton-Raphson.

Each method looks for x with f(x) = 0 and returns a :class:`RootResult`
holding the root, the number of iterations and the full convergence history
(every iterate), which the tests use to measure the convergence rate.

==========  ==================  ======================  ========================
Method      Needs               Convergence             Weak point
==========  ==================  ======================  ========================
bisection   a < b with a sign   linear: the bracket     slow (1 bit per step)
            change on [a, b]    halves every step
secant      two starting        superlinear, order      can diverge from a poor
            points              (1 + sqrt 5)/2 ~ 1.618  start
newton      f'(x) and one       quadratic (order 2)     needs f'; fails if
            starting point                              f'(x) = 0
==========  ==================  ======================  ========================

Stopping rule (DECISIONS.md D30, amended by OI-4): stop only when BOTH the
step is small, |x_new - x_old| <= xtol, AND the residual is small,
|f(x_new)| <= ftol. Requiring both protects against the two ways a single
test can stop too early: on a flat function (e.g. (x - 1)^3) |f| is tiny
long before x is accurate, and on a steep function a small step can still
leave a large |f|. Setting one tolerance to 0 switches that test off, so
``ftol=0`` means "step test only" and ``xtol=0`` means "residual test only".

Round-off safeguard: floating-point numbers near x are about eps*|x| apart,
so for a steep function even the closest representable x can leave
|f| > ftol. Requiring both tests would then never stop. The iteration
therefore also stops when the step has shrunk to round-off level,
|step| <= 4 * eps * |x|: x cannot become any more accurate, so it is
returned as the best root available in floating point.

Failures (D31) raise a subclass of ``ValueError``:
:class:`NoSignChangeError`, :class:`ZeroDerivativeError`,
:class:`DivergenceError` (non-finite iterate or |x| > divergence_limit) and
:class:`NotConvergedError` (max_iter reached).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Defaults; identical to `numerics.root_finding` in config.yaml (D38).
DEFAULT_XTOL = 1.0e-10
DEFAULT_FTOL = 1.0e-12
DEFAULT_MAX_ITER = 100
DEFAULT_DIVERGENCE_LIMIT = 1.0e10

EPS = np.finfo(float).eps
# A step of at most this many floating-point spacings (eps * |x|) means x can
# no longer change meaningfully. Like the pivot tolerance in
# linear_solvers.py, this is a machine-precision constant, not a tuning choice.
ROUNDOFF_STEPS = 4


class NoSignChangeError(ValueError):
    """Bisection was given an interval where f does not change sign.

    Example
    -------
    >>> bisection(lambda x: x**2 + 1, -1.0, 1.0)
    Traceback (most recent call last):
    ...
    tyredeg.numerics.root_finding.NoSignChangeError: f(a) = 2.0 and f(b) = 2.0 have the same sign; no bracket.
    """


class ZeroDerivativeError(ValueError):
    """Newton hit f'(x) = 0, or secant hit f(x_k) = f(x_{k-1}): no step possible.

    Example
    -------
    >>> newton(lambda x: x**2 - 1, lambda x: 2 * x, 0.0)
    Traceback (most recent call last):
    ...
    tyredeg.numerics.root_finding.ZeroDerivativeError: f'(x) = 0 at x = 0.0; Newton step undefined.
    """


class DivergenceError(ValueError):
    """An iterate became non-finite or larger than the divergence limit.

    Example
    -------
    >>> issubclass(DivergenceError, ValueError)
    True
    """


class NotConvergedError(ValueError):
    """The tolerance was not reached within max_iter iterations.

    Example
    -------
    >>> bisection(lambda x: x - 0.3, 0.0, 1.0, max_iter=3)
    Traceback (most recent call last):
    ...
    tyredeg.numerics.root_finding.NotConvergedError: bisection did not converge in 3 iterations.
    """


@dataclass(frozen=True)
class RootResult:
    """Result of a root finder.

    Attributes
    ----------
    root : float
        Approximation of x with f(x) = 0.
    iterations : int
        Number of iterations performed.
    history : numpy.ndarray
        Every iterate in order (bisection: the midpoints; secant: including
        both starting points; Newton: including the starting point).

    Example
    -------
    >>> result = bisection(lambda x: x**2 - 2, 0.0, 2.0)
    >>> round(result.root, 10), result.iterations
    (1.4142135624, 39)
    """

    root: float
    iterations: int
    history: np.ndarray


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------
def _check_settings(xtol, ftol, max_iter):
    """Raise for invalid tolerances or iteration limits."""
    for name, value in (("xtol", xtol), ("ftol", ftol)):
        if isinstance(value, bool) or not isinstance(value, (int, float, np.floating)):
            raise TypeError(f"{name} must be a number, got {value!r}.")
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite number >= 0, got {value}.")
    if xtol == 0 and ftol == 0:
        raise ValueError("At least one of xtol and ftol must be > 0, or no stop is possible.")
    if isinstance(max_iter, bool) or not isinstance(max_iter, (int, np.integer)) or max_iter < 1:
        raise ValueError(f"max_iter must be an integer >= 1, got {max_iter!r}.")


def _evaluate(f, x):
    """Return f(x) as a float, raising if it is not finite."""
    value = float(f(x))
    if not np.isfinite(value):
        raise DivergenceError(f"f({x}) is not finite ({value}).")
    return value


def _check_iterate(x, divergence_limit, method):
    """Raise DivergenceError if x is non-finite or too large."""
    if not np.isfinite(x) or abs(x) > divergence_limit:
        raise DivergenceError(f"{method} diverged: iterate {x} exceeds the limit {divergence_limit}.")


def _is_converged(step, f_value, x, xtol, ftol):
    """Stopping rule (D30 amended, OI-4): small step AND small residual,
    or a step so small that x has reached floating-point precision.

    A tolerance of 0 means that test is switched off (always passes).
    """
    step_is_small = xtol == 0 or abs(step) <= xtol
    residual_is_small = ftol == 0 or abs(f_value) <= ftol
    at_roundoff_level = abs(step) <= ROUNDOFF_STEPS * EPS * abs(x)
    return (step_is_small and residual_is_small) or at_roundoff_level


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------
def bisection(f, a, b, xtol=DEFAULT_XTOL, ftol=DEFAULT_FTOL, max_iter=DEFAULT_MAX_ITER):
    """Find a root of f in [a, b] by repeatedly halving the bracket.

    Because f(a) and f(b) have opposite signs, the continuous function f
    must cross zero between them (intermediate value theorem). Each step
    keeps the half that still has a sign change, so after k steps the root
    is known to within (b - a) / 2^(k+1).

    Parameters
    ----------
    f : callable
        Continuous function of one float.
    a, b : float
        Bracket ends with ``a < b`` and ``f(a) * f(b) <= 0``.
    xtol : float, optional
        Step tolerance: the half-width of the bracket must be <= xtol (>= 0;
        0 switches the test off). Default 1e-10. See the module docstring.
    ftol : float, optional
        Residual tolerance: |f(midpoint)| must be <= ftol (>= 0; 0 switches
        the test off). Default 1e-12.
    max_iter : int, optional
        Maximum iterations (>= 1). Default 100.

    Returns
    -------
    RootResult

    Raises
    ------
    TypeError, ValueError
        For invalid arguments (e.g. ``a >= b``, negative tolerances).
    NoSignChangeError
        If ``f(a)`` and ``f(b)`` have the same sign.
    NotConvergedError
        If the tolerance is not reached in ``max_iter`` iterations.

    Example
    -------
    >>> result = bisection(lambda x: x**2 - 2, 1.0, 2.0)
    >>> round(result.root, 9), result.iterations
    (1.414213562, 38)
    """
    _check_settings(xtol, ftol, max_iter)
    a, b = float(a), float(b)
    if not (np.isfinite(a) and np.isfinite(b)) or a >= b:
        raise ValueError(f"Need finite a < b, got a = {a}, b = {b}.")
    f_a, f_b = _evaluate(f, a), _evaluate(f, b)
    if f_a == 0:
        return RootResult(a, 0, np.array([a]))
    if f_b == 0:
        return RootResult(b, 0, np.array([b]))
    if f_a * f_b > 0:
        raise NoSignChangeError(f"f(a) = {f_a} and f(b) = {f_b} have the same sign; no bracket.")

    history = []
    for iteration in range(1, max_iter + 1):
        midpoint = (a + b) / 2.0
        f_mid = _evaluate(f, midpoint)
        history.append(midpoint)
        half_width = (b - a) / 2.0
        # The half-width bounds the distance to the root, so it is the step test.
        if _is_converged(half_width, f_mid, midpoint, xtol, ftol):
            return RootResult(midpoint, iteration, np.array(history))
        # Keep the half in which the sign changes.
        if f_a * f_mid < 0:
            b = midpoint
        else:
            a, f_a = midpoint, f_mid
    raise NotConvergedError(f"bisection did not converge in {max_iter} iterations.")


def secant(
    f,
    x0,
    x1,
    xtol=DEFAULT_XTOL,
    ftol=DEFAULT_FTOL,
    max_iter=DEFAULT_MAX_ITER,
    divergence_limit=DEFAULT_DIVERGENCE_LIMIT,
):
    """Find a root of f with the secant method.

    Newton's method with the derivative replaced by the slope of the line
    through the last two iterates:
    ``x_new = x1 - f(x1) * (x1 - x0) / (f(x1) - f(x0))``.

    Parameters
    ----------
    f : callable
        Function of one float.
    x0, x1 : float
        Two different starting points, ideally close to the root.
    xtol, ftol : float, optional
        Stopping tolerances (see module docstring). Defaults 1e-10, 1e-12.
    max_iter : int, optional
        Maximum iterations (>= 1). Default 100.
    divergence_limit : float, optional
        Iterates with |x| above this count as diverged (> 0). Default 1e10.

    Returns
    -------
    RootResult
        ``history`` starts with ``x0, x1``.

    Raises
    ------
    TypeError, ValueError
        For invalid arguments (e.g. ``x0 == x1``).
    ZeroDerivativeError
        If ``f(x1) == f(x0)`` (the secant line is horizontal).
    DivergenceError
        If an iterate is non-finite or exceeds ``divergence_limit``.
    NotConvergedError
        If the tolerance is not reached in ``max_iter`` iterations.

    Example
    -------
    >>> result = secant(lambda x: x**2 - 2, 1.0, 2.0)
    >>> round(result.root, 12), result.iterations
    (1.414213562373, 7)
    """
    _check_settings(xtol, ftol, max_iter)
    x0, x1 = float(x0), float(x1)
    if not (np.isfinite(x0) and np.isfinite(x1)) or x0 == x1:
        raise ValueError(f"Need two different finite starting points, got {x0} and {x1}.")
    f0, f1 = _evaluate(f, x0), _evaluate(f, x1)
    history = [x0, x1]
    for iteration in range(1, max_iter + 1):
        if f1 == f0:
            raise ZeroDerivativeError(f"f(x) is equal at {x0} and {x1}; secant slope is zero.")
        step = -f1 * (x1 - x0) / (f1 - f0)
        x_new = x1 + step
        _check_iterate(x_new, divergence_limit, "secant")
        f_new = _evaluate(f, x_new)
        history.append(x_new)
        if _is_converged(step, f_new, x_new, xtol, ftol):
            return RootResult(x_new, iteration, np.array(history))
        x0, f0, x1, f1 = x1, f1, x_new, f_new
    raise NotConvergedError(f"secant did not converge in {max_iter} iterations.")


def newton(
    f,
    fprime,
    x0,
    xtol=DEFAULT_XTOL,
    ftol=DEFAULT_FTOL,
    max_iter=DEFAULT_MAX_ITER,
    divergence_limit=DEFAULT_DIVERGENCE_LIMIT,
):
    """Find a root of f with Newton-Raphson: ``x_new = x - f(x) / f'(x)``.

    Each step follows the tangent line at x down to zero. Near a simple root
    the number of correct digits roughly doubles every iteration.

    Parameters
    ----------
    f : callable
        Function of one float.
    fprime : callable
        Its derivative f'(x) (analytic, or e.g. a central difference).
    x0 : float
        Starting point, ideally close to the root.
    xtol, ftol : float, optional
        Stopping tolerances (see module docstring). Defaults 1e-10, 1e-12.
    max_iter : int, optional
        Maximum iterations (>= 1). Default 100.
    divergence_limit : float, optional
        Iterates with |x| above this count as diverged (> 0). Default 1e10.

    Returns
    -------
    RootResult
        ``history`` starts with ``x0``.

    Raises
    ------
    TypeError, ValueError
        For invalid arguments.
    ZeroDerivativeError
        If ``f'(x) == 0`` at an iterate (the tangent never reaches zero).
    DivergenceError
        If an iterate is non-finite or exceeds ``divergence_limit``.
    NotConvergedError
        If the tolerance is not reached in ``max_iter`` iterations.

    Example
    -------
    >>> result = newton(lambda x: x**2 - 2, lambda x: 2 * x, 1.0)
    >>> round(result.root, 12), result.iterations
    (1.414213562373, 5)
    """
    _check_settings(xtol, ftol, max_iter)
    if not callable(fprime):
        raise TypeError("fprime must be callable.")
    x = float(x0)
    if not np.isfinite(x):
        raise ValueError(f"x0 must be finite, got {x0}.")
    f_x = _evaluate(f, x)
    history = [x]
    for iteration in range(1, max_iter + 1):
        slope = _evaluate(fprime, x)
        if slope == 0:
            raise ZeroDerivativeError(f"f'(x) = 0 at x = {x}; Newton step undefined.")
        step = -f_x / slope
        x = x + step
        _check_iterate(x, divergence_limit, "newton")
        f_x = _evaluate(f, x)
        history.append(x)
        if _is_converged(step, f_x, x, xtol, ftol):
            return RootResult(x, iteration, np.array(history))
    raise NotConvergedError(f"newton did not converge in {max_iter} iterations.")
