"""Verification tests for Gaussian elimination with partial pivoting."""

import warnings
from pathlib import Path

import numpy as np
import pytest

from tyredeg.config import load_config
from tyredeg.numerics.linear_solvers import (
    NearSingularWarning,
    SingularMatrixError,
    back_substitution,
    condition_number_1norm,
    forward_substitution,
    gaussian_elimination,
    lu_factor,
    lu_solve,
)

VERIFY = load_config(Path(__file__).resolve().parents[1] / "config.yaml").verification


def hilbert(n):
    """Hilbert matrix H_ij = 1 / (i + j + 1): a classic ill-conditioned matrix."""
    i, j = np.indices((n, n))
    return 1.0 / (i + j + 1.0)


@pytest.mark.parametrize("n", [1, 2, 5, 10])
def test_matches_numpy_solve_on_random_systems(n):
    rng = np.random.default_rng(42)  # seed recorded (rule 11)
    A = rng.normal(size=(n, n)) + n * np.eye(n)
    b = rng.normal(size=n)
    x = gaussian_elimination(A, b).x
    np.testing.assert_allclose(x, np.linalg.solve(A, b), rtol=VERIFY.linear_solver_rtol, atol=1e-14)


def test_zero_pivot_requires_a_row_swap():
    # Without pivoting the first step would divide by A[0, 0] = 0.
    A = np.array([[0.0, 2.0, 1.0], [1.0, 1.0, 1.0], [2.0, 1.0, 0.0]])
    b = np.array([3.0, 3.0, 3.0])
    lu, permutation = lu_factor(A)
    assert permutation[0] == 2  # largest |entry| of column 0 is in row 2
    np.testing.assert_allclose(gaussian_elimination(A, b).x, np.linalg.solve(A, b),
                               rtol=VERIFY.linear_solver_rtol)


def test_tiny_pivot_is_handled_accurately():
    # Classic example: without pivoting, 1 - 1e20 swamps the 1 and x1 comes out 0.
    A = np.array([[1e-20, 1.0], [1.0, 1.0]])
    b = np.array([1.0, 2.0])
    np.testing.assert_allclose(gaussian_elimination(A, b).x, [1.0, 1.0], rtol=1e-12)


def test_lu_factors_reconstruct_permuted_matrix():
    rng = np.random.default_rng(42)
    A = rng.normal(size=(6, 6))
    lu, permutation = lu_factor(A)
    L = np.tril(lu, -1) + np.eye(6)
    U = np.triu(lu)
    np.testing.assert_allclose(L @ U, A[permutation], atol=1e-12)
    # Partial pivoting keeps every multiplier at most 1 in size.
    assert np.max(np.abs(np.tril(lu, -1))) <= 1.0


def test_multiple_right_hand_sides():
    rng = np.random.default_rng(42)
    A = rng.normal(size=(4, 4)) + 4 * np.eye(4)
    B = rng.normal(size=(4, 3))
    lu, permutation = lu_factor(A)
    np.testing.assert_allclose(lu_solve(lu, permutation, B), np.linalg.solve(A, B), rtol=1e-12)


def test_input_matrix_is_not_modified():
    A = np.array([[0.0, 1.0], [2.0, 3.0]])
    copy = A.copy()
    gaussian_elimination(A, [1.0, 5.0])
    np.testing.assert_array_equal(A, copy)


def test_triangular_solves():
    L = np.array([[2.0, 0.0, 0.0], [1.0, 1.0, 0.0], [3.0, -1.0, 4.0]])
    b = np.array([2.0, 3.0, 10.0])
    np.testing.assert_allclose(forward_substitution(L, b), np.linalg.solve(L, b))
    U = L.T
    np.testing.assert_allclose(back_substitution(U, b), np.linalg.solve(U, b))
    with pytest.raises(ValueError, match="Zero diagonal"):
        back_substitution([[0.0, 1.0], [0.0, 1.0]], [1.0, 1.0])


# ---------------------------------------------------------------------------
# Condition number, singular and near-singular matrices (D34)
# ---------------------------------------------------------------------------
def test_condition_estimate_matches_numpy_1norm():
    rng = np.random.default_rng(42)
    A = rng.normal(size=(5, 5))
    assert condition_number_1norm(A) == pytest.approx(np.linalg.cond(A, 1), rel=1e-10)


def test_well_conditioned_matrix_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", NearSingularWarning)
        result = gaussian_elimination(np.eye(3) * 2.0, [1.0, 1.0, 1.0])
    assert result.condition_estimate == pytest.approx(1.0)


def test_hilbert_matrix_triggers_near_singular_warning():
    H = hilbert(10)  # 1-norm condition number ~3.5e13 > 1e12
    with pytest.warns(NearSingularWarning, match="condition estimate"):
        result = gaussian_elimination(H, H @ np.ones(10))
    assert result.condition_estimate == pytest.approx(np.linalg.cond(H, 1), rel=1e-2)


def test_hilbert_below_threshold_does_not_warn():
    H = hilbert(6)  # condition number ~2.9e7
    with warnings.catch_warnings():
        warnings.simplefilter("error", NearSingularWarning)
        gaussian_elimination(H, H @ np.ones(6))


def test_custom_threshold():
    H = hilbert(6)
    with pytest.warns(NearSingularWarning):
        gaussian_elimination(H, H @ np.ones(6), condition_threshold=1e6)


@pytest.mark.parametrize(
    "A",
    [
        [[1.0, 2.0], [2.0, 4.0]],                  # second row = 2 x first row
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],  # rank 2 (rounding makes pivot ~1e-16)
        [[0.0, 0.0], [0.0, 0.0]],
    ],
)
def test_singular_matrices_raise(A):
    with pytest.raises(SingularMatrixError):
        gaussian_elimination(A, np.ones(len(A)))


@pytest.mark.parametrize(
    "A, b",
    [
        ([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], [1.0, 2.0]),   # not square
        ([[1.0, 2.0], [3.0, 4.0]], [1.0, 2.0, 3.0]),         # wrong b length
        ([[1.0, np.nan], [3.0, 4.0]], [1.0, 2.0]),           # NaN
        ([[1.0, 2.0], [3.0, 4.0]], [1.0, np.inf]),
        ([], []),
    ],
)
def test_invalid_inputs(A, b):
    with pytest.raises(ValueError):
        gaussian_elimination(A, b)


def test_invalid_threshold():
    with pytest.raises(ValueError):
        gaussian_elimination(np.eye(2), [1.0, 1.0], condition_threshold=0.5)
