"""Offline tests for tyredeg.cleaning.

The main test builds a small synthetic race in which every cleaning rule has
a known number of laps to remove, so the report can be checked exactly.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from tyredeg.cleaning import (
    RULE_ORDER,
    clean_laps,
    first_lap_mask,
    inaccurate_mask,
    missing_lap_time_mask,
    missing_stint_info_mask,
    not_green_mask,
    outliers_mask,
    pit_laps_mask,
    robust_outlier_flags,
    short_stints_mask,
    theil_sen_line,
)

SETTINGS = SimpleNamespace(outlier_k=3.0, min_stint_laps=10)


def small_noise(lap_numbers):
    """Deterministic, irregular noise of about +/-0.1 s (no random numbers needed)."""
    return 0.1 * np.sin(1.7 * np.asarray(lap_numbers, dtype=float))


def make_stint(driver, stint, first_lap, n_laps, base=80.0, slope=0.05, race="r1"):
    """Laps of one clean stint: lap time = base + slope * tyre age + small noise."""
    laps = np.arange(first_lap, first_lap + n_laps, dtype=float)
    tyre_age = np.arange(1, n_laps + 1, dtype=float)
    return pd.DataFrame(
        {
            "RaceId": race,
            "Driver": driver,
            "LapNumber": laps,
            "LapTime": base + slope * tyre_age + small_noise(laps),
            "Stint": float(stint),
            "Compound": "HARD",
            "TyreLife": tyre_age,
            "IsPitInLap": False,
            "IsPitOutLap": False,
            "IsGreenLap": True,
            "IsAccurate": True,
        }
    )


def set_value(laps, driver, lap, column, value):
    """Change one cell, identified by driver and lap number."""
    row = (laps["Driver"] == driver) & (laps["LapNumber"] == lap)
    assert row.sum() == 1
    laps.loc[row, column] = value


def make_race():
    """A race with exactly one known case for each rule.

    Driver A, stint 1 (laps 1-15): lap 1 = first lap, lap 8 = outlier (+5 s),
    lap 15 = in-lap  ->  12 clean laps remain.
    Driver A, stint 2 (laps 16-30): lap 16 = out-lap, lap 20 = not green,
    lap 22 = no lap time, lap 25 = no stint number, lap 27 = inaccurate,
    lap 29 = IsAccurate unknown (kept)  ->  10 clean laps remain.
    Driver B, stint 1 (laps 1-8): lap 1 = first lap; the other 7 laps form a
    stint shorter than 10 laps and are dropped.
    Total: 38 laps in, 22 laps out.
    """
    laps = pd.concat(
        [make_stint("A", 1, 1, 15), make_stint("A", 2, 16, 15), make_stint("B", 1, 1, 8)],
        ignore_index=True,
    )
    laps["IsAccurate"] = laps["IsAccurate"].astype(object)
    set_value(laps, "A", 8, "LapTime", 85.0)
    set_value(laps, "A", 15, "IsPitInLap", True)
    set_value(laps, "A", 16, "IsPitOutLap", True)
    set_value(laps, "A", 20, "IsGreenLap", False)
    set_value(laps, "A", 22, "LapTime", np.nan)
    set_value(laps, "A", 25, "Stint", np.nan)
    set_value(laps, "A", 27, "IsAccurate", False)
    set_value(laps, "A", 29, "IsAccurate", np.nan)
    return laps


# ---------------------------------------------------------------------------
# clean_laps: exact counts
# ---------------------------------------------------------------------------
def test_clean_laps_report_counts_are_exact():
    clean, report = clean_laps(make_race(), SETTINGS)
    expected = {
        "input": 0,
        "missing_lap_time": 1,
        "first_lap": 2,
        "pit_laps": 2,
        "not_green": 1,
        "inaccurate": 1,
        "missing_stint_info": 1,
        "outliers": 1,
        "short_stints": 7,
    }
    assert dict(zip(report["rule"], report["removed"])) == expected
    assert report["remaining"].iloc[0] == 38
    assert report["remaining"].iloc[-1] == 22
    assert len(clean) == 22


def test_clean_laps_report_order_and_consistency():
    clean, report = clean_laps(make_race(), SETTINGS)
    assert report["rule"].tolist() == ["input"] + list(RULE_ORDER)
    # Every removed lap is counted exactly once.
    assert report["removed"].sum() == report["remaining"].iloc[0] - len(clean)
    remaining = report["remaining"].to_numpy()
    assert np.all(remaining[1:] == remaining[:-1] - report["removed"].to_numpy()[1:])


def test_clean_laps_keeps_the_right_laps():
    clean, _ = clean_laps(make_race(), SETTINGS)
    a1 = clean[(clean.Driver == "A") & (clean.Stint == 1)]["LapNumber"].tolist()
    a2 = clean[(clean.Driver == "A") & (clean.Stint == 2)]["LapNumber"].tolist()
    assert a1 == [2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14]
    assert a2 == [17, 18, 19, 21, 23, 24, 26, 28, 29, 30]  # lap 29 (unknown accuracy) kept
    assert "B" not in set(clean["Driver"])
    assert list(clean.index) == list(range(len(clean)))


def test_clean_laps_does_not_modify_input():
    laps = make_race()
    before = laps.copy()
    clean_laps(laps, SETTINGS)
    pd.testing.assert_frame_equal(laps, before)


def test_clean_laps_without_isaccurate_column():
    laps = make_race().drop(columns=["IsAccurate"])
    _, report = clean_laps(laps, SETTINGS)
    removed = dict(zip(report["rule"], report["removed"]))
    assert removed["inaccurate"] == 0


def test_clean_laps_with_project_config():
    from tyredeg.config import load_config

    config = load_config("config.yaml")
    clean, report = clean_laps(make_race(), config)
    assert report["remaining"].iloc[-1] == len(clean)


# ---------------------------------------------------------------------------
# clean_laps: input validation
# ---------------------------------------------------------------------------
def test_clean_laps_rejects_bad_tables():
    with pytest.raises(TypeError):
        clean_laps("laps", SETTINGS)
    with pytest.raises(ValueError, match="empty"):
        clean_laps(make_race().iloc[0:0], SETTINGS)
    with pytest.raises(ValueError, match="TyreLife"):
        clean_laps(make_race().drop(columns=["TyreLife"]), SETTINGS)


@pytest.mark.parametrize(
    "settings, error",
    [
        (SimpleNamespace(outlier_k=None, min_stint_laps=10), ValueError),
        (SimpleNamespace(outlier_k=3.0, min_stint_laps=None), ValueError),
        (SimpleNamespace(outlier_k=0.0, min_stint_laps=10), ValueError),
        (SimpleNamespace(outlier_k=3.0, min_stint_laps=0), ValueError),
        (SimpleNamespace(outlier_k="3", min_stint_laps=10), TypeError),
        (SimpleNamespace(outlier_k=3.0, min_stint_laps=2.5), TypeError),
        (SimpleNamespace(outlier_k=3.0), TypeError),
    ],
)
def test_clean_laps_rejects_bad_settings(settings, error):
    with pytest.raises(error):
        clean_laps(make_race(), settings)


# ---------------------------------------------------------------------------
# Individual simple rules
# ---------------------------------------------------------------------------
def test_simple_rule_masks():
    laps = make_race()
    assert missing_lap_time_mask(laps).sum() == 1
    assert first_lap_mask(laps).sum() == 2
    assert pit_laps_mask(laps).sum() == 2
    assert not_green_mask(laps).sum() == 1
    assert missing_stint_info_mask(laps).sum() == 1


def test_inaccurate_mask_treats_unknown_as_accurate():
    laps = pd.DataFrame({"IsAccurate": [True, False, np.nan, None]})
    assert inaccurate_mask(laps).tolist() == [False, True, False, False]


def test_inaccurate_mask_without_column():
    assert inaccurate_mask(pd.DataFrame({"LapTime": [80.0, 81.0]})).tolist() == [False, False]


@pytest.mark.parametrize("column", ["Stint", "Compound", "TyreLife"])
def test_missing_stint_info_each_column(column):
    laps = make_stint("A", 1, 2, 3)
    laps[column] = laps[column].astype(object)
    laps.loc[1, column] = None
    assert missing_stint_info_mask(laps).tolist() == [False, True, False]


def test_short_stints_mask_boundary():
    laps = pd.concat([make_stint("A", 1, 2, 10), make_stint("B", 1, 2, 9)], ignore_index=True)
    mask = short_stints_mask(laps, 10)
    assert mask[laps.Driver == "A"].sum() == 0  # exactly 10 laps: kept
    assert mask[laps.Driver == "B"].sum() == 9  # 9 laps: dropped


def test_stints_are_separated_by_race():
    # Same driver and stint number in two races must count as two stints.
    laps = pd.concat(
        [make_stint("A", 1, 2, 6, race="r1"), make_stint("A", 1, 2, 6, race="r2")],
        ignore_index=True,
    )
    assert short_stints_mask(laps, 10).sum() == 12


# ---------------------------------------------------------------------------
# Theil-Sen line and outlier rule
# ---------------------------------------------------------------------------
def test_theil_sen_recovers_exact_line():
    x = np.arange(1, 11, dtype=float)
    intercept, slope = theil_sen_line(x, 80.0 + 0.07 * x)
    assert intercept == pytest.approx(80.0)
    assert slope == pytest.approx(0.07)


def test_theil_sen_ignores_a_large_outlier():
    x = np.arange(1, 11, dtype=float)
    y = 80.0 + 0.07 * x
    y[4] += 10.0
    intercept, slope = theil_sen_line(x, y)
    assert slope == pytest.approx(0.07)
    assert intercept == pytest.approx(80.0)


def test_theil_sen_matches_scipy_benchmark():
    rng = np.random.default_rng(42)  # seed recorded (rule 11)
    x = np.arange(1, 31, dtype=float)
    y = 80.0 + 0.05 * x + rng.normal(0.0, 0.4, x.size)
    y[[3, 17]] += [4.0, 6.0]
    intercept, slope = theil_sen_line(x, y)
    # scipy's "joint" intercept is median(y - slope * x), the same definition.
    reference = stats.theilslopes(y, x, method="joint")
    assert slope == pytest.approx(reference.slope, abs=1e-12)
    assert intercept == pytest.approx(reference.intercept, abs=1e-12)


def test_theil_sen_all_x_equal_gives_zero_slope():
    intercept, slope = theil_sen_line([5, 5, 5], [80.0, 81.0, 82.0])
    assert slope == 0.0
    assert intercept == 81.0


@pytest.mark.parametrize(
    "x, y",
    [([1], [80.0]), ([1, 2], [80.0]), ([1, 2, np.nan], [80.0, 81.0, 82.0]),
     ([[1, 2], [3, 4]], [[1, 2], [3, 4]])],
)
def test_theil_sen_rejects_bad_input(x, y):
    with pytest.raises(ValueError):
        theil_sen_line(x, y)


def test_outlier_rule_does_not_flag_ends_of_a_degrading_stint():
    # A 30-lap stint that slows by 0.1 s/lap (3 s in total). A rule based on the
    # flat stint median would call the first and last laps outliers; the
    # robust line follows the trend, so nothing is flagged.
    laps = make_stint("A", 1, 2, 30, slope=0.1)
    assert outliers_mask(laps, 3.0).sum() == 0


def test_outlier_rule_finds_planted_outliers_on_a_slope():
    laps = make_stint("A", 1, 2, 30, slope=0.1)
    laps.loc[[5, 20], "LapTime"] += [3.0, -2.0]  # one slow and one fast lap
    flagged = laps.index[outliers_mask(laps, 3.0)].tolist()
    assert flagged == [5, 20]


def test_outlier_threshold_controls_sensitivity():
    laps = make_stint("A", 1, 2, 30, slope=0.1)
    laps.loc[5, "LapTime"] += 0.6  # a moderately slow lap
    assert outliers_mask(laps, 3.0).sum() == 1
    assert outliers_mask(laps, 10.0).sum() == 0


def test_robust_flags_short_or_constant_stints():
    assert robust_outlier_flags([1, 2], [80.0, 90.0], 3.0).tolist() == [False, False]
    # Zero spread: no deviation can be judged, so nothing is flagged.
    assert not robust_outlier_flags([1, 2, 3, 4], [80.0, 80.0, 80.0, 90.0], 3.0).any()


@pytest.mark.parametrize("k, error", [(0, ValueError), (-1.0, ValueError), (np.inf, ValueError),
                                      ("3", TypeError), (True, TypeError)])
def test_robust_flags_reject_bad_k(k, error):
    with pytest.raises(error):
        robust_outlier_flags([1, 2, 3], [80.0, 80.1, 80.2], k)
