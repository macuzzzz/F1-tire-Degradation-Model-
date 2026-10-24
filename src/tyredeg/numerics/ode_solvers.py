"""From-scratch ODE solvers: forward Euler, Heun, RK4 and adaptive RK45.

All solvers integrate an initial value problem

    dy/dt = f(t, y),   y(t0) = y0,   t0 <= t <= t_end

where ``f(t, y)`` has the same signature as in SciPy. ``y`` may be a scalar
or a vector. Every solver counts how many times it calls ``f`` ("function
evaluations", nfev), because calls to ``f`` dominate the cost of solving an
ODE and are the fair way to compare methods (Phase 8).

Fixed-step methods (DECISIONS.md D30)
-------------------------------------
``euler``, ``heun`` and ``rk4`` take a step size ``h``. If ``h`` does not
divide the interval exactly, the last step is shortened so the solution
ends exactly at ``t_end``. Order of accuracy (global error ~ C h^p):

======  =====  =============================  ======================
Method  Order  Function evaluations per step  Idea
======  =====  =============================  ======================
Euler   1      1                              slope at the start
Heun    2      2                              average of start slope
                                              and predicted end slope
RK4     4      4                              weighted average of 4
                                              slopes across the step
======  =====  =============================  ======================

Adaptive method (D25-D29)
-------------------------
``rk45`` uses the Dormand-Prince 5(4) embedded pair: each step computes a
5th-order and a 4th-order solution from the same 7 slopes. Their difference
estimates the local error, which a controller uses to accept/reject the step
and choose the next step size. The 5th-order solution is kept ("local
extrapolation"). The 7th slope of a step equals the 1st slope of the next
step ("first same as last", FSAL), so an accepted step costs 6 new
evaluations.

References: Dormand & Prince (1980), J. Comput. Appl. Math. 6(1), 19-26;
Hairer, Norsett & Wanner, Solving Ordinary Differential Equations I,
2nd ed. (1993), Sections II.4-II.5 (coefficients: Table 5.2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Defaults; identical to the `numerics.ode` section of config.yaml (D38).
DEFAULT_RTOL = 1.0e-3
DEFAULT_ATOL = 1.0e-6
DEFAULT_INITIAL_STEP_FRACTION = 0.01
DEFAULT_MAX_STEPS = 10000
DEFAULT_SAFETY = 0.9
DEFAULT_MIN_FACTOR = 0.2
DEFAULT_MAX_FACTOR = 10.0

EPS = np.finfo(float).eps

# ---------------------------------------------------------------------------
# Dormand-Prince 5(4) Butcher tableau (Hairer, Norsett & Wanner, Table 5.2)
# ---------------------------------------------------------------------------
# Nodes c_i: stage i is evaluated at time t + c_i * h.
DP_C = np.array([0.0, 1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0])
# Coupling coefficients a_ij: stage i uses y + h * sum_j a_ij * k_j.
DP_A = np.array(
    [
        [0, 0, 0, 0, 0, 0],
        [1 / 5, 0, 0, 0, 0, 0],
        [3 / 40, 9 / 40, 0, 0, 0, 0],
        [44 / 45, -56 / 15, 32 / 9, 0, 0, 0],
        [19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729, 0, 0],
        [9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656, 0],
        [35 / 384, 0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84],
    ],
    dtype=float,
)
# 5th-order weights (used to advance). They equal the last row of DP_A, which
# is why the 7th stage is the slope at the new point (FSAL).
DP_B5 = np.array([35 / 384, 0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84, 0])
# 4th-order weights (only used for the error estimate).
DP_B4 = np.array(
    [5179 / 57600, 0, 7571 / 16695, 393 / 640, -92097 / 339200, 187 / 2100, 1 / 40]
)
# Local error estimate = h * sum_i (b5_i - b4_i) * k_i.
DP_E = DP_B5 - DP_B4
# The error estimate comes from the 4th-order formula, so the local error
# scales like h^5 and the controller exponent is -1/(4 + 1).
ERROR_EXPONENT = -1.0 / 5.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
class _CountingFunction:
    """Wrap ``f`` so every call is counted and the result has the right shape."""

    def __init__(self, f, scalar_problem, dimension):
        self.f = f
        self.scalar_problem = scalar_problem
        self.dimension = dimension
        self.calls = 0

    def __call__(self, t, y):
        self.calls += 1
        # Scalar problems are given a plain float, so f can use math functions.
        argument = float(y[0]) if self.scalar_problem else y.copy()
        slope = np.asarray(self.f(t, argument), dtype=float).reshape(-1)
        if slope.size != self.dimension:
            raise ValueError(
                f"f returned {slope.size} values but y has {self.dimension} components."
            )
        if not np.all(np.isfinite(slope)):
            raise ValueError(f"f returned a non-finite value at t = {t}.")
        return slope


def _check_problem(f, t_span, y0):
    """Validate the common inputs; return (t0, t_end, y0 as 1-D array, is_scalar)."""
    if not callable(f):
        raise TypeError("f must be callable as f(t, y).")
    if not isinstance(t_span, (tuple, list)) or len(t_span) != 2:
        raise TypeError("t_span must be a (t0, t_end) pair.")
    t0, t_end = float(t_span[0]), float(t_span[1])
    if not (np.isfinite(t0) and np.isfinite(t_end)):
        raise ValueError("t_span must contain finite numbers.")
    if t_end <= t0:
        raise ValueError(f"t_end must be greater than t0, got t_span = {t_span}.")
    y0_array = np.asarray(y0, dtype=float)
    if y0_array.ndim > 1:
        raise ValueError("y0 must be a scalar or a 1-D array.")
    if y0_array.size == 0:
        raise ValueError("y0 must not be empty.")
    if not np.all(np.isfinite(y0_array)):
        raise ValueError("y0 must contain finite numbers.")
    return t0, t_end, y0_array.reshape(-1).copy(), y0_array.ndim == 0


def _time_grid(t0, t_end, h):
    """Time points t0, t0 + h, ..., t_end; the last step is shortened if needed."""
    if isinstance(h, bool) or not isinstance(h, (int, float, np.floating)):
        raise TypeError(f"h must be a number, got {h!r}.")
    if not np.isfinite(h) or h <= 0:
        raise ValueError(f"h must be a finite number > 0, got {h}.")
    if h > t_end - t0:
        raise ValueError(f"h ({h}) is larger than the interval length ({t_end - t0}).")
    ratio = (t_end - t0) / h
    # Rounding errors can make e.g. 2.0 / 0.1 = 19.999999999999996; treat
    # values within 1e-9 of a whole number as exact so no tiny last step appears.
    if abs(ratio - round(ratio)) < 1e-9 * max(1.0, ratio):
        n_steps = int(round(ratio))
    else:
        n_steps = int(np.ceil(ratio))
    times = t0 + h * np.arange(n_steps + 1)
    times[-1] = t_end
    return times


def _format_output(times, states, scalar_problem):
    """Return y as 1-D for scalar problems, else shape (n_points, dimension)."""
    states = np.array(states)
    if scalar_problem:
        return times, states[:, 0]
    return times, states


def _fixed_step_solve(step, f, t_span, y0, h):
    """Run a one-step method ``step(f, t, y, h)`` over the whole time grid."""
    t0, t_end, y, scalar_problem = _check_problem(f, t_span, y0)
    counted_f = _CountingFunction(f, scalar_problem, y.size)
    times = _time_grid(t0, t_end, h)
    states = [y.copy()]
    for k in range(len(times) - 1):
        step_size = times[k + 1] - times[k]
        y = step(counted_f, times[k], y, step_size)
        states.append(y.copy())
    t_out, y_out = _format_output(times, states, scalar_problem)
    return t_out, y_out, counted_f.calls


# ---------------------------------------------------------------------------
# One-step formulas
# ---------------------------------------------------------------------------
def _euler_step(f, t, y, h):
    # Follow the slope at the start of the step: error O(h^2) per step.
    return y + h * f(t, y)


def _heun_step(f, t, y, h):
    slope_start = f(t, y)
    # Predict the end point with Euler, then average the two slopes
    # (trapezoidal idea), which cancels the O(h^2) error term.
    y_predicted = y + h * slope_start
    slope_end = f(t + h, y_predicted)
    return y + h * (slope_start + slope_end) / 2.0


def _rk4_step(f, t, y, h):
    k1 = f(t, y)
    k2 = f(t + h / 2, y + h / 2 * k1)
    k3 = f(t + h / 2, y + h / 2 * k2)
    k4 = f(t + h, y + h * k3)
    # Simpson-like weights 1-2-2-1 make the step agree with the Taylor series
    # up to h^4.
    return y + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)


# ---------------------------------------------------------------------------
# Public fixed-step solvers
# ---------------------------------------------------------------------------
def euler(f, t_span, y0, h):
    """Solve dy/dt = f(t, y) with the forward Euler method (order 1).

    Parameters
    ----------
    f : callable
        Right-hand side ``f(t, y)``; returns a float (scalar problem) or an
        array with the same length as ``y0``.
    t_span : tuple of float
        ``(t0, t_end)`` with ``t_end > t0`` (e.g. tyre age in laps).
    y0 : float or array_like
        Initial value(s) at ``t0``, finite.
    h : float
        Step size, ``0 < h <= t_end - t0``. If it does not divide the
        interval, the last step is shortened.

    Returns
    -------
    t : numpy.ndarray
        Time points, shape (n_points,), from ``t0`` to exactly ``t_end``.
    y : numpy.ndarray
        Solution, shape (n_points,) for scalar ``y0`` or (n_points, dim).
    nfev : int
        Number of calls to ``f`` (1 per step).

    Raises
    ------
    TypeError
        If ``f`` is not callable, ``t_span`` is not a pair or ``h`` not a number.
    ValueError
        For an empty/non-finite ``y0``, ``t_end <= t0``, an invalid ``h``, or if
        ``f`` returns the wrong number of values or a non-finite value.

    Example
    -------
    >>> t, y, nfev = euler(lambda t, y: -y, (0.0, 1.0), 1.0, 0.5)
    >>> y.tolist(), nfev
    ([1.0, 0.5, 0.25], 2)
    """
    return _fixed_step_solve(_euler_step, f, t_span, y0, h)


def heun(f, t_span, y0, h):
    """Solve dy/dt = f(t, y) with Heun's method (explicit trapezoidal, order 2).

    Parameters, returns and raises are as for :func:`euler`; ``nfev`` is
    2 per step.

    Example
    -------
    >>> t, y, nfev = heun(lambda t, y: -y, (0.0, 1.0), 1.0, 0.5)
    >>> [round(float(v), 6) for v in y], nfev
    ([1.0, 0.625, 0.390625], 4)
    """
    return _fixed_step_solve(_heun_step, f, t_span, y0, h)


def rk4(f, t_span, y0, h):
    """Solve dy/dt = f(t, y) with the classical 4th-order Runge-Kutta method.

    Parameters, returns and raises are as for :func:`euler`; ``nfev`` is
    4 per step.

    Example
    -------
    >>> t, y, nfev = rk4(lambda t, y: -y, (0.0, 1.0), 1.0, 0.5)
    >>> round(float(y[-1]), 6), nfev
    (0.368171, 8)
    """
    return _fixed_step_solve(_rk4_step, f, t_span, y0, h)


# ---------------------------------------------------------------------------
# Adaptive RK45 (Dormand-Prince)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RK45Stats:
    """Step statistics of an :func:`rk45` run.

    Attributes
    ----------
    n_accepted : int
        Accepted steps.
    n_rejected : int
        Rejected (and repeated with a smaller step) steps.
    """

    n_accepted: int
    n_rejected: int


def _rms_error_norm(error, y_old, y_new, rtol, atol):
    """Scaled RMS norm of the error estimate (D26); <= 1 means "accept".

    Each component is divided by atol + rtol * max(|y_old|, |y_new|): the
    absolute part matters when y is near 0 (the wear ODE starts at d = 0),
    the relative part when y is large.
    """
    scale = atol + rtol * np.maximum(np.abs(y_old), np.abs(y_new))
    return float(np.sqrt(np.mean((error / scale) ** 2)))


def _dormand_prince_step(f, t, y, h, k1):
    """One Dormand-Prince step from (t, y); returns (y_new, error, k7).

    ``k1`` is the slope at (t, y), reused from the previous step (FSAL).
    """
    slopes = np.zeros((7, y.size))
    slopes[0] = k1
    for stage in range(1, 7):
        increment = h * (DP_A[stage, :stage] @ slopes[:stage])
        slopes[stage] = f(t + DP_C[stage] * h, y + increment)
    y_new = y + h * (DP_B5 @ slopes)
    error = h * (DP_E @ slopes)
    return y_new, error, slopes[6]


def _check_rk45_settings(rtol, atol, h0, max_steps, safety, min_factor, max_factor):
    """Raise for invalid RK45 settings."""
    for name, value in (("rtol", rtol), ("atol", atol), ("safety", safety),
                        ("min_factor", min_factor), ("max_factor", max_factor)):
        if isinstance(value, bool) or not isinstance(value, (int, float, np.floating)):
            raise TypeError(f"{name} must be a number, got {value!r}.")
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a finite number > 0, got {value}.")
    if h0 is not None and (not np.isfinite(h0) or h0 <= 0):
        raise ValueError(f"h0 must be a finite number > 0, got {h0}.")
    if isinstance(max_steps, bool) or not isinstance(max_steps, (int, np.integer)) or max_steps < 1:
        raise ValueError(f"max_steps must be an integer >= 1, got {max_steps!r}.")
    if safety > 1:
        raise ValueError(f"safety must be <= 1, got {safety}.")
    if not min_factor < 1 < max_factor:
        raise ValueError("Need min_factor < 1 < max_factor.")


def rk45(
    f,
    t_span,
    y0,
    rtol=DEFAULT_RTOL,
    atol=DEFAULT_ATOL,
    h0=None,
    max_steps=DEFAULT_MAX_STEPS,
    safety=DEFAULT_SAFETY,
    min_factor=DEFAULT_MIN_FACTOR,
    max_factor=DEFAULT_MAX_FACTOR,
):
    """Solve dy/dt = f(t, y) with the adaptive Dormand-Prince 5(4) method.

    Step-size control (D27): after each step the scaled RMS error ``err`` is
    computed. If ``err <= 1`` the step is accepted. Either way the next step
    size is ``h * clip(safety * err**(-1/5), min_factor, max_factor)``;
    after a rejection the step is not allowed to grow on the retry.

    Parameters
    ----------
    f : callable
        Right-hand side ``f(t, y)``.
    t_span : tuple of float
        ``(t0, t_end)`` with ``t_end > t0``.
    y0 : float or array_like
        Initial value(s), finite.
    rtol, atol : float, optional
        Relative and absolute tolerance, > 0. Defaults 1e-3 and 1e-6 (SciPy's
        defaults, D29). Tighten them for more accuracy.
    h0 : float or None, optional
        First step size; default ``0.01 * (t_end - t0)`` (D28).
    max_steps : int, optional
        Maximum number of step attempts (accepted + rejected). Default 10000.
    safety : float, optional
        Safety factor in (0, 1]. Default 0.9.
    min_factor, max_factor : float, optional
        Limits on how much one step may shrink or grow, with
        ``min_factor < 1 < max_factor``. Defaults 0.2 and 10.

    Returns
    -------
    t : numpy.ndarray
        Accepted time points, from ``t0`` to exactly ``t_end``.
    y : numpy.ndarray
        Solution at ``t``; shape (n_points,) or (n_points, dim).
    nfev : int
        Number of calls to ``f``.
    stats : RK45Stats
        Numbers of accepted and rejected steps.

    Raises
    ------
    TypeError
        For non-callable ``f`` or non-numeric settings.
    ValueError
        For invalid inputs/settings, if the step size falls below
        ``10 * eps * max(1, |t|)`` (no progress possible), or if
        ``max_steps`` is exceeded.

    Example
    -------
    >>> t, y, nfev, stats = rk45(lambda t, y: -y, (0.0, 2.0), 1.0, rtol=1e-8, atol=1e-10)
    >>> bool(abs(float(y[-1]) - np.exp(-2.0)) < 1e-8)
    True
    """
    _check_rk45_settings(rtol, atol, h0, max_steps, safety, min_factor, max_factor)
    t0, t_end, y, scalar_problem = _check_problem(f, t_span, y0)
    counted_f = _CountingFunction(f, scalar_problem, y.size)

    h = DEFAULT_INITIAL_STEP_FRACTION * (t_end - t0) if h0 is None else float(h0)
    t = t0
    k1 = counted_f(t, y)
    times, states = [t], [y.copy()]
    n_accepted, n_rejected = 0, 0
    previous_rejected = False

    while t < t_end:
        if n_accepted + n_rejected >= max_steps:
            raise ValueError(f"rk45 exceeded max_steps = {max_steps} at t = {t}.")
        if h < 10 * EPS * max(1.0, abs(t)):
            raise ValueError(f"rk45 step size became too small ({h:.3e}) at t = {t}.")
        # Do not step past the end of the interval.
        h = min(h, t_end - t)

        y_new, error, k7 = _dormand_prince_step(counted_f, t, y, h, k1)
        err = _rms_error_norm(error, y, y_new, rtol, atol)

        if err <= 1.0:
            # Accept: move forward and reuse the last slope (FSAL).
            t = t_end if t_end - (t + h) <= 10 * EPS * max(1.0, abs(t_end)) else t + h
            y, k1 = y_new, k7
            times.append(t)
            states.append(y.copy())
            n_accepted += 1
            factor = max_factor if err == 0 else safety * err ** ERROR_EXPONENT
            factor = min(max_factor, factor)
            if previous_rejected:
                factor = min(1.0, factor)
            previous_rejected = False
        else:
            n_rejected += 1
            factor = max(min_factor, safety * err ** ERROR_EXPONENT)
            previous_rejected = True
        h = h * factor

    t_out, y_out = _format_output(np.array(times), states, scalar_problem)
    return t_out, y_out, counted_f.calls, RK45Stats(n_accepted, n_rejected)
