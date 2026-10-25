"""Input checks added by the Phase 9 review pass (D86, C22). Offline, synthetic data."""

import numpy as np
import pandas as pd
import pytest

from tyredeg import cleaning, performance, sensitivity, strategy, validation
from tyredeg.models.common import (
    check_degrees_of_freedom,
    check_non_negative,
    format_parameter_table,
    prepare_stint_data,
    resample_stints,
)
from tyredeg.numerics.differentiation import default_step
from tyredeg.numerics.least_squares import fit_polynomial
from tyredeg.openf1_loading import OpenF1Client, find_race_session
from tyredeg.race_control import is_green_lap


def small_stints():
    # Five laps from two small stints, used as minimal valid model input.
    return prepare_stint_data([1, 2, 3, 1, 2], [80.0, 80.1, 80.2, 81.0, 81.2], ["A", "A", "A", "B", "B"])


def two_compounds():
    # Two compounds with straight-line degradation, used as a small strategy problem.
    return {"C3": strategy.CompoundModel("C3", strategy.LinearDegradation(0.06), 85.0, 40),
            "C4": strategy.CompoundModel("C4", strategy.LinearDegradation(0.055), 84.9, 35)}


# ---------------------------------------------------------------------------
# cleaning masks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mask", [
    cleaning.missing_lap_time_mask, cleaning.first_lap_mask, cleaning.pit_laps_mask,
    cleaning.not_green_mask, cleaning.missing_stint_info_mask,
])
def test_cleaning_masks_name_the_missing_column(mask):
    # A cleaning rule names the column it needs when that column is missing.
    with pytest.raises(ValueError, match="missing required columns"):
        mask(pd.DataFrame({"Unrelated": [1.0]}))


@pytest.mark.parametrize("mask", [cleaning.missing_lap_time_mask, cleaning.inaccurate_mask])
def test_cleaning_masks_reject_a_non_dataframe(mask):
    # A cleaning rule only accepts a DataFrame.
    with pytest.raises(TypeError):
        mask([80.0, 81.0])


# ---------------------------------------------------------------------------
# models.common
# ---------------------------------------------------------------------------
def test_stint_data_needs_one_value_per_lap():
    with pytest.raises(ValueError, match="one per lap"):
        small_stints().demean([1.0, 2.0])
    with pytest.raises(ValueError, match="one per lap"):
        small_stints().stint_means(np.ones(6))


def test_degrees_of_freedom_rejects_bad_parameter_counts():
    # A negative parameter count or non-stint data is rejected.
    with pytest.raises(ValueError):
        check_degrees_of_freedom(small_stints(), -1)
    with pytest.raises(TypeError):
        check_degrees_of_freedom("not data", 1)


def test_non_negative_check_validates_its_inputs():
    # The degradation function, the maximum age and the tolerance are all checked.
    with pytest.raises(TypeError):
        check_non_negative(0.05, 40.0, 0.01)
    with pytest.raises(ValueError):
        check_non_negative(lambda n: 0.05 * n, -1.0, 0.01)
    with pytest.raises(ValueError):
        check_non_negative(lambda n: 0.05 * n, 40.0, -0.01)
    with pytest.raises(ValueError, match="shape"):
        check_non_negative(lambda n: np.zeros(3), 40.0, 0.01)


def test_resample_stints_needs_stint_data_and_a_generator():
    # Resampling needs stint data and a seeded NumPy Generator (not a bare seed).
    with pytest.raises(TypeError):
        resample_stints([1, 2, 3], np.random.default_rng(42))
    with pytest.raises(TypeError, match="Generator"):
        resample_stints(small_stints(), 42)


def test_parameter_table_needs_matching_lengths():
    # Names, estimates and errors must have the same length.
    with pytest.raises(ValueError, match="same length"):
        format_parameter_table(["a", "b"], [0.06], [0.002])


# ---------------------------------------------------------------------------
# numerics
# ---------------------------------------------------------------------------
def test_default_step_rejects_non_finite_points_and_bad_exponents():
    with pytest.raises(ValueError):
        default_step(np.nan, 0.5)
    with pytest.raises(ValueError):
        default_step(1.0, 0.0)


def test_polynomial_prediction_rejects_nan():
    # A NaN tyre age cannot be predicted.
    fit = fit_polynomial([0, 1, 2], [1.0, 3.0, 5.0], 1)
    with pytest.raises(ValueError):
        fit.predict([np.nan])


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def test_green_lap_rejects_negative_lap_time():
    with pytest.raises(ValueError):
        is_green_lap(pd.Timestamp("2023-07-23 13:00"), -80.0, [])


def test_openf1_cache_path_checks_its_arguments(tmp_path):
    # Cache file names need a non-empty endpoint and a dict of query parameters.
    client = OpenF1Client(tmp_path)
    with pytest.raises(TypeError):
        client.cache_path("", {})
    with pytest.raises(TypeError):
        client.cache_path("laps", ["session_key", 1])


def test_find_race_session_needs_a_timestamp():
    # The session search needs a real date type, not a string.
    with pytest.raises(TypeError):
        find_race_session(object(), 2023, "2023-07-23")


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("counter", [performance.euler_step_flops, performance.heun_step_flops,
                                     performance.rk4_step_flops, performance.rk45_attempt_flops])
@pytest.mark.parametrize("bad", [-1, 2.5, True])
def test_flop_counters_reject_invalid_counts(counter, bad):
    # Negative or non-integer sizes are rejected.
    with pytest.raises(ValueError):
        counter(bad)


def test_profile_function_rejects_a_bad_top():
    # The number of profile rows shown must be positive.
    with pytest.raises(ValueError):
        performance.profile_function(lambda: None, top=0)


# ---------------------------------------------------------------------------
# sensitivity
# ---------------------------------------------------------------------------
def test_one_at_a_time_checks_evaluate_and_variations():
    with pytest.raises(TypeError):
        sensitivity.one_at_a_time("not callable", [])
    with pytest.raises(TypeError, match="overrides dict"):
        sensitivity.one_at_a_time(lambda **kw: {"y": 1.0}, [("x", "low")])
    with pytest.raises(TypeError, match="dict of outputs"):
        sensitivity.one_at_a_time(lambda **kw: 1.0, [])


def test_tornado_table_needs_exactly_one_nominal_row():
    # The tornado table needs exactly one nominal row and the required columns.
    oat = pd.DataFrame({"input": ["a", "a"], "label": ["l", "h"], "y": [0.0, 1.0]})
    with pytest.raises(ValueError, match="nominal"):
        sensitivity.tornado_table(oat, "y")
    with pytest.raises(ValueError, match="missing columns"):
        sensitivity.tornado_table(oat, "z")


def test_plot_tornado_rejects_an_empty_table(tmp_path):
    # An empty tornado table cannot be plotted.
    empty = pd.DataFrame({"input": [], "low_change": [], "high_change": []})
    with pytest.raises(ValueError, match="empty"):
        sensitivity.plot_tornado(empty, 1.0, "t", "x", tmp_path / "t.png")


def test_step_size_check_needs_at_least_one_step():
    # The step-size check needs at least one step.
    with pytest.raises(ValueError):
        sensitivity.step_size_check(lambda x: x, 1.0, [])


def test_fuel_refit_needs_two_coefficients():
    # The fuel refit needs at least two coefficients to show a trend.
    with pytest.raises(ValueError, match="at least 2"):
        sensitivity.degradation_rate_vs_fuel(pd.DataFrame(), "C3", [0.046], 0.046)


# ---------------------------------------------------------------------------
# strategy
# ---------------------------------------------------------------------------
def test_fuel_effect_total_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        strategy.fuel_effect_total(0, 0.046)
    with pytest.raises(ValueError):
        strategy.fuel_effect_total(70, -0.01)
    with pytest.raises(TypeError):
        strategy.fuel_effect_total(70.5, 0.046)


def test_feasible_pit_laps_rejects_unknown_compound():
    # Only compounds that have a model can be used.
    with pytest.raises(ValueError, match="Unknown compound"):
        strategy.feasible_pit_laps("C3", "C5", two_compounds(), 70)


def test_stint_time_checks_its_inputs():
    # The stint time needs a CompoundModel and a non-negative stint length.
    with pytest.raises(TypeError):
        strategy.stint_time("C3", 10)
    with pytest.raises(ValueError):
        strategy.stint_time(two_compounds()["C3"], -1)


def test_linear_degradation_rejects_negative_ages():
    # Tyre ages cannot be negative.
    with pytest.raises(ValueError):
        strategy.LinearDegradation(0.06).degradation([-1.0])


def test_max_stint_rejects_empty_ages():
    # The maximum stint length needs at least one observed tyre age.
    with pytest.raises(ValueError):
        strategy.max_stint_from_data([], 5)


def test_refuel_needs_a_dataframe():
    # Refuelling only works on a DataFrame of laps.
    with pytest.raises(TypeError):
        strategy.refuel([80.0], 0.046)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def test_binned_residuals_checks_lengths_and_edges():
    with pytest.raises(ValueError, match="differ in length"):
        validation.binned_residuals([1, 2], [0.1], [0, 10])
    with pytest.raises(ValueError, match="strictly increasing"):
        validation.binned_residuals([1, 2], [0.1, 0.2], [10, 0])


def test_summarize_folds_needs_the_baseline():
    # The fold summary compares against the baseline, so the baseline must be present.
    table = pd.DataFrame({"model": ["polynomial degree 1"], "family": ["polynomial"], "fold": [0],
                          "applicable": [True], "rmse": [0.6], "mae": [0.5], "max_abs_error": [2.0],
                          "r_squared": [0.1], "bias": [0.0]})
    with pytest.raises(ValueError, match="baseline"):
        validation.summarize_folds(table, 0.10)


def test_rank_compounds_needs_a_rate_column():
    # Ranking compounds needs a degradation-rate column.
    with pytest.raises(ValueError, match="rate"):
        validation.rank_compounds(pd.DataFrame({"compound": ["C3"]}))


def test_fold_masks_and_fit_on_check_their_inputs():
    # Folds need a RaceId column, and fit_on needs a model spec.
    with pytest.raises(ValueError, match="RaceId"):
        validation.fold_masks(pd.DataFrame({"x": [1]}), validation.Fold(("r1",), ("r2",)))
    with pytest.raises(TypeError):
        validation.fit_on("not a spec", pd.DataFrame())


def test_cross_validate_needs_folds():
    # Cross-validation needs at least one fold.
    with pytest.raises(ValueError, match="at least one Fold"):
        validation.cross_validate(pd.DataFrame(), None, [], 3)


def test_write_selection_needs_dicts(tmp_path):
    # The selection is written from dicts only.
    with pytest.raises(TypeError):
        validation.write_selection(tmp_path / "s.json", ["C3"], {})


def test_candidate_models_rejects_unknown_compound():
    # Unknown compounds have no candidate models.
    from tyredeg.config import load_config

    with pytest.raises(ValueError):
        validation.candidate_models("C9", load_config("config.yaml").models)


def test_monotonic_check_validates_its_inputs():
    # The monotonicity check needs a function and a finite maximum age.
    with pytest.raises(TypeError):
        validation.check_monotonic(0.07, 40.0, 0.05)
    with pytest.raises(ValueError):
        validation.check_monotonic(lambda n: 0.07 * n, np.inf, 0.05)
