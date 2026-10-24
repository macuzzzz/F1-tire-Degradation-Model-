"""Offline tests for tyredeg.fuel_correction (fuel effect, race length, pit loss)."""

import numpy as np
import pandas as pd
import pytest

from tyredeg.fuel_correction import (
    PitLossEstimate,
    add_fuel_corrected_times,
    estimate_pit_loss,
    fill_total_laps,
    fuel_corrected_time,
)


# ---------------------------------------------------------------------------
# fuel_corrected_time
# ---------------------------------------------------------------------------
def test_scalar_correction_exact_value():
    # 80 s on lap 11 with 0.05 s per lap of fuel: 10 laps of fuel burnt -> +0.5 s.
    assert fuel_corrected_time(80.0, 11, 70, 0.05) == pytest.approx(80.5)


def test_lap_one_is_unchanged():
    assert fuel_corrected_time(80.0, 1, 70, 0.05) == 80.0


def test_zero_coefficient_changes_nothing():
    times = np.array([80.0, 81.0, 82.0])
    assert fuel_corrected_time(times, [5, 6, 7], 70, 0.0).tolist() == times.tolist()


def test_pure_fuel_effect_is_removed_exactly():
    # A car that only gets faster from burning fuel: t = 80 - k (n - 1).
    # After correction every lap must be exactly 80 s.
    k_fuel = 0.046
    lap_numbers = np.arange(1, 71, dtype=float)
    raw = 80.0 - k_fuel * (lap_numbers - 1)
    corrected = fuel_corrected_time(raw, lap_numbers, 70, k_fuel)
    np.testing.assert_allclose(corrected, 80.0, atol=1e-12)


def test_array_inputs_and_return_type():
    corrected = fuel_corrected_time([80.0, 80.0, 80.0], [1, 2, 3], [70, 70, 70], 0.1)
    assert isinstance(corrected, np.ndarray)
    np.testing.assert_allclose(corrected, [80.0, 80.1, 80.2])
    assert isinstance(fuel_corrected_time(80.0, 2, 70, 0.1), float)


@pytest.mark.parametrize(
    "lap_time, lap_number, total_laps, k_fuel, error",
    [
        (80.0, 0, 70, 0.05, ValueError),            # lap numbers start at 1
        (80.0, 71, 70, 0.05, ValueError),           # beyond the end of the race
        (80.0, 2.5, 70, 0.05, ValueError),          # not a whole lap
        (np.nan, 5, 70, 0.05, ValueError),          # missing lap time
        (-80.0, 5, 70, 0.05, ValueError),           # negative lap time
        (80.0, 5, 0, 0.05, ValueError),             # impossible race length
        (80.0, 5, 70, -0.01, ValueError),           # fuel cannot make the car faster
        (80.0, 5, 70, np.nan, ValueError),
        (80.0, 5, 70, "0.05", TypeError),
        ([80.0, 81.0], [1, 2, 3], 70, 0.05, ValueError),  # shape mismatch
    ],
)
def test_fuel_corrected_time_rejects_bad_input(lap_time, lap_number, total_laps, k_fuel, error):
    with pytest.raises(error):
        fuel_corrected_time(lap_time, lap_number, total_laps, k_fuel)


# ---------------------------------------------------------------------------
# fill_total_laps and add_fuel_corrected_times
# ---------------------------------------------------------------------------
def make_two_races():
    return pd.DataFrame(
        {
            "RaceId": ["fastf1_race", "fastf1_race", "openf1_race", "openf1_race"],
            "LapNumber": [1.0, 60.0, 1.0, 69.0],
            "TotalLaps": [70.0, 70.0, np.nan, np.nan],
            "LapTime": [90.0, 80.0, np.nan, 81.0],
        }
    )


def test_fill_total_laps_uses_highest_lap_only_when_missing():
    filled = fill_total_laps(make_two_races())
    # FastF1 race keeps its official 70 (even though lap 60 is the highest
    # here); the OpenF1 race gets its highest lap number, 69.
    assert filled["TotalLaps"].tolist() == [70.0, 70.0, 69.0, 69.0]


def test_fill_total_laps_override_wins():
    assert fill_total_laps(make_two_races(), 70)["TotalLaps"].tolist() == [70.0] * 4


@pytest.mark.parametrize("override, error", [(1, ValueError), (70.0, TypeError), (True, TypeError)])
def test_fill_total_laps_rejects_bad_override(override, error):
    with pytest.raises(error):
        fill_total_laps(make_two_races(), override)


def test_fill_total_laps_rejects_bad_table():
    with pytest.raises(TypeError):
        fill_total_laps([1, 2])
    with pytest.raises(ValueError):
        fill_total_laps(make_two_races().drop(columns=["TotalLaps"]))


def test_add_fuel_corrected_times_keeps_missing_as_nan():
    result = add_fuel_corrected_times(fill_total_laps(make_two_races()), 0.05)
    corrected = result["FuelCorrectedTime"].tolist()
    assert corrected[0] == pytest.approx(90.0)          # lap 1
    assert corrected[1] == pytest.approx(80.0 + 0.05 * 59)
    assert np.isnan(corrected[2])                        # no lap time
    assert corrected[3] == pytest.approx(81.0 + 0.05 * 68)
    assert "FuelCorrectedTime" not in make_two_races().columns  # input untouched


def test_add_fuel_corrected_times_needs_total_laps():
    with pytest.raises(ValueError, match="fill_total_laps"):
        add_fuel_corrected_times(make_two_races(), 0.05)


# ---------------------------------------------------------------------------
# estimate_pit_loss
# ---------------------------------------------------------------------------
def lap(driver, lap_number, time, pit_in=False, pit_out=False, green=True, race="r1"):
    return {
        "RaceId": race, "Driver": driver, "LapNumber": float(lap_number),
        "FuelCorrectedTime": time, "IsPitInLap": pit_in, "IsPitOutLap": pit_out,
        "IsGreenLap": green,
    }


def make_pit_scenario():
    """All laps and clean laps for five drivers with known pit losses.

    Clean laps: A, B, C and D have a median of exactly 80 s; E has none.
    A: in 92 + out 90  -> loss 22 s
    B: in 93 + out 91  -> loss 24 s
    C: in 91 + out 89  -> loss 20 s
    D: stop with the in-lap under safety car -> excluded
    E: stop but no clean laps to compare with -> excluded
    F: in-lap but no out-lap (retired in the pits) -> excluded
    """
    clean = []
    for driver in "ABCD":
        clean += [lap(driver, n, t) for n, t in [(2, 79.5), (3, 80.0), (4, 80.5)]]
    all_laps = list(clean)
    all_laps += [lap("A", 10, 92.0, pit_in=True), lap("A", 11, 90.0, pit_out=True)]
    all_laps += [lap("B", 12, 93.0, pit_in=True), lap("B", 13, 91.0, pit_out=True)]
    all_laps += [lap("C", 14, 91.0, pit_in=True), lap("C", 15, 89.0, pit_out=True)]
    all_laps += [lap("D", 16, 100.0, pit_in=True, green=False), lap("D", 17, 95.0, pit_out=True)]
    all_laps += [lap("E", 10, 92.0, pit_in=True), lap("E", 11, 90.0, pit_out=True)]
    all_laps += [lap("F", 10, 92.0, pit_in=True)]
    return pd.DataFrame(all_laps), pd.DataFrame(clean)


def test_pit_loss_exact_values():
    all_laps, clean = make_pit_scenario()
    estimate = estimate_pit_loss(all_laps, clean)
    assert isinstance(estimate, PitLossEstimate)
    assert estimate.n_stops == 3
    assert sorted(estimate.stops["PitLoss"]) == pytest.approx([20.0, 22.0, 24.0])
    assert estimate.median_s == pytest.approx(22.0)
    # Linear interpolation: 25th percentile of [20, 22, 24] = 21, 75th = 23.
    assert estimate.q25_s == pytest.approx(21.0)
    assert estimate.q75_s == pytest.approx(23.0)
    assert estimate.iqr_s == pytest.approx(2.0)


def test_pit_loss_compares_within_the_same_race():
    # Same driver code in a second race with a different median lap time.
    all_laps, clean = make_pit_scenario()
    other_clean = [lap("A", n, 70.0, race="r2") for n in (2, 3, 4)]
    other_stop = [lap("A", 10, 85.0, pit_in=True, race="r2"),
                  lap("A", 11, 81.0, pit_out=True, race="r2")]
    all_laps = pd.concat([all_laps, pd.DataFrame(other_clean + other_stop)], ignore_index=True)
    clean = pd.concat([clean, pd.DataFrame(other_clean)], ignore_index=True)
    stops = estimate_pit_loss(all_laps, clean).stops
    r2 = stops[stops["RaceId"] == "r2"]
    assert r2["PitLoss"].tolist() == pytest.approx([85.0 + 81.0 - 140.0])


def test_pit_loss_without_qualifying_stops_raises():
    all_laps, clean = make_pit_scenario()
    no_stops = all_laps[~all_laps["IsPitInLap"]]
    with pytest.raises(ValueError, match="No green-flag pit stops"):
        estimate_pit_loss(no_stops, clean)


def test_pit_loss_rejects_bad_input():
    all_laps, clean = make_pit_scenario()
    with pytest.raises(TypeError):
        estimate_pit_loss("laps", clean)
    with pytest.raises(ValueError, match="FuelCorrectedTime"):
        estimate_pit_loss(all_laps.drop(columns=["FuelCorrectedTime"]), clean)
    with pytest.raises(ValueError):
        estimate_pit_loss(all_laps, clean.drop(columns=["Driver"]))
