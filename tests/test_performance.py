"""Tests for tyredeg.performance and for the Phase 8 optimisation (identical results)."""

import numpy as np
import pandas as pd
import pytest

from tyredeg.config import load_config
from tyredeg.performance import (
    WEAR_RHS_FLOPS,
    euler_step_flops,
    heun_step_flops,
    machine_info,
    peak_memory,
    profile_function,
    rk4_step_flops,
    rk45_attempt_flops,
    solver_flops,
    time_function,
)
from tyredeg.validation import (
    candidate_models,
    cross_validate,
    leave_one_race_out,
    predict_held_out,
    predict_held_out_loop,
)

# Stated tolerance for "same numerical results" after the optimisation (D80).
EQUIVALENCE_ATOL_S = 1e-12


# ---------------------------------------------------------------------------
# Timing, memory, profiling helpers
# ---------------------------------------------------------------------------
def test_time_function_runs_warmup_and_repeats():
    calls = []
    result = time_function(lambda: calls.append(1), repeats=5, warmup=2)
    assert len(calls) == 7                       # 2 warm-up + 5 timed
    assert result.repeats == 5 and len(result.values) == 5
    assert result.minimum <= result.mean
    assert result.std >= 0


def test_time_function_measures_a_sleep():
    import time

    result = time_function(lambda: time.sleep(0.01), repeats=3, warmup=0)
    assert result.minimum >= 0.009


def test_time_function_calibrates_calls_for_short_functions():
    calls = []
    result = time_function(lambda: calls.append(1), repeats=4, warmup=1, min_time_s=0.002)
    assert result.calls_per_repeat > 1
    # 1 warm-up call + 4 repeats x calls_per_repeat calls.
    assert len(calls) == 1 + 4 * result.calls_per_repeat
    # The reported value is the time PER CALL, far below the 2 ms repeat length.
    assert result.mean < 0.002


def test_time_function_long_calls_are_not_repeated():
    import time

    result = time_function(lambda: time.sleep(0.02), repeats=2, warmup=1, min_time_s=0.01)
    assert result.calls_per_repeat == 1


@pytest.mark.parametrize("kwargs", [dict(repeats=0), dict(warmup=-1), dict(repeats=2.5),
                                    dict(min_time_s=0.0)])
def test_time_function_rejects_bad_settings(kwargs):
    with pytest.raises(ValueError):
        time_function(lambda: None, **kwargs)
    with pytest.raises(TypeError):
        time_function("not callable")


def test_peak_memory_sees_numpy_allocations():
    _, small = peak_memory(lambda: np.ones(10))
    result, large = peak_memory(lambda: np.ones(2_000_000))   # 16 MB of float64
    assert large >= 16_000_000 > small
    assert result.shape == (2_000_000,)


def test_machine_info_and_profile():
    info = machine_info()
    assert {"python", "numpy", "cpu_count", "platform"} <= set(info)

    def work():
        return sorted(np.random.default_rng(42).random(5000))

    result, table = profile_function(work, top=10)
    assert len(result) == 5000
    assert len(table) <= 10
    assert table["cumtime_s"].is_monotonic_decreasing
    assert any("work" in name for name in table["function"])


# ---------------------------------------------------------------------------
# FLOP counts (hand-derived in the docstrings, D76)
# ---------------------------------------------------------------------------
def test_flops_per_step_match_hand_counts():
    assert WEAR_RHS_FLOPS == 2
    assert euler_step_flops(2) == 5     # f (2) + y + h k (2) + t + h (1)
    assert heun_step_flops(2) == 11     # 2 f (4) + 7
    assert rk4_step_flops(2) == 25      # 4 f (8) + 17
    assert rk45_attempt_flops(2) == 105  # worked count in the docstring


def test_flops_scale_with_cost_of_f():
    # One more FLOP in f adds (number of f evaluations per step) FLOPs per step.
    assert euler_step_flops(3) - euler_step_flops(2) == 1
    assert heun_step_flops(3) - heun_step_flops(2) == 2
    assert rk4_step_flops(3) - rk4_step_flops(2) == 4
    assert rk45_attempt_flops(3) - rk45_attempt_flops(2) == 6   # 6 new stages (FSAL)


def test_solver_flops_totals():
    assert solver_flops("euler", 40) == 200
    assert solver_flops("rk4", 40) == 1000
    assert solver_flops("rk45", 10, n_rejected=2) == 12 * 105 + 2
    with pytest.raises(ValueError):
        solver_flops("midpoint", 10)
    with pytest.raises(ValueError):
        solver_flops("rk4", -1)


# ---------------------------------------------------------------------------
# The optimisation gives the same results (D80)
# ---------------------------------------------------------------------------
def synthetic_laps(n_races=3, stints_per_race=14, seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    for race in range(n_races):
        for stint in range(stints_per_race):
            start = int(rng.integers(2, 40))
            length = int(rng.integers(4, 26))      # includes stints shorter than the anchor + 1
            offset = rng.normal(85.0, 0.6)
            for i in range(length):
                age = 2.0 + i
                rows.append({"RaceId": f"r{race}", "StintId": f"r{race}|D{stint}|1",
                             "LapNumber": float(start + i), "TyreLife": age,
                             "FuelCorrectedTime": offset + 0.06 * age + 0.001 * age**2
                             + rng.normal(0.0, 0.4)})
    laps = pd.DataFrame(rows)
    return laps.sample(frac=1.0, random_state=seed).reset_index(drop=True)  # unsorted input


@pytest.fixture(scope="module")
def specs():
    return {spec.name: spec for spec in candidate_models("C3", load_config("config.yaml").models)}


@pytest.mark.parametrize("name", ["baseline (no degradation)", "polynomial degree 2", "wear ODE",
                                  "knn k=10 uniform", "knn k=50 distance"])
@pytest.mark.parametrize("anchor", [1, 3, 5])
def test_vectorised_prediction_equals_original_loop(specs, name, anchor):
    laps = synthetic_laps()
    model = specs[name].fit(laps["TyreLife"].to_numpy(), laps["FuelCorrectedTime"].to_numpy(),
                            laps["StintId"].to_numpy())
    fast = predict_held_out(model, laps, anchor)
    slow = predict_held_out_loop(model, laps, anchor)
    assert list(fast.columns) == list(slow.columns)
    assert len(fast) == len(slow)
    pd.testing.assert_frame_equal(fast[["RaceId", "StintId"]], slow[["RaceId", "StintId"]])
    for column in ("LapNumber", "TyreLife", "actual", "predicted", "residual"):
        np.testing.assert_allclose(fast[column], slow[column], rtol=0, atol=EQUIVALENCE_ATOL_S)


def test_cross_validation_identical_with_both_implementations(specs):
    laps = synthetic_laps()
    folds = leave_one_race_out(laps["RaceId"])
    for name in ("polynomial degree 1", "wear ODE", "knn k=25 uniform"):
        fast, _ = cross_validate(laps, specs[name], folds, 3, implementation="vectorised")
        slow, _ = cross_validate(laps, specs[name], folds, 3, implementation="loop")
        for column in ("rmse", "mae", "max_abs_error", "bias", "r_squared"):
            np.testing.assert_allclose(fast[column], slow[column], rtol=0, atol=EQUIVALENCE_ATOL_S)


def test_unknown_implementation_is_rejected(specs):
    laps = synthetic_laps()
    with pytest.raises(ValueError, match="implementation"):
        cross_validate(laps, specs["polynomial degree 1"], leave_one_race_out(laps["RaceId"]), 3,
                       implementation="gpu")


def test_both_versions_reject_unscorable_input(specs):
    laps = synthetic_laps().head(3)
    model = specs["baseline (no degradation)"].fit(None, None, None)
    for predictor in (predict_held_out, predict_held_out_loop):
        with pytest.raises(ValueError, match="nothing to score"):
            predictor(model, laps, 50)
