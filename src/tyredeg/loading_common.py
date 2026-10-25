"""Pieces shared by the FastF1 and OpenF1 loaders.

The project gets lap data from two free sources (DECISIONS.md, D14):

- FastF1 for 2022 (from FastF1's free mirror),
- the OpenF1 web API for 2023 onward.

The two sources describe the same things in different ways. Both loaders
therefore convert their data into ONE common table, the "unified laps table"
(D16), and use the same exceptions and input checks defined here. Later
modules (cleaning, models, ...) only ever see the unified table, so they do
not need to know where the data came from.

Unified laps table
------------------
=================  =======  ===================================================
Column             Type     Meaning
=================  =======  ===================================================
Year               int      Championship season.
EventName          str      Official event name, e.g. "Hungarian Grand Prix".
RaceId             str      Unique race label, e.g. "2023_hungarian_grand_prix".
TotalLaps          float    Scheduled race length [laps]; NaN if the source
                            does not provide it.
Source             str      "fastf1" or "openf1".
Driver             str      Three-letter driver code, e.g. "VER".
DriverNumber       str      Car number as text, e.g. "1".
Team               str      Team name, e.g. "Red Bull Racing".
LapNumber          float    Lap of the race (1 = first lap). Whole numbers.
LapTime            float    Lap time [s]; NaN if the source has no time.
Stint              float    Stint counter for the driver (1 = first stint).
Compound           str      Relative label: "SOFT", "MEDIUM", "HARD",
                            "INTERMEDIATE" or "WET" (None if unknown).
TyreLife           float    Laps completed on this tyre set by the END of
                            this lap, including laps from earlier sessions.
IsPitInLap         bool     True if the car entered the pit lane this lap.
IsPitOutLap        bool     True if the car started this lap in the pit lane.
IsGreenLap         bool     True if no yellow flag, safety car, virtual
                            safety car or red flag was active during the lap.
=================  =======  ===================================================

Source-specific extra columns (kept when available, otherwise absent):
``FreshTyre``, ``TrackStatus``, ``IsAccurate``, ``Deleted``,
``FastF1Generated`` (FastF1 only).

The column ``PirelliCompound`` (e.g. "C3") is added afterwards by
:mod:`tyredeg.tyre_allocation`.
"""

from __future__ import annotations

import re

import pandas as pd

from tyredeg.config import FIRST_SUPPORTED_YEAR, SUPPORTED_SESSIONS

# Order of the columns every loader must produce.
UNIFIED_COLUMNS = (
    "Year",
    "EventName",
    "RaceId",
    "TotalLaps",
    "Source",
    "Driver",
    "DriverNumber",
    "Team",
    "LapNumber",
    "LapTime",
    "Stint",
    "Compound",
    "TyreLife",
    "IsPitInLap",
    "IsPitOutLap",
    "IsGreenLap",
)

# Columns that only FastF1 provides; kept at the end of the table when present.
OPTIONAL_COLUMNS = ("FreshTyre", "TrackStatus", "IsAccurate", "Deleted", "FastF1Generated")

BOOLEAN_COLUMNS = ("IsPitInLap", "IsPitOutLap", "IsGreenLap")
FLOAT_COLUMNS = ("TotalLaps", "LapNumber", "LapTime", "Stint", "TyreLife")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class RaceNotFoundError(ValueError):
    """The requested event does not exist, or the source matched a different event.

    Subclasses ``ValueError`` because the cause is a bad input (the event name).

    Example
    -------
    >>> issubclass(RaceNotFoundError, ValueError)
    True
    """


class RaceDataUnavailableError(RuntimeError):
    """The event exists but its lap data could not be downloaded or is unusable.

    Subclasses ``RuntimeError`` because the cause is outside the caller's
    control (network, missing data on the server, access restrictions, ...).

    Example
    -------
    >>> issubclass(RaceDataUnavailableError, RuntimeError)
    True
    """


# ---------------------------------------------------------------------------
# Input checks
# ---------------------------------------------------------------------------
def validate_year(year):
    """Raise if ``year`` is not an int season with lap timing data (>= 2018).

    Parameters
    ----------
    year : int
        Championship season, >= 2018.

    Raises
    ------
    TypeError
        If ``year`` is not an int (``bool`` is rejected explicitly because
        ``True`` is an ``int`` in Python).
    ValueError
        If ``year`` is earlier than 2018.

    Example
    -------
    >>> validate_year(2023)          # valid: returns None
    >>> validate_year(2010)
    Traceback (most recent call last):
    ...
    ValueError: year must be >= 2018 (no lap timing data before then), got 2010.
    """
    # Booleans are rejected explicitly because True is also an int in Python.
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError(f"year must be an int, got {year!r}.")
    if year < FIRST_SUPPORTED_YEAR:
        raise ValueError(
            f"year must be >= {FIRST_SUPPORTED_YEAR} (no lap timing data before "
            f"then), got {year}."
        )


def validate_event(event):
    """Raise if ``event`` is not a non-empty string.

    Parameters
    ----------
    event : str
        Event name, e.g. ``"Hungarian Grand Prix"``.

    Raises
    ------
    TypeError
        If ``event`` is not a string.
    ValueError
        If ``event`` is empty or only spaces.

    Example
    -------
    >>> validate_event("Hungarian Grand Prix")   # valid: returns None
    >>> validate_event("  ")
    Traceback (most recent call last):
    ...
    ValueError: event must not be empty.
    """
    # The event name must be a non-empty string.
    if not isinstance(event, str):
        raise TypeError(f"event must be a str, got {type(event).__name__}.")
    if event.strip() == "":
        raise ValueError("event must not be empty.")


def validate_session(session):
    """Raise if ``session`` is not a supported session identifier.

    Parameters
    ----------
    session : str
        Session identifier; only ``"R"`` (race) is supported.

    Raises
    ------
    ValueError
        If ``session`` is anything other than ``"R"``.

    Example
    -------
    >>> validate_session("R")   # valid: returns None
    >>> validate_session("Q")
    Traceback (most recent call last):
    ...
    ValueError: session must be one of ('R',), got 'Q'.
    """
    # Only race sessions ("R") are supported.
    if session not in SUPPORTED_SESSIONS:
        raise ValueError(f"session must be one of {SUPPORTED_SESSIONS}, got {session!r}.")


def check_event_name(returned_event, requested_event):
    """Return the official event name, or raise if it differs from the request.

    FastF1 fuzzy-matches event names: during development the request
    "Atlantis Grand Prix" silently returned the *Australian* Grand Prix. A
    typo in config.yaml could therefore load the wrong race without any
    error, so an exact (case-insensitive) match is required. See D7.

    Parameters
    ----------
    returned_event : str
        Event name reported by the data source.
    requested_event : str
        Event name the caller asked for.

    Returns
    -------
    str
        ``returned_event`` (the official spelling).

    Raises
    ------
    RaceNotFoundError
        If the two names differ (ignoring case and surrounding spaces).

    Example
    -------
    >>> check_event_name("Hungarian Grand Prix", "hungarian grand prix")
    'Hungarian Grand Prix'
    """
    # Compare names ignoring case and spaces; a mismatch means the source picked another race.
    returned_event = str(returned_event)
    if returned_event.strip().casefold() != requested_event.strip().casefold():
        raise RaceNotFoundError(
            f"Requested event {requested_event!r} but the data source matched "
            f"{returned_event!r}. Use the exact official event name."
        )
    return returned_event


# ---------------------------------------------------------------------------
# Building the unified table
# ---------------------------------------------------------------------------
def make_race_id(year, event_name):
    """Build a unique, file-name-safe race label such as ``"2023_hungarian_grand_prix"``.

    Parameters
    ----------
    year : int
        Championship season (>= 2018).
    event_name : str
        Official event name.

    Returns
    -------
    str
        ``"<year>_<event name in lower case, non-letters replaced by '_'>"``.

    Raises
    ------
    TypeError
        If ``year`` is not an int or ``event_name`` is not a str.
    ValueError
        If ``year`` < 2018 or ``event_name`` has no letters or digits.

    Example
    -------
    >>> make_race_id(2023, "Hungarian Grand Prix")
    '2023_hungarian_grand_prix'
    """
    # Validate the year and the event name.
    validate_year(year)
    if not isinstance(event_name, str):
        raise TypeError(f"event_name must be a str, got {type(event_name).__name__}.")
    # Replace every run of characters that are not a-z or 0-9 with one "_".
    # Lower-case the name and replace every run of other characters with "_", e.g.
    # "hungarian_grand_prix".
    slug = re.sub(r"[^a-z0-9]+", "_", event_name.lower()).strip("_")
    if slug == "":
        raise ValueError(f"event_name {event_name!r} contains no letters or digits.")
    return f"{year}_{slug}"


def finalise_laps(laps, year, event_name, total_laps, source):
    """Add the identification columns, fix data types and order the columns.

    Both loaders call this as their last step, which guarantees that their
    outputs have exactly the same structure.

    Parameters
    ----------
    laps : pandas.DataFrame
        Lap rows containing every unified column from ``Driver`` onward.
    year : int
        Championship season.
    event_name : str
        Official event name.
    total_laps : float
        Scheduled race length [laps], or NaN if unknown.
    source : str
        ``"fastf1"`` or ``"openf1"``.

    Returns
    -------
    pandas.DataFrame
        The unified laps table (see module docstring), index 0..N-1.

    Raises
    ------
    RaceDataUnavailableError
        If ``laps`` is empty or a unified column is missing.

    Example
    -------
    >>> table = finalise_laps(raw_rows, 2023, "Hungarian Grand Prix",
    ...                       float("nan"), "openf1")  # doctest: +SKIP
    """
    # Text used in error messages.
    description = f"{year} {event_name} ({source})"
    if laps.empty:
        raise RaceDataUnavailableError(f"No laps were found for {description}.")

    # Add the race-level columns to every lap.
    laps = laps.copy()
    laps["Year"] = year
    laps["EventName"] = event_name
    laps["RaceId"] = make_race_id(year, event_name)
    laps["TotalLaps"] = float(total_laps)
    laps["Source"] = source

    # Every unified column must be present before the table is used.
    missing = [column for column in UNIFIED_COLUMNS if column not in laps.columns]
    if missing:
        raise RaceDataUnavailableError(f"Laps for {description} are missing columns: {missing}")

    # Fix the column types so tables from both sources can be stacked.
    for column in FLOAT_COLUMNS:
        laps[column] = laps[column].astype(float)
    for column in BOOLEAN_COLUMNS:
        laps[column] = laps[column].astype(bool)
    laps["DriverNumber"] = laps["DriverNumber"].astype(str)

    # Put the unified columns first, then any optional ones, sorted by driver and lap.
    extra = [column for column in OPTIONAL_COLUMNS if column in laps.columns]
    ordered = laps[list(UNIFIED_COLUMNS) + extra]
    # Sorting makes the table deterministic regardless of the source's order.
    ordered = ordered.sort_values(["Driver", "LapNumber"], kind="stable")
    return ordered.reset_index(drop=True)


def unknown_total_laps():
    """Return NaN, the value used when a source does not report the race length.

    A named function (rather than a bare ``float("nan")``) makes it explicit
    in the calling code that no number is being guessed; later phases use
    ``race.total_laps_override`` from config.yaml instead.

    Returns
    -------
    float
        NaN.

    Raises
    ------
    Nothing: the function takes no input.

    Example
    -------
    >>> import math
    >>> math.isnan(unknown_total_laps())
    True
    """
    return float("nan")
