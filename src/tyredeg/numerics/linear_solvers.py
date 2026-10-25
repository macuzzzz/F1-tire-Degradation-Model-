"""From-scratch Gaussian elimination with partial pivoting.

Gaussian elimination turns A x = b into an upper-triangular system by
subtracting multiples of one row from the rows below it. Storing those
multipliers gives the factorisation P A = L U (L lower-triangular with unit
diagonal, U upper-triangular, P a row permutation), after which any right-hand
side is solved by forward substitution (L z = P b) and back substitution
(U x = z).

Partial pivoting
----------------
Before eliminating column k, the row with the largest |entry| in that
column (at or below row k) is swapped into the pivot position. Without this,
a zero pivot stops the method and a tiny pivot creates huge multipliers that
amplify round-off error.

Singular and near-singular matrices (DECISIONS.md D34)
------------------------------------------------------
- A pivot with |pivot| <= n * eps * max|A| is treated as zero: the matrix is
  numerically singular and :class:`SingularMatrixError` is raised.
- Otherwise the 1-norm condition number kappa_1 = ||A||_1 * ||A^-1||_1 is
  estimated (A^-1 from the LU factors, n extra solves). The relative error of
  x can be as large as about kappa * eps, so if kappa exceeds the threshold
  (default 1e12, i.e. only ~4 trustworthy digits) a
  :class:`NearSingularWarning` is issued. Reference: Higham, Accuracy and
  Stability of Numerical Algorithms, 2nd ed. (2002).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

# Default; identical to `numerics.linear.condition_warning_threshold` (D38).
DEFAULT_CONDITION_THRESHOLD = 1.0e12

# Machine epsilon, used to decide when a pivot is numerically zero.
EPS = np.finfo(float).eps


class SingularMatrixError(ValueError):
    """The matrix is (numerically) singular: a pivot is effectively zero.

    Example
    -------
    >>> gaussian_elimination([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])
    Traceback (most recent call last):
    ...
    tyredeg.numerics.linear_solvers.SingularMatrixError: A is singular to working precision (pivot 0.000e+00 in column 1).
    """


class NearSingularWarning(UserWarning):
    """The matrix is invertible but so ill-conditioned that x is unreliable.

    Example
    -------
    >>> issubclass(NearSingularWarning, UserWarning)
    True
    """


@dataclass(frozen=True)
class LinearSolveResult:
    """Result of :func:`gaussian_elimination`.

    Attributes
    ----------
    x : numpy.ndarray
        Solution of A x = b (same shape as b).
    condition_estimate : float
        1-norm condition number estimate ||A||_1 * ||A^-1||_1.

    Example
    -------
    >>> result = gaussian_elimination([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0])
    >>> result.x.round(12).tolist(), round(result.condition_estimate, 6)
    ([0.8, 1.4], 3.2)
    """

    x: np.ndarray
    condition_estimate: float


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------
def _square_matrix(A):
    A = np.array(A, dtype=float)  # a copy, so the caller's matrix is untouched
    # Must be a non-empty square matrix of finite numbers.
    if A.ndim != 2 or A.shape[0] != A.shape[1] or A.shape[0] == 0:
        raise ValueError(f"A must be a non-empty square matrix, got shape {A.shape}.")
    if not np.all(np.isfinite(A)):
        raise ValueError("A must contain only finite numbers.")
    return A


def _right_hand_side(b, n):
    # b may be one vector or several columns (one solve per column), with n rows.
    b = np.array(b, dtype=float)
    if b.ndim not in (1, 2) or b.shape[0] != n:
        raise ValueError(f"b must have {n} rows, got shape {b.shape}.")
    if not np.all(np.isfinite(b)):
        raise ValueError("b must contain only finite numbers.")
    return b


# ---------------------------------------------------------------------------
# Triangular solves
# ---------------------------------------------------------------------------
def forward_substitution(L, b, unit_diagonal=False):
    """Solve L z = b for lower-triangular L, from the first row down.

    Parameters
    ----------
    L : array_like
        n x n lower-triangular matrix (entries above the diagonal ignored).
    b : array_like
        Right-hand side, shape (n,) or (n, m).
    unit_diagonal : bool, optional
        If True, the diagonal of L is taken as 1 (as in the L of P A = L U).

    Returns
    -------
    numpy.ndarray
        z, same shape as b.

    Raises
    ------
    ValueError
        For incompatible shapes, non-finite values or a zero diagonal entry.

    Example
    -------
    >>> forward_substitution([[2.0, 0.0], [1.0, 1.0]], [4.0, 3.0]).tolist()
    [2.0, 1.0]
    """
    # Solve L z = b from the top row down: each row adds one new unknown.
    L = _square_matrix(L)
    b = _right_hand_side(b, L.shape[0])
    # Result has the same shape as b (also works for several right-hand sides).
    n = L.shape[0]
    z = np.zeros_like(b)
    for i in range(n):
        # Everything already known (z_0 .. z_{i-1}) is moved to the right side.
        known = L[i, :i] @ z[:i]
        if unit_diagonal:
            # Unit lower triangle (from LU): the diagonal is 1 by construction, so no division.
            z[i] = b[i] - known
        else:
            # A zero on the diagonal means this row cannot be solved.
            if L[i, i] == 0:
                raise ValueError(f"Zero diagonal entry in row {i}.")
            z[i] = (b[i] - known) / L[i, i]
    return z


def back_substitution(U, b):
    """Solve U x = b for upper-triangular U, from the last row up.

    Parameters
    ----------
    U : array_like
        n x n upper-triangular matrix (entries below the diagonal ignored).
    b : array_like
        Right-hand side, shape (n,) or (n, m).

    Returns
    -------
    numpy.ndarray
        x, same shape as b.

    Raises
    ------
    ValueError
        For incompatible shapes, non-finite values or a zero diagonal entry.

    Example
    -------
    >>> back_substitution([[2.0, 1.0], [0.0, 4.0]], [5.0, 8.0]).tolist()
    [1.5, 2.0]
    """
    # Solve U x = b from the bottom row up: each row adds one new unknown.
    U = _square_matrix(U)
    b = _right_hand_side(b, U.shape[0])
    n = U.shape[0]
    x = np.zeros_like(b)
    for i in range(n - 1, -1, -1):
        # A zero on the diagonal means this row cannot be solved.
        if U[i, i] == 0:
            raise ValueError(f"Zero diagonal entry in row {i}.")
        # Subtract the already known unknowns, then divide by the diagonal entry.
        known = U[i, i + 1:] @ x[i + 1:]
        x[i] = (b[i] - known) / U[i, i]
    return x


# ---------------------------------------------------------------------------
# LU factorisation with partial pivoting
# ---------------------------------------------------------------------------
def lu_factor(A):
    """Factorise P A = L U by Gaussian elimination with partial pivoting.

    Parameters
    ----------
    A : array_like
        n x n matrix with finite entries.

    Returns
    -------
    lu : numpy.ndarray
        n x n array holding U on and above the diagonal and the multipliers
        of L (unit diagonal not stored) below it.
    permutation : numpy.ndarray of int
        Row order: row i of P A is row ``permutation[i]`` of A.

    Raises
    ------
    ValueError
        If A is not a finite square matrix.
    SingularMatrixError
        If a pivot satisfies |pivot| <= n * eps * max|A| (or A is all zeros).

    Example
    -------
    >>> lu, perm = lu_factor([[0.0, 1.0], [2.0, 3.0]])
    >>> perm.tolist()   # the zero pivot forced a row swap
    [1, 0]
    """
    # Work on a copy of A that will hold L (below the diagonal) and U (on and above it).
    lu = _square_matrix(A)
    n = lu.shape[0]
    # Track the row swaps so the right-hand side can be reordered the same way later.
    permutation = np.arange(n)
    # Scale-aware "zero": a pivot this small relative to A is round-off noise.
    # Pivots smaller than this are round-off noise relative to the size of A.
    pivot_tolerance = n * EPS * np.max(np.abs(lu))
    if pivot_tolerance == 0:
        raise SingularMatrixError("A is the zero matrix.")

    # Eliminate one column at a time.
    for k in range(n):
        # Partial pivoting: bring the largest |entry| of column k into row k.
        pivot_row = k + int(np.argmax(np.abs(lu[k:, k])))
        if abs(lu[pivot_row, k]) <= pivot_tolerance:
            raise SingularMatrixError(
                f"A is singular to working precision (pivot {lu[pivot_row, k]:.3e} in column {k})."
            )
        # Swap the pivot row into place, in the matrix and in the permutation.
        if pivot_row != k:
            lu[[k, pivot_row]] = lu[[pivot_row, k]]
            permutation[[k, pivot_row]] = permutation[[pivot_row, k]]
        # Eliminate the entries below the pivot; keep the multipliers in place.
        # Multipliers that zero the entries below the pivot; stored in place as the L part.
        multipliers = lu[k + 1:, k] / lu[k, k]
        lu[k + 1:, k] = multipliers
        # Subtract multiplier x pivot row from every row below (the elimination step).
        lu[k + 1:, k + 1:] -= np.outer(multipliers, lu[k, k + 1:])
    return lu, permutation


def lu_solve(lu, permutation, b):
    """Solve A x = b using the factors from :func:`lu_factor`.

    Parameters
    ----------
    lu, permutation
        Output of :func:`lu_factor`.
    b : array_like
        Right-hand side, shape (n,) or (n, m).

    Returns
    -------
    numpy.ndarray
        x, same shape as b.

    Raises
    ------
    ValueError
        For incompatible shapes or non-finite values.

    Example
    -------
    >>> lu, perm = lu_factor([[0.0, 1.0], [2.0, 3.0]])
    >>> lu_solve(lu, perm, [1.0, 5.0]).tolist()
    [1.0, 1.0]
    """
    # Reorder b like the rows of A, then solve L z = P b and U x = z.
    b = _right_hand_side(b, lu.shape[0])
    z = forward_substitution(lu, b[permutation], unit_diagonal=True)
    return back_substitution(lu, z)


def condition_number_1norm(A, lu=None, permutation=None):
    """Estimate kappa_1(A) = ||A||_1 * ||A^-1||_1 using my own LU solves.

    ||M||_1 is the largest column sum of |M|. A^-1 is computed column by
    column by solving A x = e_j (n solves); this is affordable for the small
    systems in this project (n <= ~10).

    Parameters
    ----------
    A : array_like
        n x n matrix.
    lu, permutation : optional
        Factors from :func:`lu_factor`, to avoid factorising A again.

    Returns
    -------
    float
        Condition number estimate (>= 1).

    Raises
    ------
    ValueError, SingularMatrixError
        As for :func:`lu_factor`.

    Example
    -------
    >>> condition_number_1norm([[2.0, 0.0], [0.0, 0.5]])
    4.0
    """
    # Factorise A unless the caller already has its LU factors.
    A = _square_matrix(A)
    if lu is None or permutation is None:
        lu, permutation = lu_factor(A)
    # Inverse of A, column by column, from the LU factors.
    inverse = lu_solve(lu, permutation, np.eye(A.shape[0]))
    # 1-norm = largest absolute column sum; cond_1 = ||A||_1 * ||A^-1||_1.
    norm_a = np.max(np.sum(np.abs(A), axis=0))
    norm_inverse = np.max(np.sum(np.abs(inverse), axis=0))
    return float(norm_a * norm_inverse)


def gaussian_elimination(A, b, condition_threshold=DEFAULT_CONDITION_THRESHOLD):
    """Solve A x = b by Gaussian elimination with partial pivoting.

    Parameters
    ----------
    A : array_like
        n x n matrix with finite entries.
    b : array_like
        Right-hand side, shape (n,) or (n, m).
    condition_threshold : float, optional
        Issue a :class:`NearSingularWarning` if the condition estimate exceeds
        this (> 1). Default 1e12 (D34).

    Returns
    -------
    LinearSolveResult
        ``x`` and the 1-norm ``condition_estimate``.

    Raises
    ------
    ValueError
        For invalid shapes, non-finite entries or threshold <= 1.
    SingularMatrixError
        If A is numerically singular.

    Warns
    -----
    NearSingularWarning
        If the condition estimate exceeds ``condition_threshold``.

    Example
    -------
    >>> result = gaussian_elimination([[0.0, 1.0], [2.0, 3.0]], [1.0, 5.0])
    >>> result.x.tolist()
    [1.0, 1.0]
    """
    # The threshold must be a finite number above 1 (cond >= 1 always).
    if not np.isfinite(condition_threshold) or condition_threshold <= 1:
        raise ValueError(f"condition_threshold must be > 1, got {condition_threshold}.")
    # Factorise once, solve, and estimate the condition number from the same factors.
    A = _square_matrix(A)
    lu, permutation = lu_factor(A)
    x = lu_solve(lu, permutation, b)
    condition = condition_number_1norm(A, lu, permutation)
    # Warn (but still return x) when A is so ill-conditioned that x has few correct digits.
    if condition > condition_threshold:
        warnings.warn(
            f"Matrix is ill-conditioned (1-norm condition estimate {condition:.2e} > "
            f"{condition_threshold:.0e}); expect only about "
            f"{max(0.0, -np.log10(condition * EPS)):.0f} correct digits.",
            NearSingularWarning,
            stacklevel=2,
        )
    return LinearSolveResult(x=x, condition_estimate=condition)
