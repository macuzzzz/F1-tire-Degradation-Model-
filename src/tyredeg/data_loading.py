"""Public entry point for loading race laps (FastF1 for 2022, OpenF1 for 2023+).

The rest of the project only calls the functions in this module:

- :func:`enable_cache` - switch on FastF1's on-disk cache,
- :func:`load_race_laps` - one race, from the chosen source,
- :func:`load_many` - several races stacked into one table,
- :func:`select_laps` - keep chosen teams / drivers / compounds.

Every function returns the *unified laps table* described in
:mod:`tyredeg.loading_common`, whichever source the data came from
(DECISIONS.md D14, D16).

Typical use (downloads data, so it is shown as a listing, not run as a test)::

    from tyredeg.config import load_config
    from tyredeg.openf1_loading import OpenF1Client
    from tyredeg.tyre_allocation import add_pirelli_compound, load_allocation

    config = load_config("config.yaml")
    enable_cache(config.fastf1_cache_dir)
    client = OpenF1Client(config.openf1_cache_dir, config.openf1_request_delay_s,
                          config.openf1_max_retries)
    races = [(r.year, r.event, r.source) for r in config.races]
    laps = load_many(races, openf1_client=client)
    laps = add_pirelli_compound(laps, load_allocation(config.allocation_file))
    c3_laps = select_laps(laps, pirelli_compounds=list(config.pirelli_compounds))

FastF1 API used (checked against FastF1 3.8.3, see DECISIONS.md D13)
--------------------------------------------------------------------
``fastf1.Cache.enable_cache``, ``fastf1.get_session``, ``Session.load``,
``Session.laps``, ``Session.event["EventName"]``, ``Session.total_laps``,
``fastf1.exceptions.DataNotLoadedError``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fastf1
import fastf1.exceptions
import pandas as pd

from tyredeg.config import VALID_COMPOUNDS, VALID_SOURCES
from tyredeg.loading_common import (  # noqa: F401  (re-exported for callers)
    OPTIONAL_COLUMNS,
    UNIFIED_COLUMNS,
    RaceDataUnavailableError,
    RaceNotFoundError,
    check_event_name,
    finalise_laps,
    make_race_id,
    unknown_total_laps,
    validate_event,
    validate_session,
    validate_year,
)
from tyredeg.openf1_loading import OpenF1Client, load_openf1_laps

logger = logging.getLogger(__name__)

# Columns that must be present in FastF1's laps table. If FastF1 ever renames
# one, we want a clear error here rather than a KeyError much later.
REQUIRED_FASTF1_COLUMNS = (
    "Driver",
    "DriverNumber",
    "Team",
    "LapNumber",
    "LapTime",
    "Stint",
    "Compound",
    "TyreLife",
    "PitInTime",
    "PitOutTime",
    "TrackStatus",
)

# FastF1 track-status code for "all clear". Other codes seen in real data:
# "2" yellow, "4" safety car, "6" VSC deployed, "7" VSC ending (2022 Hungary
# and Bahrain). A lap's TrackStatus string lists every code seen during the
# lap, e.g. "1" (fully green) or "12" (green, then yellow).
GREEN_TRACK_STATUS = "1"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def enable_cache(cache_dir):
    """Create the FastF1 cache folder (if needed) and tell FastF1 to use it.

    With the cache enabled, each race is downloaded only once and later runs
    read it from disk. The folder is git-ignored so that F1 data is never
    committed (project rule 10).

    Parameters
    ----------
    cache_dir : str or pathlib.Path
        Folder for FastF1's cache, e.g. ``"cache/fastf1"``. Relative paths are
        relative to the current working directory. Created if it does not exist.

    Returns
    -------
    pathlib.Path
        The absolute path of the cache folder.

    Raises
    ------
    TypeError
        If ``cache_dir`` is not a ``str`` or ``Path``.
    ValueError
        If ``cache_dir`` is an empty string.

    Example
    -------
    >>> enable_cache("cache/fastf1")  # doctest: +SKIP
    WindowsPath('C:/.../cache/fastf1')
    """
    # The cache folder must be given as a non-empty path.
    if not isinstance(cache_dir, (str, Path)):
        raise TypeError(f"cache_dir must be a str or Path, got {type(cache_dir).__name__}.")
    if str(cache_dir).strip() == "":
        raise ValueError("cache_dir must not be empty.")
    # Create the folder if needed and point FastF1 at it, so each race downloads only once.
    path = Path(cache_dir).resolve()
    # FastF1 refuses to use a cache folder that does not exist yet.
    path.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(path))
    logger.info("FastF1 cache enabled at %s", path)
    return path


# ---------------------------------------------------------------------------
# FastF1 loader
# ---------------------------------------------------------------------------
def timedelta_to_seconds(values):
    """Convert a Series of time durations to float seconds.

    Missing durations (``NaT``, "not a time") become ``NaN`` rather than being
    dropped, so that the cleaning step can later count how many laps were
    removed because their time was missing.

    Parameters
    ----------
    values : pandas.Series
        Series with dtype ``timedelta64``.

    Returns
    -------
    pandas.Series
        Same index, dtype ``float64``, values in seconds.

    Raises
    ------
    TypeError
        If ``values`` is not a pandas Series of dtype ``timedelta64``.

    Example
    -------
    >>> s = pd.Series(pd.to_timedelta(["0:01:32.500", None]))
    >>> timedelta_to_seconds(s).tolist()
    [92.5, nan]
    """
    # Only a pandas timedelta Series can be converted to seconds.
    if not isinstance(values, pd.Series):
        raise TypeError(f"Expected a pandas Series, got {type(values).__name__}.")
    if not pd.api.types.is_timedelta64_dtype(values):
        raise TypeError(f"Expected a timedelta64 Series, got dtype {values.dtype}.")
    # Convert durations such as 0:01:20.5 to float seconds (missing values stay NaN).
    return values.dt.total_seconds().astype(float)


def is_green_track_status(track_status):
    """Return True if a FastF1 ``TrackStatus`` string contains only the green code.

    Parameters
    ----------
    track_status : str or None
        Codes seen during the lap, e.g. ``"1"`` or ``"124"``.

    Returns
    -------
    bool
        True only for a non-empty string made up solely of ``"1"``. A missing
        status cannot be shown to be green, so it returns False.

    Raises
    ------
    Nothing: any value that is not a non-empty string returns False.

    Example
    -------
    >>> is_green_track_status("1"), is_green_track_status("12"), is_green_track_status(None)
    (True, False, False)
    """
    # A missing or empty status cannot be shown to be green.
    if not isinstance(track_status, str) or track_status == "":
        return False
    # Green only if every status code seen during the lap is "1" (track clear).
    return set(track_status) == {GREEN_TRACK_STATUS}


def _get_fastf1_session(year, event, session):
    """Ask FastF1 for the session object (this does not download lap data yet)."""
    # Ask FastF1 for the session; translate its errors into this project's two error types.
    try:
        return fastf1.get_session(year, event, session)
    except ValueError as error:
        # FastF1 raises ValueError for events/sessions it cannot find.
        raise RaceNotFoundError(
            f"FastF1 could not find session {session!r} of {year} {event!r}: {error}"
        ) from error
    except Exception as error:
        # Anything else (e.g. no internet while fetching the season schedule)
        # is not the caller's fault, so it is reported as "data unavailable".
        raise RaceDataUnavailableError(
            f"Could not fetch the {year} event schedule from FastF1: {error}"
        ) from error


def _download_fastf1_laps(fastf1_session, description):
    """Run ``Session.load`` and return FastF1's laps table as a plain DataFrame."""
    # Download laps and race-control messages only (no telemetry or weather, to save time).
    try:
        # Only lap timing is needed (D8). Telemetry is large and unused until
        # the optional Phase 10; weather is unused. Race-control messages are
        # kept because FastF1 uses them to mark deleted laps.
        fastf1_session.load(laps=True, telemetry=False, weather=False, messages=True)
    except Exception as error:
        # FastF1 can fail in many ways (network, parsing, ...); we turn them all
        # into one clear exception type so callers only need to catch one.
        raise RaceDataUnavailableError(f"FastF1 failed to load {description}: {error}") from error

    # Accessing laps fails if nothing was downloaded, e.g. when the archive needs a login.
    try:
        laps = fastf1_session.laps
    except fastf1.exceptions.DataNotLoadedError as error:
        # Session.load() does NOT raise when a download fails: it only logs
        # warnings, and the error appears here when the laps are accessed.
        raise RaceDataUnavailableError(
            f"No lap data could be downloaded for {description}. Since Oct 2026 "
            f"F1's timing archive needs an F1 TV login; FastF1's free mirror only "
            f"covers 2021-2022. Use source 'openf1' for 2023 onward (D14)."
        ) from error

    # FastF1's `Laps` class is a DataFrame subclass with extra behaviour; a
    # plain DataFrame is simpler and keeps the rest of the code FastF1-free.
    # Work on a plain DataFrame and refuse an empty result.
    laps = pd.DataFrame(laps)
    if laps.empty:
        raise RaceDataUnavailableError(f"FastF1 returned no laps for {description}.")
    return laps


def _read_total_laps(fastf1_session, description):
    """Return the scheduled race length [laps] as a float, or NaN if unknown."""
    # FastF1's official race length; NaN if unknown (filled later, never guessed here).
    total_laps = getattr(fastf1_session, "total_laps", None)
    if total_laps is None or pd.isna(total_laps):
        logger.warning("Total lap count unavailable for %s; TotalLaps set to NaN.", description)
        return unknown_total_laps()
    return float(total_laps)


def _fastf1_to_unified(raw_laps, description):
    """Convert FastF1's laps table to the unified columns (from Driver onward)."""
    # Every column the unified table needs must be present.
    missing = [column for column in REQUIRED_FASTF1_COLUMNS if column not in raw_laps.columns]
    if missing:
        raise RaceDataUnavailableError(
            f"FastF1 laps for {description} are missing required columns: {missing}"
        )

    # Build the unified table: times in seconds and pit/green flags as booleans.
    laps = pd.DataFrame(
        {
            "Driver": raw_laps["Driver"],
            "DriverNumber": raw_laps["DriverNumber"],
            "Team": raw_laps["Team"],
            "LapNumber": raw_laps["LapNumber"],
            "LapTime": timedelta_to_seconds(raw_laps["LapTime"]),
            "Stint": raw_laps["Stint"],
            "Compound": raw_laps["Compound"],
            "TyreLife": raw_laps["TyreLife"],
            # FastF1 records the session time of pit entry/exit on the lap
            # where it happened; a value present means "this is an in/out-lap".
            "IsPitInLap": raw_laps["PitInTime"].notna(),
            "IsPitOutLap": raw_laps["PitOutTime"].notna(),
            "IsGreenLap": raw_laps["TrackStatus"].apply(is_green_track_status),
        }
    )
    # Keep optional FastF1 columns when present (they help the cleaning rules).
    for column in OPTIONAL_COLUMNS:
        if column in raw_laps.columns:
            laps[column] = raw_laps[column]
        else:
            logger.info("Optional column %r not provided for %s.", column, description)
    return laps


def load_fastf1_laps(year, event, session="R"):
    """Load every lap of one race from FastF1 as a unified laps table.

    Parameters
    ----------
    year : int
        Championship season, >= 2018. For free use, 2021-2022 only (D14).
    event : str
        Official event name, e.g. ``"Hungarian Grand Prix"`` (case-insensitive;
        fuzzy matches are refused, D7).
    session : str, optional
        Only ``"R"`` (race) is supported. Default ``"R"``.

    Returns
    -------
    pandas.DataFrame
        Unified laps table with ``Source == "fastf1"`` plus the optional
        FastF1 columns. No laps are removed here.

    Raises
    ------
    TypeError, ValueError
        For invalid ``year``, ``event`` or ``session``.
    RaceNotFoundError
        If FastF1 cannot find the event or matches a different event name.
    RaceDataUnavailableError
        If the lap data cannot be downloaded, is empty, or lacks a column.

    Example
    -------
    >>> laps = load_fastf1_laps(2022, "Bahrain Grand Prix")  # doctest: +SKIP
    >>> ver = laps[laps.Driver == "VER"]  # doctest: +SKIP
    >>> ver["LapTime"].head(2).tolist(), ver["Compound"].head(2).tolist()  # doctest: +SKIP
    ([100.236, 97.88], ['SOFT', 'SOFT'])
    """
    # Validate the request before any download.
    validate_year(year)
    validate_event(event)
    validate_session(session)
    description = f"{year} {event} ({session})"

    # Get the session, check FastF1 matched the requested event, then download and convert.
    fastf1_session = _get_fastf1_session(year, event, session)
    event_name = check_event_name(fastf1_session.event["EventName"], event)
    raw_laps = _download_fastf1_laps(fastf1_session, description)
    laps = _fastf1_to_unified(raw_laps, description)
    total_laps = _read_total_laps(fastf1_session, description)
    logger.info("Loaded %d laps for %s from FastF1", len(laps), description)
    return finalise_laps(laps, year, event_name, total_laps, "fastf1")


# ---------------------------------------------------------------------------
# Public loading functions
# ---------------------------------------------------------------------------
def load_race_laps(year, event, session="R", source="fastf1", openf1_client=None):
    """Load every lap of one race from the chosen source.

    Parameters
    ----------
    year : int
        Championship season (>= 2018; >= 2023 for OpenF1).
    event : str
        Official event name, e.g. ``"Hungarian Grand Prix"``.
    session : str, optional
        Only ``"R"`` (race) is supported. Default ``"R"``.
    source : str, optional
        ``"fastf1"`` (default) or ``"openf1"`` (D14).
    openf1_client : OpenF1Client or None, optional
        Required when ``source == "openf1"``; ignored otherwise.

    Returns
    -------
    pandas.DataFrame
        Unified laps table (see :mod:`tyredeg.loading_common`).

    Raises
    ------
    TypeError, ValueError
        For invalid arguments, an unknown source, or a missing OpenF1 client.
    RaceNotFoundError, RaceDataUnavailableError
        From the underlying loader.

    Example
    -------
    >>> laps = load_race_laps(2023, "Hungarian Grand Prix", source="openf1",
    ...                       openf1_client=OpenF1Client("cache/openf1"))  # doctest: +SKIP
    """
    # Only known data sources are accepted.
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}, got {source!r}.")
    # FastF1 for seasons in its free mirror (2022 here); OpenF1 for 2023 onward.
    if source == "fastf1":
        return load_fastf1_laps(year, event, session)

    validate_session(session)
    if openf1_client is None:
        raise ValueError("source 'openf1' needs an OpenF1Client (argument openf1_client).")
    return load_openf1_laps(year, event, openf1_client)


def _parse_race_entry(entry):
    """Return (year, event, source) from a (year, event) or (year, event, source) entry."""
    # Each race is (year, event) or (year, event, source); the source defaults to FastF1.
    if not isinstance(entry, (list, tuple)) or len(entry) not in (2, 3):
        raise TypeError(f"Each race must be (year, event) or (year, event, source), got {entry!r}.")
    year, event = entry[0], entry[1]
    source = entry[2] if len(entry) == 3 else "fastf1"
    validate_year(year)
    validate_event(event)
    if source not in VALID_SOURCES:
        raise ValueError(f"Unknown source {source!r} for {year} {event}; use one of {VALID_SOURCES}.")
    return year, event, source


def load_many(races, session="R", openf1_client=None):
    """Load several races and stack them into one DataFrame.

    Parameters
    ----------
    races : list of tuples
        ``(year, event)`` (FastF1) or ``(year, event, source)`` entries, e.g.
        ``[(2022, "Hungarian Grand Prix", "fastf1"),
        (2023, "Hungarian Grand Prix", "openf1")]``. Non-empty, no duplicates.
    session : str, optional
        Session identifier. Only ``"R"``. Default ``"R"``.
    openf1_client : OpenF1Client or None, optional
        Required if any race uses source ``"openf1"``.

    Returns
    -------
    pandas.DataFrame
        All laps of all races, in the order given. ``RaceId`` tells the races
        apart, which later lets validation split the data *by race*.

    Raises
    ------
    TypeError
        If ``races`` is not a list/tuple or an entry is malformed.
    ValueError
        If ``races`` is empty, a race is listed twice, or a source is unknown.
        All entries are checked before anything is downloaded.
    RaceNotFoundError, RaceDataUnavailableError
        From the first race that fails. Failing loudly (rather than skipping
        the race) prevents a run from quietly using fewer races than configured.

    Example
    -------
    >>> laps = load_many([(2022, "Hungarian Grand Prix", "fastf1"),
    ...                   (2023, "Hungarian Grand Prix", "openf1")],
    ...                  openf1_client=OpenF1Client("cache/openf1"))  # doctest: +SKIP
    """
    # Need a non-empty list of races.
    if not isinstance(races, (list, tuple)):
        raise TypeError(f"races must be a list of race tuples, got {type(races).__name__}.")
    if len(races) == 0:
        raise ValueError("races must contain at least one race.")

    # Validate every entry and refuse duplicates (a race loaded twice would be double-counted).
    parsed = []
    seen = set()
    for entry in races:
        year, event, source = _parse_race_entry(entry)
        key = (year, event.strip().casefold())
        if key in seen:
            raise ValueError(f"Race {year} {event!r} is listed more than once.")
        seen.add(key)
        parsed.append((year, event, source))

    # Load each race and stack them into one table.
    tables = []
    for year, event, source in parsed:
        tables.append(load_race_laps(year, event, session, source, openf1_client))
    # ignore_index=True gives the combined table a fresh 0..N-1 index.
    return pd.concat(tables, ignore_index=True)


def select_laps(laps, teams=None, drivers=None, compounds=None, pirelli_compounds=None):
    """Keep only the laps of the chosen teams, drivers and tyre compounds.

    Each filter is optional: ``None`` means "do not filter on this column".

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table.
    teams : list of str or None, optional
        Team names exactly as in the ``Team`` column, e.g. ``["Red Bull Racing"]``.
    drivers : list of str or None, optional
        Three-letter driver codes, e.g. ``["VER", "PER"]``.
    compounds : list of str or None, optional
        Relative labels from ``"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"``.
    pirelli_compounds : list of str or None, optional
        Pirelli codes such as ``["C3"]``; needs the ``PirelliCompound`` column
        added by :func:`tyredeg.tyre_allocation.add_pirelli_compound`.

    Returns
    -------
    pandas.DataFrame
        The matching rows (a copy), with a fresh 0..N-1 index.

    Raises
    ------
    TypeError
        If ``laps`` is not a DataFrame or a filter is not a list of strings.
    ValueError
        If ``laps`` is empty, a needed column is missing, a filter list is
        empty, a compound name is unknown, or no laps match the filters.

    Example
    -------
    >>> c3 = select_laps(laps, pirelli_compounds=["C3"])  # doctest: +SKIP
    """
    # Validate the table and the compound labels.
    if not isinstance(laps, pd.DataFrame):
        raise TypeError(f"laps must be a pandas DataFrame, got {type(laps).__name__}.")
    if laps.empty:
        raise ValueError("laps is empty; there is nothing to select from.")
    if compounds is not None:
        for compound in compounds:
            if compound not in VALID_COMPOUNDS:
                raise ValueError(f"Unknown compound {compound!r}. Allowed: {VALID_COMPOUNDS}.")

    # Each filter keeps only the listed values; None means "no filter".
    filters = (
        ("Team", teams),
        ("Driver", drivers),
        ("Compound", compounds),
        ("PirelliCompound", pirelli_compounds),
    )
    # Start with every row selected, then switch rows off filter by filter.
    # Combine the filters: a lap is kept only if it passes every active one.
    keep = pd.Series(True, index=laps.index)
    for column, allowed in filters:
        if allowed is None:
            continue
        if not isinstance(allowed, (list, tuple)) or not all(isinstance(a, str) for a in allowed):
            raise TypeError(f"The {column} filter must be a list of strings, got {allowed!r}.")
        if len(allowed) == 0:
            raise ValueError(f"The {column} filter is an empty list; use None for 'all'.")
        if column not in laps.columns:
            raise ValueError(f"Column {column!r} not found in laps.")
        keep = keep & laps[column].isin(allowed)

    # An empty result usually means a misspelt name, so say what was asked for.
    selected = laps[keep].reset_index(drop=True)
    if selected.empty:
        raise ValueError(
            f"No laps match teams={teams}, drivers={drivers}, compounds={compounds}, "
            f"pirelli_compounds={pirelli_compounds}."
        )
    return selected
