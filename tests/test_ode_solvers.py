"""Verification tests for the from-scratch ODE solvers (Euler, Heun, RK4, RK45).

Acceptance tolerances come from the `verification` section of config.yaml (D37).
"""

from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.integrate._ivp.rk import RK45 as ScipyRK45

from tyredeg.config import load_config
from tyredeg.numerics import ode_solvers
from tyredeg.numerics.ode_solvers import RK45Stats, euler, heun, rk4, rk45

VERIFY = load_config(Path(__file__).resolve().parents[1] / "config.yaml").verification

# Test problem 1: exponential decay, y(t) = exp(-t).
def decay(t, y):
    return -y


# Test problem 2: the wear model dd/dn = a + b d, d(0) = 0 (Phase 4), over a
# 40-lap stint; exact solution d(n) = (a / b) (exp(b n) - 1).
A, B = 0.05, 0.03


def wear(t, d):
    # Tyre-wear ODE dd/dn = a + b*d, the model used in the project.
    return A + B * d


def wear_exact(n):
    # Its closed-form solution with d(0) = 0, used as the exact reference.
    return A / B * (np.exp(B * n) - 1.0)


# Test problem 3 (vector): harmonic oscillator y'' = -y as [position, velocity].
def oscillator(t, y):
    return np.array([y[1], -y[0]])


PROBLEMS = {
    "decay": (decay, 1.0, 2.0, np.exp(-2.0)),
    "wear": (wear, 0.0, 40.0, wear_exact(40.0)),
}
FIXED_STEP = {"euler": (euler, 1), "heun": (heun, 2), "rk4": (rk4, 4)}


def observed_order(solver, f, y0, t_end, exact):
    """Slope of log(error) vs log(h) for h = T/40, T/80, T/160, T/320 (D37)."""
    steps = t_end / np.array([40, 80, 160, 320])
    errors = [abs(solver(f, (0.0, t_end), y0, h)[1][-1] - exact) for h in steps]
    slope, _ = np.polyfit(np.log(steps), np.log(errors), 1)
    return slope


# ---------------------------------------------------------------------------
# Order of convergence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("problem", PROBLEMS)
@pytest.mark.parametrize("method", FIXED_STEP)
def test_observed_order_matches_theory(method, problem):
    # On every test problem the observed order must match the theory (1, 2 or 4).
    solver, theoretical = FIXED_STEP[method]
    f, y0, t_end, exact = PROBLEMS[problem]
    order = observed_order(solver, f, y0, t_end, exact)
    assert abs(order - theoretical) <= VERIFY.ode_order_tolerance, order


@pytest.mark.parametrize("method", FIXED_STEP)
def test_observed_order_for_a_vector_problem(method):
    # The same order check on a 2-component system (harmonic oscillator).
    solver, theoretical = FIXED_STEP[method]
    t_end = 2.0
    steps = t_end / np.array([40, 80, 160, 320])
    errors = []
    for h in steps:
        _, y, _ = solver(oscillator, (0.0, t_end), [1.0, 0.0], h)
        errors.append(np.max(np.abs(y[-1] - [np.cos(t_end), -np.sin(t_end)])))
    slope, _ = np.polyfit(np.log(steps), np.log(errors), 1)
    assert abs(slope - theoretical) <= VERIFY.ode_order_tolerance


# ---------------------------------------------------------------------------
# Accuracy at the optimal step found by scripts/numerics_study.py (N3 request)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method, n_steps, max_error",
    [
        # The study's smallest-error step for each method on the 40-lap wear
        # ODE (reports/phase3_ode_fixed_step.csv): RK4 reaches round-off level
        # at h = 40/4096; Euler and Heun keep improving down to h = 40/65536.
        ("rk4", 4096, 1e-13),
        ("heun", 65536, 1e-9),
        ("euler", 65536, 1e-4),
    ],
)
def test_error_at_study_optimal_step(method, n_steps, max_error):
    # At the step count chosen in the numerics study each method meets its error target.
    solver, _ = FIXED_STEP[method]
    _, d, _ = solver(wear, (0.0, 40.0), 0.0, 40.0 / n_steps)
    assert abs(d[-1] - wear_exact(40.0)) < max_error


def test_rk4_meets_1ms_with_one_lap_steps():
    # One step per lap is the natural choice for lap data; the study shows RK4
    # stays far below the 1 ms timing resolution even with 10-lap steps.
    _, d, _ = rk4(wear, (0.0, 40.0), 0.0, 1.0)
    assert np.max(np.abs(d - wear_exact(np.arange(41.0)))) < 1e-6


# ---------------------------------------------------------------------------
# Function-evaluation counts, grid and output shape
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method, per_step", [("euler", 1), ("heun", 2), ("rk4", 4)])
def test_function_evaluation_counts(method, per_step):
    # Cost check: f-evaluations = steps x stages per step (1, 2 or 4).
    solver, _ = FIXED_STEP[method]
    _, _, nfev = solver(decay, (0.0, 1.0), 1.0, 0.1)
    assert nfev == 10 * per_step


def test_last_step_is_shortened_to_hit_t_end():
    t, y, nfev = euler(decay, (0.0, 1.0), 1.0, 0.3)
    np.testing.assert_allclose(t, [0.0, 0.3, 0.6, 0.9, 1.0])
    assert t[-1] == 1.0
    # Last step has length 0.1: y = 0.7^3 * (1 - 0.1).
    assert y[-1] == pytest.approx(0.7**3 * 0.9)
    assert nfev == 4


def test_rounding_in_step_count_does_not_create_tiny_step():
    t, _, _ = euler(decay, (0.0, 2.0), 1.0, 0.1)  # 2.0 / 0.1 = 19.999999999999996
    assert len(t) == 21
    assert np.all(np.diff(t) > 0.09)


def test_scalar_and_vector_output_shapes():
    # A scalar problem gives a 1-D result, a vector problem one column per component.
    _, y_scalar, _ = rk4(decay, (0.0, 1.0), 1.0, 0.5)
    _, y_vector, _ = rk4(oscillator, (0.0, 1.0), [1.0, 0.0], 0.5)
    assert y_scalar.shape == (3,)
    assert y_vector.shape == (3, 2)


def test_scalar_problem_receives_a_float():
    # A scalar problem passes a plain float to f, not a 1-element array.
    received = []

    def f(t, y):
        # Record the type of y that the solver passes in.
        received.append(type(y))
        return -y

    euler(f, (0.0, 1.0), 1.0, 0.5)
    assert received == [float, float]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "f, t_span, y0, h, error",
    [
        ("not callable", (0.0, 1.0), 1.0, 0.1, TypeError),
        (decay, 1.0, 1.0, 0.1, TypeError),
        (decay, (1.0, 0.0), 1.0, 0.1, ValueError),
        (decay, (0.0, np.inf), 1.0, 0.1, ValueError),
        (decay, (0.0, 1.0), np.nan, 0.1, ValueError),
        (decay, (0.0, 1.0), [], 0.1, ValueError),
        (decay, (0.0, 1.0), [[1.0]], 0.1, ValueError),
        (decay, (0.0, 1.0), 1.0, 0.0, ValueError),
        (decay, (0.0, 1.0), 1.0, -0.1, ValueError),
        (decay, (0.0, 1.0), 1.0, 2.0, ValueError),
        (decay, (0.0, 1.0), 1.0, "0.1", TypeError),
    ],
)
@pytest.mark.parametrize("solver", [euler, heun, rk4])
def test_fixed_step_input_validation(solver, f, t_span, y0, h, error):
    # Invalid functions, intervals, initial values and step sizes are rejected.
    with pytest.raises(error):
        solver(f, t_span, y0, h)


def test_wrong_size_or_nonfinite_slope_is_rejected():
    # f must return the right number of finite values.
    with pytest.raises(ValueError, match="values"):
        rk4(lambda t, y: np.array([1.0, 2.0]), (0.0, 1.0), 1.0, 0.5)
    with pytest.raises(ValueError, match="non-finite"):
        rk4(lambda t, y: np.inf, (0.0, 1.0), 1.0, 0.5)


# ---------------------------------------------------------------------------
# RK45 (Dormand-Prince)
# ---------------------------------------------------------------------------
def test_dormand_prince_coefficients_match_scipy():
    # SciPy's RK45 implements the same pair; its tableau is an independent copy.
    np.testing.assert_allclose(ode_solvers.DP_C[:6], ScipyRK45.C, rtol=0, atol=1e-15)
    # SciPy stores only the 6 x 5 block that is used (stage 6 needs k1..k5).
    np.testing.assert_allclose(ode_solvers.DP_A[:6, :5], ScipyRK45.A, rtol=0, atol=1e-15)
    np.testing.assert_allclose(ode_solvers.DP_B5[:6], ScipyRK45.B, rtol=0, atol=1e-15)
    # SciPy stores the error weights with the opposite sign (b4 - b5).
    np.testing.assert_allclose(ode_solvers.DP_E, -ScipyRK45.E, rtol=0, atol=1e-15)


@pytest.mark.parametrize("rtol, atol", [(1e-3, 1e-6), (1e-6, 1e-9), (1e-10, 1e-12)])
@pytest.mark.parametrize("problem", PROBLEMS)
def test_rk45_against_exact_and_scipy(problem, rtol, atol):
    f, y0, t_end, exact = PROBLEMS[problem]
    t, y, nfev, stats = rk45(f, (0.0, t_end), y0, rtol=rtol, atol=atol)
    reference = solve_ivp(f, (0.0, t_end), [y0], method="RK45", rtol=rtol, atol=atol)
    allowed = VERIFY.rk45_tolerance_factor * (atol + rtol * abs(exact))
    assert t[-1] == t_end
    assert abs(y[-1] - exact) <= allowed
    assert abs(y[-1] - reference.y[0, -1]) <= allowed
    assert nfev <= VERIFY.rk45_max_nfev_ratio * reference.nfev
    # FSAL: 1 initial evaluation + 6 per attempted step.
    assert nfev == 1 + 6 * (stats.n_accepted + stats.n_rejected)


def test_rk45_vector_problem_against_scipy():
    # On a vector problem my RK45 is at least as accurate as SciPy's RK45 (the benchmark).
    rtol, atol = 1e-8, 1e-10
    t, y, _, _ = rk45(oscillator, (0.0, 10.0), [1.0, 0.0], rtol=rtol, atol=atol)
    reference = solve_ivp(oscillator, (0.0, 10.0), [1.0, 0.0], method="RK45", rtol=rtol, atol=atol)
    exact = np.array([np.cos(10.0), -np.sin(10.0)])
    assert y.shape == (len(t), 2)
    np.testing.assert_allclose(y[-1], exact, atol=100 * (atol + rtol))
    np.testing.assert_allclose(y[-1], reference.y[:, -1], atol=100 * (atol + rtol))


def test_rk45_error_falls_as_tolerance_tightens():
    # A tighter tolerance must give a smaller error.
    errors = []
    for rtol in (1e-4, 1e-7, 1e-10):
        _, d, _, _ = rk45(wear, (0.0, 40.0), 0.0, rtol=rtol, atol=rtol * 1e-3)
        errors.append(abs(d[-1] - wear_exact(40.0)))
    assert errors[0] > errors[1] > errors[2]


def test_rk45_rejects_a_too_large_first_step():
    # A first step of the whole interval on a fast-decaying problem must fail
    # the error test, be rejected and be retried with a smaller step.
    _, y, _, stats = rk45(lambda t, y: -50.0 * y, (0.0, 1.0), 1.0, h0=1.0,
                          rtol=1e-6, atol=1e-9)
    assert stats.n_rejected >= 1
    assert abs(y[-1] - np.exp(-50.0)) < 1e-8


def test_rk45_controller_settings_are_adjustable():
    # N3: the controller can be tuned; a smaller max_factor takes more steps.
    _, _, _, default = rk45(wear, (0.0, 40.0), 0.0, rtol=1e-6, atol=1e-9)
    _, _, _, cautious = rk45(wear, (0.0, 40.0), 0.0, rtol=1e-6, atol=1e-9, max_factor=2.0)
    assert isinstance(default, RK45Stats)
    assert cautious.n_accepted >= default.n_accepted


def test_rk45_max_steps_exceeded():
    # A step limit that is too small stops the solver with a clear error.
    with pytest.raises(ValueError, match="max_steps"):
        rk45(wear, (0.0, 40.0), 0.0, rtol=1e-12, atol=1e-14, max_steps=5)


@pytest.mark.parametrize(
    "settings, error",
    [
        (dict(rtol=0.0), ValueError),
        (dict(atol=-1.0), ValueError),
        (dict(rtol="1e-3"), TypeError),
        (dict(h0=0.0), ValueError),
        (dict(max_steps=0), ValueError),
        (dict(safety=1.5), ValueError),
        (dict(min_factor=1.5), ValueError),
        (dict(max_factor=0.9), ValueError),
    ],
)
def test_rk45_rejects_bad_settings(settings, error):
    # Invalid tolerances and step-control settings are rejected.
    with pytest.raises(error):
        rk45(wear, (0.0, 40.0), 0.0, **settings)
