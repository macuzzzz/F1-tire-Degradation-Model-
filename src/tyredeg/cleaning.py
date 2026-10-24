"""Lap filtering rules: keep only laps that reflect tyre degradation.

A raw race lap time is affected by many things besides tyre wear: pit stops,
safety cars, the standing start, traffic and driver mistakes. This module
removes the laps where such effects dominate, so the remaining laps can be
used to fit degradation models.

How the cleaning works
----------------------
:func:`clean_laps` applies the rules below **in this order**. Each rule only
looks at the laps still remaining after the earlier rules, and each removed
lap is counted under the *first* rule that removed it, so the counts in the
report add up exactly to the total number of laps removed (DECISIONS.md D17).

====  ==================  ===================================================
Step  Rule                Removes ...
====  ==================  ===================================================
1     missing_lap_time    laps with no lap time (NaN)
2     first_lap           lap 1 (standing start: much slower, not tyre-related)
3     pit_laps            in-laps and out-laps (time lost in the pit lane)
4     not_green           laps with a yellow flag, SC, VSC or red flag (D18)
5     inaccurate          laps FastF1 flags as inaccurate (FastF1 data only)
6     missing_stint_info  laps with no stint number, compound or tyre age
7     outliers            unusually slow/fast laps within a stint (D19)
8     short_stints        whole stints with < min_stint_laps laps left (D20)
====  ==================  ===================================================

Laps deleted for track limits are deliberately **kept** (D18): the time was
really driven, and OpenF1 has no such flag, so removing them would clean the
two data sources differently.

Each rule is a small function ``<rule>_mask(laps, ...)`` that returns a
boolean Series which is ``True`` for the laps the rule removes. This keeps
every rule testable and explainable on its own.

The outlier rule is run on the **raw** lap times (not fuel-corrected ones), so
the set of clean laps does not change when the fuel coefficient is varied in
the sensitivity analysis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Columns every rule set needs. `IsAccurate` is optional (FastF1 only).
REQUIRED_COLUMNS = (
    "RaceId",
    "Driver",
    "LapNumber",
    "LapTime",
    "Stint",
    "Compound",
    "TyreLife",
    "IsPitInLap",
    "IsPitOutLap",
    "IsGreenLap",
)

# A stint is identified by race, driver and stint number. Lap numbers restart
# in every race, so RaceId must be part of the key.
STINT_KEY = ["RaceId", "Driver", "Stint"]

# For normally distributed data the median absolute deviation (MAD) is
# 0.6745 standard deviations; multiplying by 1/0.6745 = 1.4826 turns the MAD
# into an estimate of the standard deviation. This is a mathematical constant,
# not a tuning choice, so it lives here rather than in config.yaml.
MAD_TO_STD = 1.4826

# The outlier rule needs at least 3 laps: 2 points always lie exactly on a
# line, which would make the spread zero.
MIN_LAPS_FOR_OUTLIER_TEST = 3

RULE_ORDER = (
    "missing_lap_time",
    "first_lap",
    "pit_laps",
    "not_green",
    "inaccurate",
    "missing_stint_info",
    "outliers",
    "short_stints",
)


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------
def _check_laps(laps):
    """Raise if ``laps`` is not a non-empty DataFrame with the required columns."""
    if not isinstance(laps, pd.DataFrame):
        raise TypeError(f"laps must be a pandas DataFrame, got {type(laps).__name__}.")
    if laps.empty:
        raise ValueError("laps is empty; there is nothing to clean.")
    missing = [column for column in REQUIRED_COLUMNS if column not in laps.columns]
    if missing:
        raise ValueError(f"laps is missing required columns: {missing}")


def _check_outlier_k(outlier_k):
    """Raise if ``outlier_k`` is not a positive number."""
    if isinstance(outlier_k, bool) or not isinstance(outlier_k, (int, float)):
        raise TypeError(f"outlier_k must be a number, got {outlier_k!r}.")
    if not np.isfinite(outlier_k) or outlier_k <= 0:
        raise ValueError(f"outlier_k must be a finite number > 0, got {outlier_k}.")


def _check_min_stint_laps(min_stint_laps):
    """Raise if ``min_stint_laps`` is not an integer >= 1."""
    if isinstance(min_stint_laps, bool) or not isinstance(min_stint_laps, (int, np.integer)):
        raise TypeError(f"min_stint_laps must be an integer, got {min_stint_laps!r}.")
    if min_stint_laps < 1:
        raise ValueError(f"min_stint_laps must be >= 1, got {min_stint_laps}.")


# ---------------------------------------------------------------------------
# Rules 1-6: simple lap-by-lap rules
# ---------------------------------------------------------------------------
def missing_lap_time_mask(laps):
    """Return True for laps without a lap time.

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``LapTime`` [s]).

    Returns
    -------
    pandas.Series of bool
        True where ``LapTime`` is NaN.

    Example
    -------
    >>> missing_lap_time_mask(pd.DataFrame({"LapTime": [80.0, float("nan")]})).tolist()
    [False, True]
    """
    return laps["LapTime"].isna()


def first_lap_mask(laps):
    """Return True for lap 1 of the race.

    The first lap starts from a standstill and is run in a tight pack, so it
    is several seconds slower for reasons that have nothing to do with tyres.

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``LapNumber``).

    Returns
    -------
    pandas.Series of bool

    Example
    -------
    >>> first_lap_mask(pd.DataFrame({"LapNumber": [1.0, 2.0]})).tolist()
    [True, False]
    """
    return laps["LapNumber"] == 1


def pit_laps_mask(laps):
    """Return True for in-laps and out-laps.

    These laps include time spent driving through the pit lane, which is
    analysed separately as the pit loss (see :mod:`tyredeg.fuel_correction`).

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``IsPitInLap`` and ``IsPitOutLap``).

    Returns
    -------
    pandas.Series of bool

    Example
    -------
    >>> df = pd.DataFrame({"IsPitInLap": [False, True, False],
    ...                    "IsPitOutLap": [False, False, True]})
    >>> pit_laps_mask(df).tolist()
    [False, True, True]
    """
    return laps["IsPitInLap"].astype(bool) | laps["IsPitOutLap"].astype(bool)


def not_green_mask(laps):
    """Return True for laps not run fully under green flag (D18).

    ``IsGreenLap`` is set by the loaders: for FastF1 data, the lap's track
    status contains only code "1" (all clear); codes "2" yellow, "4" safety
    car, "5" red flag, "6" VSC deployed and "7" VSC ending make it not green.
    For OpenF1 data the same is rebuilt from race-control messages.

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``IsGreenLap``).

    Returns
    -------
    pandas.Series of bool

    Example
    -------
    >>> not_green_mask(pd.DataFrame({"IsGreenLap": [True, False]})).tolist()
    [False, True]
    """
    return ~laps["IsGreenLap"].astype(bool)


def inaccurate_mask(laps):
    """Return True for laps that FastF1 explicitly flags as inaccurate.

    Only FastF1 provides ``IsAccurate``. When FastF1 and OpenF1 races are
    combined, OpenF1 rows have no value (NaN). "Unknown" is not evidence of a
    bad lap, so only laps flagged exactly ``False`` are removed.

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table; ``IsAccurate`` is optional.

    Returns
    -------
    pandas.Series of bool
        All False if the column is absent.

    Example
    -------
    >>> df = pd.DataFrame({"IsAccurate": [True, False, None]})
    >>> inaccurate_mask(df).tolist()
    [False, True, False]
    """
    if "IsAccurate" not in laps.columns:
        return pd.Series(False, index=laps.index)
    # Element-wise comparison: True == False and NaN == False both give False,
    # so only an explicit False flag removes a lap.
    return laps["IsAccurate"].eq(False)


def missing_stint_info_mask(laps):
    """Return True for laps with no stint number, compound or tyre age.

    Without these a lap cannot be assigned to a stint or a tyre age, so it
    cannot be used for degradation modelling (seen for 1-3 laps per OpenF1 race).

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``Stint``, ``Compound``, ``TyreLife``).

    Returns
    -------
    pandas.Series of bool

    Example
    -------
    >>> df = pd.DataFrame({"Stint": [1.0, None], "Compound": ["HARD", "HARD"],
    ...                    "TyreLife": [3.0, 4.0]})
    >>> missing_stint_info_mask(df).tolist()
    [False, True]
    """
    return laps["Stint"].isna() | laps["Compound"].isna() | laps["TyreLife"].isna()


# ---------------------------------------------------------------------------
# Rule 7: outliers within a stint (robust line + MAD)
# ---------------------------------------------------------------------------
def theil_sen_line(x, y):
    """Fit a straight line ``y = intercept + slope * x`` that resists outliers.

    The Theil-Sen estimator takes the slope as the **median of the slopes of
    all pairs of points**, and the intercept as the median of
    ``y - slope * x``. Because medians ignore extreme values, a few bad laps
    barely move the line (up to ~29% of the points can be outliers), unlike an
    ordinary least-squares fit, which a single very slow lap can tilt.

    Parameters
    ----------
    x : array_like
        Explanatory values, e.g. tyre age [laps]. 1-D, at least 2 values,
        no NaN.
    y : array_like
        Responses, e.g. lap time [s]. Same length as ``x``, no NaN.

    Returns
    -------
    intercept : float
        Line value at ``x = 0`` (same unit as ``y``).
    slope : float
        Change of ``y`` per unit ``x`` (e.g. s per lap). 0.0 if all ``x`` are equal.

    Raises
    ------
    ValueError
        If the inputs are not 1-D, differ in length, have fewer than 2
        values, or contain NaN/inf.

    Example
    -------
    >>> intercept, slope = theil_sen_line([1, 2, 3, 4, 5], [80.0, 80.1, 80.2, 95.0, 80.4])
    >>> round(intercept, 3), round(slope, 3)
    (79.9, 0.1)
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1:
        raise ValueError("x and y must be 1-D arrays.")
    if x.size != y.size:
        raise ValueError(f"x and y must have the same length, got {x.size} and {y.size}.")
    if x.size < 2:
        raise ValueError("At least 2 points are needed to fit a line.")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("x and y must not contain NaN or infinite values.")

    # All pairs (i, j) with i < j: np.triu_indices gives their row/column indices.
    i, j = np.triu_indices(x.size, k=1)
    dx = x[j] - x[i]
    dy = y[j] - y[i]
    # Pairs with the same x have no defined slope, so they are skipped.
    usable = dx != 0
    if np.any(usable):
        slope = float(np.median(dy[usable] / dx[usable]))
    else:
        slope = 0.0
    intercept = float(np.median(y - slope * x))
    return intercept, slope


def robust_outlier_flags(x, y, outlier_k):
    """Flag points that lie far from a robust line through the data.

    Steps:

    1. fit a Theil-Sen line (:func:`theil_sen_line`) - this follows the
       genuine upward trend of lap time with tyre age, so laps at the start
       and end of a long stint are not mistaken for outliers;
    2. residual r = y - line value;
    3. robust spread s = 1.4826 x median(|r - median(r)|)  (MAD scaled to a
       standard deviation);
    4. flag points with |r - median(r)| > outlier_k x s.

    Parameters
    ----------
    x : array_like
        Tyre age [laps] of each lap in one stint.
    y : array_like
        Lap time [s] of each lap. Same length as ``x``.
    outlier_k : float
        Threshold in robust standard deviations, > 0 (config: 3.0, D19).

    Returns
    -------
    numpy.ndarray of bool
        True for outliers. All False if there are fewer than 3 points, or if
        the spread s is 0 (then no deviation can be judged "large"; dividing
        by zero is avoided).

    Raises
    ------
    TypeError, ValueError
        If ``outlier_k`` is invalid, or ``x``/``y`` are invalid (see
        :func:`theil_sen_line`).

    Example
    -------
    >>> flags = robust_outlier_flags([1, 2, 3, 4, 5, 6], [80.0, 80.2, 79.9, 85.0, 80.1, 80.3], 3.0)
    >>> flags.tolist()
    [False, False, False, True, False, False]
    """
    _check_outlier_k(outlier_k)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < MIN_LAPS_FOR_OUTLIER_TEST:
        return np.zeros(x.size, dtype=bool)

    intercept, slope = theil_sen_line(x, y)
    residuals = y - (intercept + slope * x)
    deviations = np.abs(residuals - np.median(residuals))
    spread = MAD_TO_STD * np.median(deviations)
    if spread == 0:
        return np.zeros(x.size, dtype=bool)
    return deviations > outlier_k * spread


def outliers_mask(laps, outlier_k):
    """Return True for outlier laps, judged separately within each stint (D19).

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table with valid ``LapTime`` [s], ``TyreLife`` [laps]
        and stint columns (run rules 1-6 first).
    outlier_k : float
        Threshold in robust standard deviations, > 0.

    Returns
    -------
    pandas.Series of bool

    Raises
    ------
    TypeError, ValueError
        If ``outlier_k`` is invalid or a lap time / tyre age is NaN.

    Example
    -------
    >>> mask = outliers_mask(laps_after_rules_1_to_6, outlier_k=3.0)  # doctest: +SKIP
    """
    _check_outlier_k(outlier_k)
    flags = pd.Series(False, index=laps.index)
    for _, stint in laps.groupby(STINT_KEY, sort=False):
        stint_flags = robust_outlier_flags(stint["TyreLife"], stint["LapTime"], outlier_k)
        flags.loc[stint.index] = stint_flags
    return flags


# ---------------------------------------------------------------------------
# Rule 8: short stints
# ---------------------------------------------------------------------------
def short_stints_mask(laps, min_stint_laps):
    """Return True for every lap of a stint with fewer than ``min_stint_laps`` laps (D20).

    A stint needs enough laps to estimate its own base lap time and
    degradation trend; very short stints mostly add noise.

    Parameters
    ----------
    laps : pandas.DataFrame
        Laps remaining after the other rules (needs the stint key columns).
    min_stint_laps : int
        Minimum number of laps a stint must keep, >= 1 (config: 10).

    Returns
    -------
    pandas.Series of bool

    Raises
    ------
    TypeError, ValueError
        If ``min_stint_laps`` is not an integer >= 1.

    Example
    -------
    >>> df = pd.DataFrame({"RaceId": ["r"] * 3, "Driver": ["A", "A", "B"],
    ...                    "Stint": [1.0, 1.0, 1.0]})
    >>> short_stints_mask(df, 2).tolist()
    [False, False, True]
    """
    _check_min_stint_laps(min_stint_laps)
    # transform("size") gives every lap the size of its own stint.
    stint_sizes = laps.groupby(STINT_KEY, sort=False)["Stint"].transform("size")
    return stint_sizes < min_stint_laps


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
def _read_settings(config):
    """Return (outlier_k, min_stint_laps) from a Config-like object."""
    for name in ("outlier_k", "min_stint_laps"):
        if not hasattr(config, name):
            raise TypeError(f"config must have an attribute '{name}'.")
        if getattr(config, name) is None:
            raise ValueError(f"config.{name} is not set; set cleaning.{name} in config.yaml.")
    _check_outlier_k(config.outlier_k)
    _check_min_stint_laps(config.min_stint_laps)
    return config.outlier_k, config.min_stint_laps


def clean_laps(laps, config):
    """Apply all cleaning rules in order and report how many laps each removed.

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (see :mod:`tyredeg.loading_common`), any number of
        races, drivers and compounds.
    config : Config
        The project configuration (or any object with the attributes
        ``outlier_k`` > 0 and ``min_stint_laps`` >= 1).

    Returns
    -------
    clean : pandas.DataFrame
        The laps that passed every rule, original column order, index 0..N-1.
    report : pandas.DataFrame
        One row per rule in the order applied, with columns ``rule``,
        ``removed`` (laps removed by that rule) and ``remaining`` (laps left
        afterwards). The first row (``rule == "input"``) holds the input size.

    Raises
    ------
    TypeError
        If ``laps`` is not a DataFrame or ``config`` lacks a setting.
    ValueError
        If ``laps`` is empty or lacks a required column, or a setting is
        missing/out of range.

    Example
    -------
    >>> clean, report = clean_laps(laps, load_config("config.yaml"))  # doctest: +SKIP
    >>> report  # doctest: +SKIP
    """
    _check_laps(laps)
    outlier_k, min_stint_laps = _read_settings(config)

    rules = {
        "missing_lap_time": missing_lap_time_mask,
        "first_lap": first_lap_mask,
        "pit_laps": pit_laps_mask,
        "not_green": not_green_mask,
        "inaccurate": inaccurate_mask,
        "missing_stint_info": missing_stint_info_mask,
        "outliers": lambda remaining: outliers_mask(remaining, outlier_k),
        "short_stints": lambda remaining: short_stints_mask(remaining, min_stint_laps),
    }

    remaining = laps
    rows = [{"rule": "input", "removed": 0, "remaining": len(laps)}]
    for name in RULE_ORDER:
        remove = rules[name](remaining)
        remaining = remaining[~remove]
        rows.append({"rule": name, "removed": int(remove.sum()), "remaining": len(remaining)})

    report = pd.DataFrame(rows)
    return remaining.reset_index(drop=True), report
