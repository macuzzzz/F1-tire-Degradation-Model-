"""The numerics function defaults must equal config.yaml's `numerics` section (D38).

Function defaults let the methods be called and tested on their own, while
config.yaml is the single documented place for numerical choices (rule E).
This test fails if the two ever drift apart.
"""

import inspect
from pathlib import Path

from tyredeg.config import load_config
from tyredeg.numerics import differentiation, least_squares, linear_solvers, ode_solvers, root_finding

NUMERICS = load_config(Path(__file__).resolve().parents[1] / "config.yaml").numerics


def defaults_of(function):
    return {name: p.default for name, p in inspect.signature(function).parameters.items()
            if p.default is not inspect.Parameter.empty}


def test_ode_defaults_match_config():
    ode = NUMERICS.ode
    assert defaults_of(ode_solvers.rk45) == {
        "rtol": ode.rtol, "atol": ode.atol, "h0": None, "max_steps": ode.max_steps,
        "safety": ode.safety, "min_factor": ode.min_factor, "max_factor": ode.max_factor,
    }
    assert ode_solvers.DEFAULT_INITIAL_STEP_FRACTION == ode.initial_step_fraction


def test_root_finding_defaults_match_config():
    settings = NUMERICS.root_finding
    expected = {"xtol": settings.xtol, "ftol": settings.ftol, "max_iter": settings.max_iter}
    assert defaults_of(root_finding.bisection) == expected
    expected["divergence_limit"] = settings.divergence_limit
    assert defaults_of(root_finding.secant) == expected
    assert defaults_of(root_finding.newton) == expected


def test_differentiation_defaults_match_config():
    assert differentiation.FORWARD_STEP_EXPONENT == NUMERICS.forward_step_exponent
    assert differentiation.CENTRAL_STEP_EXPONENT == NUMERICS.central_step_exponent
    assert differentiation.SECOND_STEP_EXPONENT == NUMERICS.second_step_exponent


def test_linear_and_least_squares_defaults_match_config():
    threshold = NUMERICS.condition_warning_threshold
    assert defaults_of(linear_solvers.gaussian_elimination)["condition_threshold"] == threshold
    assert defaults_of(least_squares.fit_linear_least_squares)["condition_threshold"] == threshold
    assert defaults_of(least_squares.fit_polynomial)["scale"] == NUMERICS.scale_polynomial_inputs


def test_model_defaults_match_config():
    # Phase 4 model defaults must equal the `models` section of config.yaml (D46).
    from tyredeg.models import knn, polynomial, wear_ode

    models = load_config(Path(__file__).resolve().parents[1] / "config.yaml").models
    assert polynomial.DEFAULT_DEGREE == models.default_degree
    assert wear_ode.DEFAULT_SOLVER == models.ode_solver
    assert wear_ode.DEFAULT_B_BRACKET == models.b_bracket
    assert wear_ode.DEFAULT_B_GRID_POINTS == models.b_grid_points
    assert (wear_ode.DEFAULT_B_XTOL, wear_ode.DEFAULT_B_FTOL) == (models.b_xtol, models.b_ftol)
    assert wear_ode.DEFAULT_RK4_STEP == models.rk4_step
    assert (wear_ode.DEFAULT_RK45_RTOL, wear_ode.DEFAULT_RK45_ATOL) == (models.rk45_rtol, models.rk45_atol)
    assert (knn.DEFAULT_K, knn.DEFAULT_WEIGHTS) == (models.default_k, models.default_weights)
    for module in (polynomial, wear_ode, knn):
        assert module.DEFAULT_NEGATIVE_TOLERANCE_S == models.negative_degradation_tolerance_s
