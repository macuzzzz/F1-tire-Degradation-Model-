"""Tests for the independent checks in scripts/audit.py (D89-D90). Offline, synthetic."""

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit  # noqa: E402
from tyredeg.models.polynomial import PolynomialDegradationModel  # noqa: E402
from tyredeg.strategy import CompoundModel, LinearDegradation, optimise_brute_force, optimise_two_stop  # noqa: E402


def models():
    return {"C3": CompoundModel("C3", LinearDegradation(0.06), 85.0, 40),
            "C4": CompoundModel("C4", LinearDegradation(0.055), 84.9, 35)}


def test_stint_table_is_the_sum_of_lap_times_and_marks_long_stints_infeasible():
    table = audit.stint_time_table(models(), 70)
    assert table["C3"][2] == pytest.approx(2 * 85.0 + 0.06 * (1 + 2))
    assert np.isinf(table["C4"][36])          # longer than the 35-lap limit


@pytest.mark.parametrize("stops", [1, 2])
def test_exhaustive_search_agrees_with_the_optimisers(stops):
    fuel_total = 0.046 * 70 * 69 / 2
    table = audit.stint_time_table(models(), 70)
    time, sequence, lengths = audit.best_by_enumeration(table, ["C3", "C4"], 70, stops, 20.9, fuel_total)
    if stops == 1:
        best = min(optimise_brute_force(a, b, models(), 70, 20.9, 0.046).total_time
                   for a, b in (("C3", "C4"), ("C4", "C3")))
    else:
        sequences = [s for s in product(["C3", "C4"], repeat=3) if len(set(s)) == 2]
        best = min(optimise_two_stop(list(s), models(), 70, 20.9, 0.046).total_time for s in sequences)
    assert time == pytest.approx(best, abs=1e-9)
    assert sum(lengths) == 70 and len(set(sequence)) == 2


def test_rate_change_explains_the_whole_bias_without_noise():
    # Two noise-free stints whose true slope is 0.04, predicted with slope 0.07.
    ages = np.tile(np.arange(1.0, 21.0), 2)
    stints = np.repeat(["s1", "s2"], 20)
    laps = pd.DataFrame({"StintId": stints, "LapNumber": ages, "TyreLife": ages,
                         "FuelCorrectedTime": 80.0 + 0.04 * ages + np.where(stints == "s2", 1.0, 0.0)})
    true_model = PolynomialDegradationModel("C3").fit(ages, laps["FuelCorrectedTime"], stints)
    train_model = LinearDegradation(0.07)
    anchors = laps.groupby("StintId").head(3)
    scored = laps.drop(anchors.index)
    expected = audit.wear_rate_bias(train_model, true_model, laps, scored, 3)
    # Error per lap = (0.07 - 0.04) x (age - mean anchor age 2); mean over ages 4..20 = 0.03 x 10.
    assert expected == pytest.approx(0.03 * (np.mean(np.arange(4.0, 21.0)) - 2.0))
    assert audit.anchor_lap_residual(true_model, laps, 3) == pytest.approx(0.0, abs=1e-9)
