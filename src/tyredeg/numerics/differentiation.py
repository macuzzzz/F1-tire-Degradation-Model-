"""From-scratch finite differences for functions and for sampled arrays.

Formulas (h = step size), with their truncation error from Taylor series:

=========================  =========================================  =======
Name                       Formula                                    Error
=========================  =========================================  =======
forward, 1st derivative    (f(x+h) - f(x)) / h                        O(h)
backward, 1st derivative   (f(x) - f(x-h)) / h                        O(h)
central, 1st derivative    (f(x+h) - f(x-h)) / (2h)                   O(h^2)
central, 2nd derivative    (f(x+h) - 2 f(x) + f(x-h)) / h^2           O(h^2)
=========================  =========================================  =======

Choosing h (DECISIONS.md D32)
-----------------------------
A smaller h reduces the truncation error C h^p, but each f value carries a
round-off error of about eps |f| (eps = 2.2e-16), and dividing by h^m
amplifies it to about eps / h^m. The total C h^p + eps / h^m is smallest
when both terms are similar, at h ~ eps^(1/(p+m)):

- forward/backward (p = 1, m = 1): h = eps^(1/2) ~ 1.5e-8
- central 1st      (p = 2, m = 1): h = eps^(1/3) ~ 6.1e-6
- central 2nd      (p = 2, m = 2): h = eps^(1/4) ~ 1.2e-4

The default step is that value times max(1, |x|), so it scales with x.
Reference: Nocedal & Wright, Numerical Optimization, 2nd ed., Section 8.1.

Sampled arrays (D33)
--------------------
For values y_i = f(x_i) on a uniform grid with spacing h, the same formulas
are applied between neighbouring samples. For the central formulas the two
end points use second-order one-sided formulas, so the result is O(h^2)
everywhere (as ``numpy.gradient(..., edge_order=2)``).
"""

from __future__ import annotations

import numpy as np

# Defaults; identical to `numerics.differentiation` in config.yaml (D38).
FORWARD_STEP_EXPONENT = 0.5
CENTRAL_STEP_EXPONENT = 1.0 / 3.0
SECOND_STEP_EXPONENT = 0.25

EPS = np.finfo(float).eps

# Relative tolerance for deciding that sample spacing is uniform.
UNIFORM_SPACING_RTOL = 1e-9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def default_step(x, exponent):
    """Return the default step ``eps**exponent * max(1, |x|)``.

    Parameters
    ----------
    x : float or array_like
        Point(s) where the derivative is wanted.
    exponent : float
        0.5 (forward/backward), 1/3 (central) or 0.25 (second derivative).

    Returns
    -------
    float or numpy.ndarray
        Step size(s) > 0.

    Example
    -------
    >>> float(default_step(1.0, 0.5)) == float(np.sqrt(np.finfo(float).eps))
    True
    """
    return EPS**exponent * np.maximum(1.0, np.abs(np.asarray(x, dtype=float)))


def _step(x, h, exponent):
    """Return h if given (checked), else the default step for x."""
    if h is None:
        return default_step(x, exponent)
    h = np.asarray(h, dtype=float)
    if not np.all(np.isfinite(h)) or np.any(h <= 0):
        raise ValueError(f"h must be finite and > 0, got {h}.")
    return h


def _point(x):
    """Return x as a float array, raising if it is not finite."""
    if isinstance(x, str):
        raise TypeError("x must be a number or an array of numbers.")
    x = np.asarray(x, dtype=float)
    if not np.all(np.isfinite(x)):
        raise ValueError("x must be finite.")
    return x


def _check_function(f):
    if not callable(f):
        raise TypeError("f must be callable.")


def _scalar_or_array(values):
    """Return a float for 0-d results, else the array."""
    values = np.asarray(values, dtype=float)
    return float(values) if values.ndim == 0 else values


# ---------------------------------------------------------------------------
# Derivatives of a function
# ---------------------------------------------------------------------------
def forward_difference(f, x, h=None):
    """First derivative of f at x by the forward difference (error O(h)).

    Parameters
    ----------
    f : callable
        Function of x; must accept arrays if ``x`` is an array.
    x : float or array_like
        Point(s), finite.
    h : float or None, optional
        Step > 0. Default ``sqrt(eps) * max(1, |x|)`` (D32).

    Returns
    -------
    float or numpy.ndarray
        Approximation of f'(x).

    Raises
    ------
    TypeError
        If ``f`` is not callable.
    ValueError
        If ``x`` is not finite or ``h`` is not > 0.

    Example
    -------
    >>> bool(round(forward_difference(np.sin, 1.0), 6) == round(np.cos(1.0), 6))
    True
    """
    _check_function(f)
    x = _point(x)
    h = _step(x, h, FORWARD_STEP_EXPONENT)
    return _scalar_or_array((f(x + h) - f(x)) / h)


def backward_difference(f, x, h=None):
    """First derivative of f at x by the backward difference (error O(h)).

    Parameters, returns and raises as for :func:`forward_difference`.

    Example
    -------
    >>> bool(round(backward_difference(np.sin, 1.0), 6) == round(np.cos(1.0), 6))
    True
    """
    _check_function(f)
    x = _point(x)
    h = _step(x, h, FORWARD_STEP_EXPONENT)
    return _scalar_or_array((f(x) - f(x - h)) / h)


def central_difference(f, x, h=None):
    """First derivative of f at x by the central difference (error O(h^2)).

    The O(h) error terms of the forward and backward formulas have opposite
    signs and cancel in their average, which is the central formula.

    Parameters, returns and raises as for :func:`forward_difference`; the
    default step is ``eps**(1/3) * max(1, |x|)``.

    Example
    -------
    >>> bool(abs(central_difference(np.sin, 1.0) - np.cos(1.0)) < 1e-10)
    True
    """
    _check_function(f)
    x = _point(x)
    h = _step(x, h, CENTRAL_STEP_EXPONENT)
    return _scalar_or_array((f(x + h) - f(x - h)) / (2.0 * h))


def central_second_difference(f, x, h=None):
    """Second derivative of f at x by the central difference (error O(h^2)).

    Parameters, returns and raises as for :func:`forward_difference`; the
    default step is ``eps**(1/4) * max(1, |x|)``.

    Example
    -------
    >>> bool(abs(central_second_difference(np.sin, 1.0) + np.sin(1.0)) < 1e-7)
    True
    """
    _check_function(f)
    x = _point(x)
    h = _step(x, h, SECOND_STEP_EXPONENT)
    return _scalar_or_array((f(x + h) - 2.0 * f(x) + f(x - h)) / h**2)


# ---------------------------------------------------------------------------
# Derivatives of sampled arrays
# ---------------------------------------------------------------------------
def _samples(x, y, minimum):
    """Validate sample arrays; return (x, y, spacing h)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1:
        raise ValueError("x and y must be 1-D arrays.")
    if x.size != y.size:
        raise ValueError(f"x and y must have the same length, got {x.size} and {y.size}.")
    if x.size < minimum:
        raise ValueError(f"At least {minimum} samples are needed, got {x.size}.")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("x and y must not contain NaN or infinite values.")
    spacing = np.diff(x)
    h = spacing[0]
    if h <= 0:
        raise ValueError("x must be strictly increasing.")
    if not np.allclose(spacing, h, rtol=UNIFORM_SPACING_RTOL, atol=0.0):
        raise ValueError("x must be uniformly spaced (D33).")
    return x, y, h


def forward_difference_samples(x, y):
    """Forward differences of samples: (y[i+1] - y[i]) / h at x[0] .. x[n-2].

    Parameters
    ----------
    x : array_like
        Uniformly spaced, strictly increasing sample points (>= 2).
    y : array_like
        Sample values, same length, finite.

    Returns
    -------
    numpy.ndarray
        n - 1 derivative estimates, one for each of ``x[:-1]``.

    Raises
    ------
    ValueError
        For mismatched lengths, too few samples, non-finite values,
        non-increasing or non-uniform x.

    Example
    -------
    >>> forward_difference_samples([0, 1, 2], [0, 1, 4]).tolist()
    [1.0, 3.0]
    """
    x, y, h = _samples(x, y, 2)
    return (y[1:] - y[:-1]) / h


def backward_difference_samples(x, y):
    """Backward differences of samples: (y[i] - y[i-1]) / h at x[1] .. x[n-1].

    Parameters and raises as for :func:`forward_difference_samples`.

    Returns
    -------
    numpy.ndarray
        n - 1 derivative estimates, one for each of ``x[1:]``.

    Example
    -------
    >>> backward_difference_samples([0, 1, 2], [0, 1, 4]).tolist()
    [1.0, 3.0]
    """
    x, y, h = _samples(x, y, 2)
    return (y[1:] - y[:-1]) / h


def central_difference_samples(x, y):
    """First derivative at every sample, O(h^2) everywhere (D33).

    Interior points: (y[i+1] - y[i-1]) / (2h). End points: the second-order
    one-sided formulas (-3 y0 + 4 y1 - y2) / (2h) and
    (3 y[n-1] - 4 y[n-2] + y[n-3]) / (2h).

    Parameters
    ----------
    x : array_like
        Uniformly spaced, strictly increasing sample points (>= 3).
    y : array_like
        Sample values, same length, finite.

    Returns
    -------
    numpy.ndarray
        n derivative estimates, one per sample.

    Raises
    ------
    ValueError
        As for :func:`forward_difference_samples` (needs >= 3 samples).

    Example
    -------
    >>> central_difference_samples([0, 1, 2, 3], [0, 1, 4, 9]).tolist()
    [0.0, 2.0, 4.0, 6.0]
    """
    x, y, h = _samples(x, y, 3)
    derivative = np.empty_like(y)
    derivative[1:-1] = (y[2:] - y[:-2]) / (2.0 * h)
    derivative[0] = (-3.0 * y[0] + 4.0 * y[1] - y[2]) / (2.0 * h)
    derivative[-1] = (3.0 * y[-1] - 4.0 * y[-2] + y[-3]) / (2.0 * h)
    return derivative


def central_second_difference_samples(x, y):
    """Second derivative at every sample, O(h^2) everywhere (D33).

    Interior points: (y[i+1] - 2 y[i] + y[i-1]) / h^2. End points: the
    second-order one-sided formulas (2 y0 - 5 y1 + 4 y2 - y3) / h^2 and its
    mirror image at the right end.

    Parameters
    ----------
    x : array_like
        Uniformly spaced, strictly increasing sample points (>= 4).
    y : array_like
        Sample values, same length, finite.

    Returns
    -------
    numpy.ndarray
        n second-derivative estimates.

    Raises
    ------
    ValueError
        As for :func:`forward_difference_samples` (needs >= 4 samples).

    Example
    -------
    >>> central_second_difference_samples([0, 1, 2, 3], [0, 1, 4, 9]).tolist()
    [2.0, 2.0, 2.0, 2.0]
    """
    x, y, h = _samples(x, y, 4)
    second = np.empty_like(y)
    second[1:-1] = (y[2:] - 2.0 * y[1:-1] + y[:-2]) / h**2
    second[0] = (2.0 * y[0] - 5.0 * y[1] + 4.0 * y[2] - y[3]) / h**2
    second[-1] = (2.0 * y[-1] - 5.0 * y[-2] + 4.0 * y[-3] - y[-4]) / h**2
    return second
