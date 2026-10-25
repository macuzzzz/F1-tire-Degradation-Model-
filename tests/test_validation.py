"""Offline tests for tyredeg.validation (metrics, splits, CV, selection, checks, firewall)."""

import numpy as np
import pandas as pd
import pytest

from tyredeg.config import load_config
from tyredeg.validation import (
    BASELINE_NAME,
    Fold,
    FirewallError,
    bias,
    binned_residuals,
    candidate_models,
    check_monotonic,
    compute_metrics,
    cross_validate,
    fold_masks,
    guard_test_run,
    holdout_split,
    leave_one_race_out,
    leftover_fuel_effect,
    load_selection,
    mae,
    max_abs_error,
    predict_held_out,
    r_squared,
    rank_compounds,
    rmse,
    select_models,
    summarize_folds,
    write_selection,
)

SEED = 42


# ---------------------------------------------------------------------------
# Metrics on hand-computed examples
# ---------------------------------------------------------------------------
# actual = [1, 2, 3, 4], predicted = [1, 3, 2, 6]
# errors (predicted - actual) = [0, 1, -1, 2]
#   RMSE = sqrt((0 + 1 + 1 + 4) / 4) = sqrt(1.5) = 1.2247449
#   MAE  = (0 + 1 + 1 + 2) / 4 = 1.0
#   max  = 2.0
#   bias = (0 + 1 - 1 + 2) / 4 = 0.5
#   R^2  = 1 - SS_res / SS_tot = 1 - 6 / 5 = -0.2   (mean of actual = 2.5;
#          SS_tot = 2.25 + 0.25 + 0.25 + 2.25 = 5)
ACTUAL = [1.0, 2.0, 3.0, 4.0]
PREDICTED = [1.0, 3.0, 2.0, 6.0]


def test_metrics_hand_computed():
    # Metrics on a small example computed by hand.
    assert rmse(ACTUAL, PREDICTED) == pytest.approx(np.sqrt(1.5))
    assert mae(ACTUAL, PREDICTED) == pytest.approx(1.0)
    assert max_abs_error(ACTUAL, PREDICTED) == pytest.approx(2.0)
    assert bias(ACTUAL, PREDICTED) == pytest.approx(0.5)
    assert r_squared(ACTUAL, PREDICTED) == pytest.approx(-0.2)


def test_metrics_second_example():
    # actual [10, 20], predicted [12, 17]: errors [2, -3]
    # RMSE = sqrt((4 + 9) / 2) = sqrt(6.5); MAE = 2.5; bias = -0.5;
    # R^2 = 1 - 13 / 50 = 0.74 (mean 15, SS_tot = 25 + 25).
    m = compute_metrics([10.0, 20.0], [12.0, 17.0])
    assert m["rmse"] == pytest.approx(np.sqrt(6.5))
    assert m["mae"] == pytest.approx(2.5)
    assert m["bias"] == pytest.approx(-0.5)
    assert m["r_squared"] == pytest.approx(0.74)
    assert m["n"] == 2


def test_perfect_prediction_and_constant_actual():
    m = compute_metrics(ACTUAL, ACTUAL)
    assert m["rmse"] == 0.0 and m["r_squared"] == 1.0
    assert np.isnan(r_squared([5.0, 5.0], [5.0, 6.0]))  # SS_tot = 0: undefined


@pytest.mark.parametrize("actual, predicted", [([], []), ([1.0, 2.0], [1.0]), ([1.0, np.nan], [1.0, 2.0])])
def test_metric_input_validation(actual, predicted):
    # Invalid metric inputs are rejected.
    with pytest.raises(ValueError):
        rmse(actual, predicted)


# ---------------------------------------------------------------------------
# Splits never put the same race in train and test
# ---------------------------------------------------------------------------
RACES = ["2022_hungarian_grand_prix", "2023_hungarian_grand_prix", "2024_hungarian_grand_prix"]


def test_leave_one_race_out_folds_are_disjoint_and_complete():
    folds = leave_one_race_out(RACES + RACES)  # duplicates ignored
    assert len(folds) == 3
    tested = []
    for fold in folds:
        assert set(fold.train_races).isdisjoint(fold.test_races)
        assert set(fold.train_races) | set(fold.test_races) == set(RACES)
        assert len(fold.test_races) == 1
        tested.extend(fold.test_races)
    assert sorted(tested) == RACES  # every race is held out exactly once


def test_test_race_never_in_training_fold_when_not_passed():
    # The CV stage passes only training races, so 2025 cannot appear anywhere.
    for fold in leave_one_race_out(RACES):
        assert "2025_hungarian_grand_prix" not in fold.train_races + fold.test_races


def test_holdout_split():
    # The named race becomes the test race, all others are training races.
    fold = holdout_split(RACES + ["2025_hungarian_grand_prix"], ["2025_hungarian_grand_prix"])
    assert fold.test_races == ("2025_hungarian_grand_prix",)
    assert fold.train_races == tuple(RACES)
    with pytest.raises(ValueError, match="not found"):
        holdout_split(RACES, ["2030_x"])


def test_fold_rejects_overlap_and_empty_sides():
    # A race cannot be on both sides, and neither side can be empty.
    with pytest.raises(ValueError, match="both"):
        Fold(("r1", "r2"), ("r2",))
    with pytest.raises(ValueError):
        Fold((), ("r1",))
    with pytest.raises(ValueError):
        leave_one_race_out(["r1"])


def test_fold_masks_split_laps_by_race():
    # Fold masks split laps by race, with no lap on both sides.
    laps = pd.DataFrame({"RaceId": ["r1", "r1", "r2", "r3"]})
    train, test = fold_masks(laps, Fold(("r1", "r3"), ("r2",)))
    assert train.tolist() == [True, True, False, True]
    assert test.tolist() == [False, False, True, False]
    assert not np.any(train & test)


# ---------------------------------------------------------------------------
# Anchored prediction and cross-validation
# ---------------------------------------------------------------------------
def synthetic_laps(rate=0.07, n_races=3, stints_per_race=12, noise=0.3, seed=SEED):
    """Clean-lap table: offset per stint + rate * tyre age + noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for race in range(n_races):
        for stint in range(stints_per_race):
            start_lap = int(rng.integers(2, 40))
            length = int(rng.integers(12, 25))
            age = np.arange(2.0, 2.0 + length)
            offset = rng.normal(85.0, 0.6)
            for i in range(length):
                rows.append({"RaceId": f"r{race}", "StintId": f"r{race}|D{stint}|1",
                             "Driver": f"D{stint}", "LapNumber": float(start_lap + i),
                             "TyreLife": age[i], "PirelliCompound": "C3",
                             "FuelCorrectedTime": offset + rate * age[i] + rng.normal(0.0, noise)})
    return pd.DataFrame(rows)


class LinearDegradation:
    def __init__(self, rate):
        # Degradation rate in seconds per lap of tyre age.
        self.rate = rate

    def degradation(self, tyre_age):
        # Degradation grows linearly with tyre age.
        return self.rate * np.asarray(tyre_age, dtype=float)


def test_anchored_prediction_is_exact_for_noise_free_data():
    laps = synthetic_laps(noise=0.0, n_races=1, stints_per_race=4)
    scored = predict_held_out(LinearDegradation(0.07), laps, anchor_laps=3)
    np.testing.assert_allclose(scored["predicted"], scored["actual"], atol=1e-9)
    # The anchor laps are not scored: 3 fewer laps per stint.
    assert len(scored) == len(laps) - 3 * laps["StintId"].nunique()


def test_anchor_uses_only_the_first_laps():
    laps = pd.DataFrame({"RaceId": "r", "StintId": "s", "LapNumber": [5.0, 6.0, 7.0, 8.0],
                         "TyreLife": [1.0, 2.0, 3.0, 4.0], "FuelCorrectedTime": [80.0, 80.0, 99.0, 99.0]})
    # Baseline (d = 0), anchor 2 laps: offset = 80, predictions for laps 7, 8 = 80.
    scored = predict_held_out(LinearDegradation(0.0), laps, anchor_laps=2)
    assert scored["predicted"].tolist() == [80.0, 80.0]
    assert scored["residual"].tolist() == [-19.0, -19.0]


def test_predict_held_out_rejects_bad_anchor_and_short_stints():
    # Invalid anchor counts and stints too short to score are rejected.
    laps = synthetic_laps(n_races=1, stints_per_race=2)
    with pytest.raises(ValueError):
        predict_held_out(LinearDegradation(0.07), laps, anchor_laps=0)
    with pytest.raises(ValueError, match="nothing to score"):
        predict_held_out(LinearDegradation(0.07), laps, anchor_laps=100)


@pytest.fixture(scope="module")
def models_settings():
    # The model settings from the real config.yaml.
    return load_config("config.yaml").models


def test_cross_validation_recovers_degradation_and_beats_baseline(models_settings):
    laps = synthetic_laps()
    folds = leave_one_race_out(laps["RaceId"])
    specs = {s.name: s for s in candidate_models("C3", models_settings)}
    tables = []
    for name in (BASELINE_NAME, "polynomial degree 1", "knn k=10 uniform"):
        table, scored = cross_validate(laps, specs[name], folds, anchor_laps=3)
        assert set(scored["fold"]) == {0, 1, 2}
        tables.append(table)
    summary = summarize_folds(pd.concat(tables), max_abs_bias=0.1).set_index("model")
    assert summary.loc["polynomial degree 1", "beats_baseline_all_folds"]
    assert summary.loc["polynomial degree 1", "rmse_mean"] == pytest.approx(0.3 * np.sqrt(1 + 1 / 3), rel=0.25)
    assert summary.loc[BASELINE_NAME, "bias_mean"] < -0.3  # misses the wear


def test_cross_validation_skips_k_larger_than_training_set(models_settings):
    laps = synthetic_laps(n_races=3, stints_per_race=3)  # ~110 training laps per fold
    specs = {s.name: s for s in candidate_models("C3", models_settings)}
    table, _ = cross_validate(laps, specs["knn k=400 uniform"], leave_one_race_out(laps["RaceId"]), 3)
    assert not table["applicable"].any()


def test_cross_validation_never_trains_on_the_held_out_race(models_settings):
    # A recording model checks that no fold is ever trained on its own test race.
    laps = synthetic_laps()
    seen = []

    class Recorder:
        name, family, complexity, min_training_laps = "recorder", "polynomial", 1, 0

        @staticmethod
        def fit(ages, times, ids):
            # Record which races each fit sees, then return a fixed model.
            seen.append({label.split("|")[0] for label in ids})
            return LinearDegradation(0.07)

    folds = leave_one_race_out(laps["RaceId"])
    cross_validate(laps, Recorder, folds, 3)
    for fold, training_races in zip(folds, seen):
        assert training_races == set(fold.train_races)
        assert not training_races & set(fold.test_races)


# ---------------------------------------------------------------------------
# Selection rule (D48)
# ---------------------------------------------------------------------------
def test_one_standard_error_rule_prefers_simpler_model():
    summary = pd.DataFrame({
        "model": [BASELINE_NAME, "polynomial degree 1", "polynomial degree 3", "wear ODE", "knn k=50"],
        "family": ["baseline", "polynomial", "polynomial", "wear_ode", "knn"],
        "rmse_mean": [1.2, 0.64, 0.62, 0.63, 0.61],
        "rmse_se": [0.1, 0.05, 0.05, 0.05, 0.05],
    })
    complexity = {BASELINE_NAME: 0, "polynomial degree 1": 1, "polynomial degree 3": 3,
                  "wear ODE": 2, "knn k=50": 10}
    result = select_models(summary, complexity)
    assert result["family_winners"] == {"polynomial": "polynomial degree 3", "wear_ode": "wear ODE",
                                        "knn": "knn k=50"}
    # Best = 0.61 +/- 0.05 -> threshold 0.66; simplest family winner within it = wear ODE (2).
    assert result["selected"] == "wear ODE"
    assert result["threshold"] == pytest.approx(0.66)


def test_selection_picks_best_when_others_are_too_far():
    # If no simpler model is within one SE of the best, the best model is chosen.
    summary = pd.DataFrame({"model": ["p1", "k"], "family": ["polynomial", "knn"],
                            "rmse_mean": [0.80, 0.60], "rmse_se": [0.01, 0.01]})
    assert select_models(summary, {"p1": 1, "k": 10})["selected"] == "k"


def test_selection_needs_a_candidate():
    # At least one candidate besides the baseline is needed.
    with pytest.raises(ValueError):
        select_models(pd.DataFrame({"model": [BASELINE_NAME], "family": ["baseline"],
                                    "rmse_mean": [1.0], "rmse_se": [0.1]}), {BASELINE_NAME: 0})


# ---------------------------------------------------------------------------
# Physical consistency, ranking, residuals
# ---------------------------------------------------------------------------
def test_monotonic_check():
    assert check_monotonic(lambda n: 0.07 * n, 40.0, 0.05).ok
    wiggly = check_monotonic(lambda n: 0.07 * n - 0.2 * (n == 20), 40.0, 0.05)
    assert not wiggly.ok and wiggly.n_drops_over_tolerance == 1
    assert wiggly.largest_drop_s == pytest.approx(0.2 - 0.07)
    with pytest.raises(ValueError):
        check_monotonic(lambda n: n, 10.0, -1.0)


def test_rank_compounds_reports_without_forcing_an_order():
    rates = pd.DataFrame({"compound": ["C3", "C4", "C5"], "rate": [0.07, 0.05, 0.09],
                          "lower": [0.06, 0.04, 0.08], "upper": [0.08, 0.06, 0.10]})
    ranked = rank_compounds(rates)
    assert ranked["compound"].tolist() == ["C5", "C3", "C4"]  # softest is not assumed fastest
    assert ranked["rank"].tolist() == [1, 2, 3]


def test_binned_residuals():
    # Residual counts, means and standard errors per tyre-age bin.
    table = binned_residuals([1, 2, 11, 12, 25], [0.1, -0.1, 0.5, 0.7, 9.0], [0, 10, 20])
    assert table["n"].tolist() == [2, 2]
    assert table["mean"].round(6).tolist() == [0.0, 0.6]
    assert table["se"].iloc[1] == pytest.approx(np.std([0.5, 0.7], ddof=1) / np.sqrt(2))


def fuel_laps(leftover):
    """Two stints per driver-race (age resets at the stop, lap number does not)."""
    rng = np.random.default_rng(SEED)
    rows = []
    for race in range(3):
        for driver in range(15):
            offset = rng.normal(85.0, 0.6)
            stop = int(rng.integers(20, 40))
            for lap in range(2, 70):
                age = lap - 1 if lap <= stop else lap - stop
                rows.append({"RaceId": f"r{race}", "Driver": f"D{driver}", "LapNumber": float(lap),
                             "TyreLife": float(age), "PirelliCompound": "C3",
                             "FuelCorrectedTime": offset + 0.07 * age + leftover * lap
                             + rng.normal(0.0, 0.3)})
    return pd.DataFrame(rows)


def test_leftover_fuel_effect_is_recovered():
    # A leftover fuel effect of 0.02 s/lap is recovered and flagged.
    result = leftover_fuel_effect(fuel_laps(0.02), ["C3"], 100, 0.95, SEED)
    assert result.estimate == pytest.approx(0.02, abs=0.003)
    assert result.flagged and result.lower > 0


def test_no_leftover_fuel_effect_is_not_flagged():
    # Without a leftover fuel effect nothing is flagged.
    result = leftover_fuel_effect(fuel_laps(0.0), ["C3"], 100, 0.95, SEED)
    assert abs(result.estimate) < 0.003
    assert not result.flagged and result.lower < 0 < result.upper


# ---------------------------------------------------------------------------
# Test-set firewall (D55)
# ---------------------------------------------------------------------------
def test_test_stage_refuses_without_selection(tmp_path):
    with pytest.raises(FirewallError, match="cross-validation stage first"):
        load_selection(tmp_path / "model_selection.json")


def test_selection_round_trip(tmp_path):
    # The saved selection reads back with the same content.
    path = tmp_path / "sub" / "model_selection.json"
    write_selection(path, {"C3": {"selected": "polynomial degree 1"}}, {"git_commit": "abc"})
    loaded = load_selection(path)
    assert loaded["selection"]["C3"]["selected"] == "polynomial degree 1"
    assert loaded["git_commit"] == "abc" and "created_utc" in loaded


def test_test_run_happens_once_unless_forced(tmp_path):
    results, log = tmp_path / "test_results.csv", tmp_path / "test_runs.log"
    guard_test_run(results, log)            # first run allowed
    results.write_text("done")
    with pytest.raises(FirewallError, match="already"):
        guard_test_run(results, log)        # repeat refused
    guard_test_run(results, log, force=True)  # forced repeat allowed ...
    lines = log.read_text().splitlines()
    assert len(lines) == 2 and "FORCED" in lines[1]  # ... and logged


def test_cv_rerun_refused_after_the_test_unless_forced(tmp_path):
    from tyredeg.validation import guard_cv_rerun

    selection, results = tmp_path / "model_selection.json", tmp_path / "test_results.csv"
    guard_cv_rerun(selection, results)          # nothing exists yet: allowed
    selection.write_text("{}")
    guard_cv_rerun(selection, results)          # selection but no test yet: allowed
    results.write_text("done")
    with pytest.raises(FirewallError, match="must not be overwritten"):
        guard_cv_rerun(selection, results)      # after the test: refused
    guard_cv_rerun(selection, results, force=True)  # deliberate override allowed
