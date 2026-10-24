"""From-scratch linear and polynomial least squares.

Problem: given an n x p matrix X (n observations, p parameters) and data y,
find beta minimising the residual sum of squares RSS = ||y - X beta||^2.

Two ways to solve it (DECISIONS.md D35)
---------------------------------------
1. **Normal equations** (the main method): setting the gradient of RSS to
   zero gives (X^T X) beta = X^T y, a p x p system solved with my
   Gaussian elimination (:mod:`tyredeg.numerics.linear_solvers`).
2. **QR** (for comparison): numpy's QR factorisation X = Q R (Q has
   orthonormal columns, R is p x p upper-triangular). Because Q^T Q = I,
   the problem becomes R beta = Q^T y, solved with my back substitution.

Why the normal equations square the condition number
----------------------------------------------------
Write X with its singular value decomposition X = U S V^T. Then
X^T X = V S^2 V^T, so the singular values of X^T X are the SQUARES of those
of X, and cond(X^T X) = sigma_max^2 / sigma_min^2 = cond(X)^2. Solving a
system loses about log10(cond) digits, so the normal equations lose twice as
many digits as necessary: cond(X) = 1e6 is harmless for QR (which works with
R, whose condition number equals cond(X)) but gives cond(X^T X) = 1e12 for
the normal equations. Reference: Golub & Van Loan, Matrix Computations,
4th ed., Section 5.3.

Polynomial inputs are therefore scaled to [-1, 1] by default
(``s = (x - centre) / half_range``): for tyre ages 1-41 laps this lowers
cond(X^T X) for a cubic from 1.5e10 to 61 (D35).

Uncertainty: with sigma^2 = RSS / (n - p), the covariance of beta is
sigma^2 (X^T X)^-1, whose diagonal gives the squared standard errors.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np

from tyredeg.numerics.linear_solvers import (
    DEFAULT_CONDITION_THRESHOLD,
    NearSingularWarning,
    back_substitution,
    condition_number_1norm,
    gaussian_elimination,
    lu_factor,
    lu_solve,
)

# Default; identical to `numerics.least_squares.scale_polynomial_inputs` (D38).
DEFAULT_SCALE_POLYNOMIAL_INPUTS = True

VALID_METHODS = ("normal", "qr")


@dataclass(frozen=True)
class LeastSquaresResult:
    """Result of a linear least-squares fit.

    Attributes
    ----------
    coefficients : numpy.ndarray
        Fitted beta, shape (p,).
    standard_errors : numpy.ndarray
        Standard error of each coefficient (NaN if n == p, no residual
        degrees of freedom).
    residual_sum_of_squares : float
        RSS = ||y - X beta||^2 (units of y squared).
    condition_estimate : float
        1-norm condition estimate of the matrix actually solved: X^T X for
        "normal", R for "qr".
    method : str
        ``"normal"`` or ``"qr"``.

    Example
    -------
    >>> result = fit_linear_least_squares([[1.0, 0.0], [1.0, 1.0], [1.0, 2.0]], [1.0, 3.1, 4.9])
    >>> result.coefficients.round(6).tolist(), round(result.residual_sum_of_squares, 6), result.method
    ([1.05, 1.95], 0.015, 'normal')
    """

    coefficients: np.ndarray
    standard_errors: np.ndarray
    residual_sum_of_squares: float
    condition_estimate: float
    method: str


def _check_xy(X, y):
    """Validate the design matrix and data; return float copies."""
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=float)
    if X.ndim != 2:
        raise ValueError(f"X must be a 2-D matrix, got shape {X.shape}.")
    if y.ndim != 1 or y.size != X.shape[0]:
        raise ValueError(f"y must be 1-D with {X.shape[0]} values, got shape {y.shape}.")
    n, p = X.shape
    if p == 0:
        raise ValueError("X must have at least one column.")
    if n < p:
        raise ValueError(f"Need at least as many observations as parameters (n={n} < p={p}).")
    if not (np.all(np.isfinite(X)) and np.all(np.isfinite(y))):
        raise ValueError("X and y must contain only finite numbers.")
    return X, y


def _standard_errors(inverse_xtx_diagonal, rss, n, p):
    """sqrt(diag(sigma^2 (X^T X)^-1)) with sigma^2 = RSS / (n - p)."""
    if n == p:
        return np.full(p, np.nan)
    sigma_squared = rss / (n - p)
    return np.sqrt(sigma_squared * inverse_xtx_diagonal)


def fit_linear_least_squares(X, y, condition_threshold=DEFAULT_CONDITION_THRESHOLD):
    """Least squares by the normal equations, solved with my Gaussian elimination.

    Parameters
    ----------
    X : array_like
        Design matrix, shape (n, p) with n >= p, finite.
    y : array_like
        Observations, shape (n,), finite.
    condition_threshold : float, optional
        Warn (NearSingularWarning) if cond(X^T X) exceeds this. Default 1e12.

    Returns
    -------
    LeastSquaresResult

    Raises
    ------
    ValueError
        For invalid shapes or non-finite values.
    SingularMatrixError
        If X^T X is singular (columns of X linearly dependent).

    Warns
    -----
    NearSingularWarning
        If X^T X is ill-conditioned.

    Example
    -------
    >>> X = [[1.0, 0.0], [1.0, 1.0], [1.0, 2.0]]
    >>> fit_linear_least_squares(X, [1.0, 3.0, 5.0]).coefficients.round(10).tolist()
    [1.0, 2.0]
    """
    X, y = _check_xy(X, y)
    n, p = X.shape
    xtx = X.T @ X
    xty = X.T @ y
    solution = gaussian_elimination(xtx, xty, condition_threshold)
    beta = solution.x
    rss = float(np.sum((y - X @ beta) ** 2))
    # (X^T X)^-1 from the same LU factors, for the standard errors.
    lu, permutation = lu_factor(xtx)
    inverse_diagonal = np.diag(lu_solve(lu, permutation, np.eye(p)))
    return LeastSquaresResult(
        coefficients=beta,
        standard_errors=_standard_errors(inverse_diagonal, rss, n, p),
        residual_sum_of_squares=rss,
        condition_estimate=solution.condition_estimate,
        method="normal",
    )


def fit_linear_least_squares_qr(X, y, condition_threshold=DEFAULT_CONDITION_THRESHOLD):
    """Least squares via numpy's QR factorisation and my back substitution.

    Used to compare against :func:`fit_linear_least_squares`; it avoids
    forming X^T X, so it works with cond(X) rather than cond(X)^2.

    Parameters
    ----------
    X : array_like
        Design matrix, shape (n, p) with n >= p, finite.
    y : array_like
        Observations, shape (n,), finite.
    condition_threshold : float, optional
        Warn (NearSingularWarning) if cond(R) exceeds this. Default 1e12.

    Returns
    -------
    LeastSquaresResult
        ``method == "qr"``; ``condition_estimate`` is that of R.

    Raises
    ------
    ValueError
        For invalid shapes or non-finite values.
    SingularMatrixError
        If R is singular to working precision (columns of X linearly dependent).

    Warns
    -----
    NearSingularWarning
        If R is ill-conditioned.

    Example
    -------
    >>> X = [[1.0, 0.0], [1.0, 1.0], [1.0, 2.0]]
    >>> fit_linear_least_squares_qr(X, [1.0, 3.0, 5.0]).coefficients.round(10).tolist()
    [1.0, 2.0]
    """
    X, y = _check_xy(X, y)
    n, p = X.shape
    q, r = np.linalg.qr(X, mode="reduced")
    beta = back_substitution(r, q.T @ y)
    rss = float(np.sum((y - X @ beta) ** 2))
    condition = condition_number_1norm(r)
    if condition > condition_threshold:
        warnings.warn(
            f"R is ill-conditioned (condition estimate {condition:.2e}).",
            NearSingularWarning,
            stacklevel=2,
        )
    # (X^T X)^-1 = (R^T R)^-1 = R^-1 R^-T; R^-1 by back substitution on I.
    r_inverse = back_substitution(r, np.eye(p))
    inverse_diagonal = np.sum(r_inverse**2, axis=1)
    return LeastSquaresResult(
        coefficients=beta,
        standard_errors=_standard_errors(inverse_diagonal, rss, n, p),
        residual_sum_of_squares=rss,
        condition_estimate=condition,
        method="qr",
    )


# ---------------------------------------------------------------------------
# Polynomial fits
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PolynomialFit:
    """A fitted polynomial ``y = sum_k coefficients[k] * s**k``, ``s = (x - centre) / half_range``.

    Attributes
    ----------
    coefficients : numpy.ndarray
        Coefficients in increasing powers of the scaled variable s.
    standard_errors : numpy.ndarray
        Standard error of each coefficient (same basis).
    centre, half_range : float
        Input scaling (0 and 1 when scaling is off).
    degree : int
    result : LeastSquaresResult
        The underlying least-squares result.

    Example
    -------
    >>> fit = fit_polynomial([0, 1, 2, 3], [1.0, 2.0, 5.0, 10.0], 2)
    >>> fit.degree, fit.centre, fit.half_range
    (2, 1.5, 1.5)
    >>> (fit.unscaled_coefficients().round(10) + 0.0).tolist()   # + 0.0 turns -0.0 into 0.0
    [1.0, 0.0, 1.0]
    """

    coefficients: np.ndarray
    standard_errors: np.ndarray
    centre: float
    half_range: float
    degree: int
    result: LeastSquaresResult

    def predict(self, x):
        """Evaluate the polynomial at x (original units).

        Parameters
        ----------
        x : float or array_like
            Point(s) in the original units of the fitted x, finite.

        Returns
        -------
        numpy.ndarray
            Fitted values, shape (n,).

        Raises
        ------
        ValueError
            If ``x`` contains NaN or infinite values.

        Example
        -------
        >>> fit_polynomial([0, 1, 2], [1.0, 3.0, 5.0], 1).predict([3.0]).round(10).tolist()
        [7.0]
        """
        x = np.asarray(x, dtype=float)
        if not np.all(np.isfinite(x)):
            raise ValueError("x must not contain NaN or infinite values.")
        return polynomial_design_matrix(x.reshape(-1), self.degree, self.centre,
                                        self.half_range) @ self.coefficients

    def unscaled_coefficients(self):
        """Coefficients in increasing powers of the ORIGINAL variable x.

        Expands ((x - c) / r)^k with the binomial theorem:
        (x - c)^k = sum_j C(k, j) x^j (-c)^(k - j).

        Returns
        -------
        numpy.ndarray
            Coefficients a_0 .. a_degree of 1, x, ..., x^degree.

        Raises
        ------
        Nothing: the scaling was validated when the fit was made.

        Example
        -------
        >>> fit = fit_polynomial([1, 2, 3, 4], [3.0, 5.0, 7.0, 9.0], 1)
        >>> fit.unscaled_coefficients().round(10).tolist()
        [1.0, 2.0]
        """
        return unscaling_matrix(self.degree, self.centre, self.half_range) @ self.coefficients


def unscaling_matrix(degree, centre, half_range):
    """Matrix T with (unscaled coefficients) = T @ (scaled coefficients).

    The polynomial sum_k b_k s^k with s = (x - c) / r equals sum_j a_j x^j.
    Expanding ((x - c) / r)^k with the binomial theorem,
    (x - c)^k = sum_j C(k, j) x^j (-c)^(k - j), gives
    T[j, k] = C(k, j) (-c)^(k - j) / r^k for j <= k (0 otherwise).
    Because the map is linear, a covariance matrix converts as T C T^T.

    Parameters
    ----------
    degree : int
        Polynomial degree >= 0.
    centre, half_range : float
        The scaling used (half_range > 0).

    Returns
    -------
    numpy.ndarray
        Shape (degree + 1, degree + 1), upper-triangular.

    Raises
    ------
    ValueError
        If ``degree`` < 0 or ``half_range`` <= 0.

    Example
    -------
    >>> unscaling_matrix(1, centre=2.0, half_range=0.5).tolist()
    [[1.0, -4.0], [0.0, 2.0]]
    """
    if isinstance(degree, bool) or not isinstance(degree, (int, np.integer)) or degree < 0:
        raise ValueError(f"degree must be an integer >= 0, got {degree!r}.")
    if not half_range > 0:
        raise ValueError(f"half_range must be > 0, got {half_range}.")
    matrix = np.zeros((degree + 1, degree + 1))
    for k in range(degree + 1):
        for j in range(k + 1):
            matrix[j, k] = math.comb(k, j) * (-centre) ** (k - j) / half_range**k
    return matrix


def polynomial_design_matrix(x, degree, centre=0.0, half_range=1.0):
    """Columns 1, s, s^2, ..., s^degree with s = (x - centre) / half_range.

    Parameters
    ----------
    x : array_like
        1-D input values (e.g. tyre age [laps]).
    degree : int
        Polynomial degree >= 0.
    centre, half_range : float, optional
        Scaling; ``half_range > 0``.

    Returns
    -------
    numpy.ndarray
        Shape (len(x), degree + 1).

    Raises
    ------
    ValueError
        For non-1-D x, a negative degree or half_range <= 0.

    Example
    -------
    >>> polynomial_design_matrix([1.0, 2.0], 2).tolist()
    [[1.0, 1.0, 1.0], [1.0, 2.0, 4.0]]
    """
    x = np.asarray(x, dtype=float)
    if x.ndim != 1:
        raise ValueError("x must be 1-D.")
    if isinstance(degree, bool) or not isinstance(degree, (int, np.integer)) or degree < 0:
        raise ValueError(f"degree must be an integer >= 0, got {degree!r}.")
    if not half_range > 0:
        raise ValueError(f"half_range must be > 0, got {half_range}.")
    s = (x - centre) / half_range
    columns = [np.ones_like(s)]
    for _ in range(degree):
        columns.append(columns[-1] * s)
    return np.column_stack(columns)


def fit_polynomial(x, y, degree, scale=DEFAULT_SCALE_POLYNOMIAL_INPUTS, method="normal",
                   condition_threshold=DEFAULT_CONDITION_THRESHOLD):
    """Fit a polynomial of the given degree by least squares.

    Parameters
    ----------
    x : array_like
        1-D inputs (e.g. tyre age [laps]), finite.
    y : array_like
        1-D observations (e.g. lap time [s]), same length.
    degree : int
        Degree >= 0; needs at least ``degree + 1`` distinct x values.
    scale : bool, optional
        Map x to [-1, 1] first (D35). Default True.
    method : str, optional
        ``"normal"`` (default, my Gaussian elimination) or ``"qr"``.
    condition_threshold : float, optional
        Near-singular warning threshold. Default 1e12.

    Returns
    -------
    PolynomialFit

    Raises
    ------
    ValueError
        For invalid inputs, an unknown method, too few points, or all x equal
        while scaling a polynomial of degree >= 1.
    SingularMatrixError
        If the columns are linearly dependent.

    Example
    -------
    >>> fit = fit_polynomial([0, 1, 2, 3], [1.0, 2.0, 5.0, 10.0], 2)
    >>> (fit.unscaled_coefficients().round(10) + 0.0).tolist()  # + 0.0 turns -0.0 into 0.0
    [1.0, 0.0, 1.0]
    """
    if method not in VALID_METHODS:
        raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}.")
    if not isinstance(scale, bool):
        raise TypeError("scale must be True or False.")
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or not np.all(np.isfinite(x)):
        raise ValueError("x must be a 1-D array of finite numbers.")
    if isinstance(degree, bool) or not isinstance(degree, (int, np.integer)) or degree < 0:
        raise ValueError(f"degree must be an integer >= 0, got {degree!r}.")
    if np.unique(x).size < degree + 1:
        raise ValueError(f"A degree-{degree} polynomial needs at least {degree + 1} distinct x values.")

    centre, half_range = 0.0, 1.0
    if scale and x.size > 0:
        low, high = float(np.min(x)), float(np.max(x))
        centre = (low + high) / 2.0
        if high > low:
            half_range = (high - low) / 2.0
    X = polynomial_design_matrix(x, degree, centre, half_range)
    if method == "normal":
        result = fit_linear_least_squares(X, y, condition_threshold)
    else:
        result = fit_linear_least_squares_qr(X, y, condition_threshold)
    return PolynomialFit(
        coefficients=result.coefficients,
        standard_errors=result.standard_errors,
        centre=centre,
        half_range=half_range,
        degree=int(degree),
        result=result,
    )
