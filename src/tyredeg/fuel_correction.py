"""Fuel-effect removal and pit-loss estimation.

Fuel effect (DECISIONS.md D21, D22)
-----------------------------------
An F1 car starts the race with up to 110 kg of fuel and burns it as the race
goes on, so the car gets lighter and faster every lap. That speed-up works in
the opposite direction to tyre degradation, so it must be removed before
degradation can be measured.

**Assumption:** the same amount of fuel is burnt on every lap, so the fuel
load falls linearly with lap number. (In reality laps behind a safety car burn
less fuel; those laps are removed by cleaning anyway.) With ``k_fuel`` the
lap-time cost of carrying one lap's worth of fuel [s per lap of fuel], the
car on lap n is ``k_fuel * (n - 1)`` seconds faster than on lap 1, so

    corrected time = lap time + k_fuel * (lap number - 1)

is the time the lap would have taken with the full lap-1 fuel load (the
race-start reference, D21). Choosing another reference (e.g. the last lap)
only shifts every corrected time by the same constant, which does not change
any degradation slope.

Pit loss (D24)
--------------
The time lost by making a pit stop is estimated from real stops as

    loss = (in-lap time + out-lap time) - 2 x (driver's median clean lap time)

using fuel-corrected times for all three, so that a stop early in the race is
not compared with laps run on a much lighter car. Only stops whose in-lap and
out-lap are both green are used, because stops under a safety car lose less
time. The estimate is the median over all stops; the spread is the
interquartile range (IQR), i.e. the 25th to 75th percentile, which describes
the middle 50% of stops and is not distorted by a few badly delayed stops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FUEL_CORRECTED_COLUMN = "FuelCorrectedTime"


# ---------------------------------------------------------------------------
# Race length
# ---------------------------------------------------------------------------
def fill_total_laps(laps, total_laps_override=None):
    """Return a copy of ``laps`` with no missing ``TotalLaps`` values (D23).

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``RaceId``, ``LapNumber``, ``TotalLaps``).
    total_laps_override : int or None, optional
        If given (>= 2), every race gets this race length [laps].
        If None (default), races keep their value from the data and races
        without one (OpenF1) get the highest lap number completed in that
        race. This is correct unless a race was stopped early, which did not
        happen in the races used here.

    Returns
    -------
    pandas.DataFrame
        Copy of ``laps`` with ``TotalLaps`` filled in.

    Raises
    ------
    TypeError
        If ``laps`` is not a DataFrame or the override is not an int.
    ValueError
        If ``laps`` is empty, a column is missing, or the override is < 2.

    Example
    -------
    >>> df = pd.DataFrame({"RaceId": ["r", "r"], "LapNumber": [69.0, 70.0],
    ...                    "TotalLaps": [float("nan")] * 2})
    >>> fill_total_laps(df)["TotalLaps"].tolist()
    [70.0, 70.0]
    """
    # Validate the table and its required columns.
    if not isinstance(laps, pd.DataFrame):
        raise TypeError(f"laps must be a pandas DataFrame, got {type(laps).__name__}.")
    if laps.empty:
        raise ValueError("laps is empty.")
    for column in ("RaceId", "LapNumber", "TotalLaps"):
        if column not in laps.columns:
            raise ValueError(f"laps is missing column {column!r}.")

    # Work on a copy so the caller's table is not modified.
    result = laps.copy()
    # An override sets the same race length for every race.
    if total_laps_override is not None:
        if isinstance(total_laps_override, bool) or not isinstance(total_laps_override, int):
            raise TypeError(f"total_laps_override must be an int, got {total_laps_override!r}.")
        if total_laps_override < 2:
            raise ValueError(f"total_laps_override must be >= 2, got {total_laps_override}.")
        result["TotalLaps"] = float(total_laps_override)
        return result

    # Otherwise fill missing race lengths with the highest lap number seen in that race.
    highest_lap = result.groupby("RaceId")["LapNumber"].transform("max")
    missing = result["TotalLaps"].isna()
    for race_id in result.loc[missing, "RaceId"].unique():
        logger.info("TotalLaps missing for %s; using the highest lap number.", race_id)
    result.loc[missing, "TotalLaps"] = highest_lap[missing]
    return result


# ---------------------------------------------------------------------------
# Fuel correction
# ---------------------------------------------------------------------------
def _check_k_fuel(k_fuel):
    """Raise if ``k_fuel`` is not a finite number >= 0."""
    # k_fuel must be a finite number >= 0 (seconds per lap of fuel).
    if isinstance(k_fuel, bool) or not isinstance(k_fuel, (int, float, np.floating)):
        raise TypeError(f"k_fuel must be a number, got {k_fuel!r}.")
    if not np.isfinite(k_fuel) or k_fuel < 0:
        raise ValueError(f"k_fuel must be a finite number >= 0, got {k_fuel}.")


def fuel_corrected_time(lap_time, lap_number, total_laps, k_fuel):
    """Remove the fuel-mass effect from lap times (race-start reference, D21).

    ``corrected = lap_time + k_fuel * (lap_number - 1)``: the time the lap
    would have taken with the car still carrying its full lap-1 fuel load,
    assuming fuel load falls linearly with lap number.

    Parameters
    ----------
    lap_time : float or array_like
        Lap time(s) [s], finite and > 0.
    lap_number : float or array_like
        Lap number(s) in the race, whole numbers from 1 to ``total_laps``.
        Same shape as ``lap_time`` (or a scalar).
    total_laps : float or array_like
        Scheduled race length [laps], >= 1. Not needed by the formula itself
        with the race-start reference; it is used to reject impossible lap
        numbers (beyond the end of the race).
    k_fuel : float
        Lap-time cost of carrying one lap's worth of fuel [s per lap of
        fuel], >= 0 (config: 0.046, sensitivity range 0.015-0.070).

    Returns
    -------
    float or numpy.ndarray
        Fuel-corrected lap time(s) [s]; a float if all inputs are scalars.

    Raises
    ------
    TypeError
        If ``k_fuel`` is not a number.
    ValueError
        If any lap time is NaN/inf or <= 0, a lap number is not a whole
        number in [1, total_laps], ``total_laps`` < 1, shapes do not match,
        or ``k_fuel`` < 0.

    Example
    -------
    >>> fuel_corrected_time(80.0, lap_number=11, total_laps=70, k_fuel=0.05)
    80.5
    """
    # Check k_fuel and convert the inputs to float arrays.
    _check_k_fuel(k_fuel)
    lap_time = np.asarray(lap_time, dtype=float)
    lap_number = np.asarray(lap_number, dtype=float)
    total_laps = np.asarray(total_laps, dtype=float)

    # Broadcast scalars and arrays to a common shape, or explain why they do not fit.
    try:
        lap_time, lap_number, total_laps = np.broadcast_arrays(lap_time, lap_number, total_laps)
    except ValueError as error:
        raise ValueError(f"lap_time, lap_number and total_laps have incompatible shapes: {error}") from error

    # Lap times must be positive, lap numbers whole and between 1 and the race length.
    if not np.all(np.isfinite(lap_time)) or np.any(lap_time <= 0):
        raise ValueError("lap_time must be finite and > 0 (remove missing lap times first).")
    if not np.all(np.isfinite(total_laps)) or np.any(total_laps < 1):
        raise ValueError("total_laps must be finite and >= 1.")
    if not np.all(np.isfinite(lap_number)) or np.any(lap_number != np.round(lap_number)):
        raise ValueError("lap_number must contain whole numbers.")
    if np.any(lap_number < 1) or np.any(lap_number > total_laps):
        raise ValueError("lap_number must lie between 1 and total_laps.")

    # Correct each lap to the fuel load of lap 1: lap n carried (n - 1) laps less fuel.
    corrected = lap_time + k_fuel * (lap_number - 1.0)
    if corrected.ndim == 0:
        return float(corrected)
    return corrected


def add_fuel_corrected_times(laps, k_fuel):
    """Return a copy of ``laps`` with a ``FuelCorrectedTime`` column [s].

    Laps without a lap time keep NaN (so cleaning can still count them);
    every other lap is corrected with :func:`fuel_corrected_time`.

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table with ``LapTime``, ``LapNumber`` and a filled
        ``TotalLaps`` column (see :func:`fill_total_laps`).
    k_fuel : float
        Fuel coefficient [s per lap of fuel], >= 0.

    Returns
    -------
    pandas.DataFrame

    Raises
    ------
    TypeError, ValueError
        If ``laps`` is invalid, ``TotalLaps`` is missing for a timed lap, or
        :func:`fuel_corrected_time` rejects a value.

    Example
    -------
    >>> df = pd.DataFrame({"LapTime": [80.0, float("nan")], "LapNumber": [3.0, 4.0],
    ...                    "TotalLaps": [70.0, 70.0]})
    >>> add_fuel_corrected_times(df, 0.05)["FuelCorrectedTime"].tolist()
    [80.1, nan]
    """
    # Validate the table and its required columns.
    if not isinstance(laps, pd.DataFrame):
        raise TypeError(f"laps must be a pandas DataFrame, got {type(laps).__name__}.")
    if laps.empty:
        raise ValueError("laps is empty.")
    for column in ("LapTime", "LapNumber", "TotalLaps"):
        if column not in laps.columns:
            raise ValueError(f"laps is missing column {column!r}.")

    # Only laps with a lap time can be corrected, and those need a known race length.
    timed = laps["LapTime"].notna()
    if laps.loc[timed, "TotalLaps"].isna().any():
        raise ValueError("TotalLaps is missing for some laps; call fill_total_laps first.")

    # Add the column on a copy; laps without a time stay NaN.
    result = laps.copy()
    result[FUEL_CORRECTED_COLUMN] = np.nan
    if timed.any():
        result.loc[timed, FUEL_CORRECTED_COLUMN] = fuel_corrected_time(
            laps.loc[timed, "LapTime"].to_numpy(),
            laps.loc[timed, "LapNumber"].to_numpy(),
            laps.loc[timed, "TotalLaps"].to_numpy(),
            k_fuel,
        )
    return result


# ---------------------------------------------------------------------------
# Pit loss
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PitLossEstimate:
    """Result of :func:`estimate_pit_loss`.

    Attributes
    ----------
    median_s : float
        Median pit loss over all qualifying stops [s] (the estimate).
    q25_s, q75_s : float
        25th and 75th percentiles [s]; ``q75_s - q25_s`` is the IQR (spread).
    n_stops : int
        Number of stops used.
    stops : pandas.DataFrame
        One row per stop: RaceId, Driver, InLap, InLapTime, OutLapTime,
        MedianCleanTime and PitLoss (all times fuel-corrected, [s]).

    Example
    -------
    >>> estimate = PitLossEstimate(20.9, 19.8, 22.3, 105, pd.DataFrame())
    >>> round(estimate.iqr_s, 6)
    2.5
    """

    median_s: float
    q25_s: float
    q75_s: float
    n_stops: int
    stops: pd.DataFrame

    @property
    def iqr_s(self):
        """float: interquartile range q75 - q25 [s]."""
        # Interquartile range: the spread of the middle half of the stops.
        return self.q75_s - self.q25_s


def _driver_medians(clean_laps):
    """Return {(RaceId, Driver): median fuel-corrected clean lap time [s]}."""
    # Each driver's typical clean lap time in each race (fuel-corrected).
    medians = clean_laps.groupby(["RaceId", "Driver"])[FUEL_CORRECTED_COLUMN].median()
    return medians.to_dict()


def _find_green_stops(laps):
    """Return (in-lap row, out-lap row) pairs for stops on green-flag laps.

    A stop is an in-lap on lap n followed by an out-lap on lap n+1 of the same
    driver in the same race. Both laps need a time and must be green.
    """
    # Index every timed lap by (race, driver, lap) for quick lookup of the next lap.
    timed = laps[laps[FUEL_CORRECTED_COLUMN].notna()]
    by_lap = {}
    for row in timed.itertuples(index=False):
        by_lap[(row.RaceId, row.Driver, row.LapNumber)] = row

    # A stop is an in-lap followed directly by the matching out-lap.
    pairs = []
    for row in timed[timed["IsPitInLap"].astype(bool)].itertuples(index=False):
        out_lap = by_lap.get((row.RaceId, row.Driver, row.LapNumber + 1))
        if out_lap is None or not bool(out_lap.IsPitOutLap):
            continue
        # Keep only stops where both laps were green-flag (no safety car distortion).
        if bool(row.IsGreenLap) and bool(out_lap.IsGreenLap):
            pairs.append((row, out_lap))
    return pairs


def estimate_pit_loss(laps, clean_laps):
    """Estimate the time lost by a pit stop from real green-flag stops (D24).

    Pass only the races that may inform the result: before the test
    evaluation that means the training races only. The final strategy
    (after the test) deliberately uses 2023-2025 (D56, D58); it is never
    scored against the test race, so this is not leakage (audit check B9).

    Parameters
    ----------
    laps : pandas.DataFrame
        All laps (before cleaning) with ``FuelCorrectedTime`` (see
        :func:`add_fuel_corrected_times`) and the unified columns
        ``RaceId, Driver, LapNumber, IsPitInLap, IsPitOutLap, IsGreenLap``.
    clean_laps : pandas.DataFrame
        The same laps after :func:`tyredeg.cleaning.clean_laps` (all
        compounds); used for each driver's median clean lap time.

    Returns
    -------
    PitLossEstimate
        Median, 25th/75th percentiles (IQR), number of stops and a per-stop table.

    Raises
    ------
    TypeError
        If an input is not a DataFrame.
    ValueError
        If a required column is missing or no qualifying stop is found.

    Example
    -------
    >>> estimate = estimate_pit_loss(train_laps, train_clean)  # doctest: +SKIP
    >>> estimate.median_s, estimate.q25_s, estimate.q75_s  # doctest: +SKIP
    """
    # Validate both tables and their required columns.
    for name, table in (("laps", laps), ("clean_laps", clean_laps)):
        if not isinstance(table, pd.DataFrame):
            raise TypeError(f"{name} must be a pandas DataFrame, got {type(table).__name__}.")
    needed = ("RaceId", "Driver", "LapNumber", "IsPitInLap", "IsPitOutLap", "IsGreenLap",
              FUEL_CORRECTED_COLUMN)
    missing = [column for column in needed if column not in laps.columns]
    if missing:
        raise ValueError(f"laps is missing columns: {missing}")
    for column in ("RaceId", "Driver", FUEL_CORRECTED_COLUMN):
        if column not in clean_laps.columns:
            raise ValueError(f"clean_laps is missing column {column!r}.")

    # Reference pace: each driver's median clean lap in that race.
    medians = _driver_medians(clean_laps)
    rows = []
    # Pit loss of each stop = in-lap + out-lap - two typical laps of the same driver.
    for in_lap, out_lap in _find_green_stops(laps):
        median_time = medians.get((in_lap.RaceId, in_lap.Driver))
        if median_time is None:
            continue  # driver has no clean laps to compare with
        in_time = getattr(in_lap, FUEL_CORRECTED_COLUMN)
        out_time = getattr(out_lap, FUEL_CORRECTED_COLUMN)
        rows.append(
            {
                "RaceId": in_lap.RaceId,
                "Driver": in_lap.Driver,
                "InLap": in_lap.LapNumber,
                "InLapTime": in_time,
                "OutLapTime": out_time,
                "MedianCleanTime": median_time,
                "PitLoss": in_time + out_time - 2.0 * median_time,
            }
        )

    # Summarise all stops: median as the estimate, quartiles as the spread.
    if not rows:
        raise ValueError("No green-flag pit stops with clean reference laps were found.")
    stops = pd.DataFrame(rows)
    losses = stops["PitLoss"].to_numpy()
    # numpy's default percentile uses linear interpolation between data points.
    q25, median, q75 = np.percentile(losses, [25, 50, 75])
    return PitLossEstimate(
        median_s=float(median),
        q25_s=float(q25),
        q75_s=float(q75),
        n_stops=len(stops),
        stops=stops,
    )
