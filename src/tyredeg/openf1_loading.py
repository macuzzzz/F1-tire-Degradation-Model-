"""Load race laps from the free OpenF1 web API (https://openf1.org), 2023 onward.

Why OpenF1
----------
Since October 2026 F1's own timing archive requires a paid F1 TV login, so
FastF1 can only load 2021-2022 for free. OpenF1 serves historical data from
2023 onward without authentication (DECISIONS.md, D14). FastF1 is still used
for the event *schedule* (official event names and race dates), which remains
free, so both sources share the same event naming.

What this module does
---------------------
1. :class:`OpenF1Client` downloads JSON from OpenF1, waiting between requests
   and retrying when rate-limited, and saves every response in a local cache
   folder so each race is downloaded only once (D15). The cache matters
   because OpenF1 blocks *all* free access while a live F1 session is running.
2. :func:`load_openf1_laps` combines five OpenF1 endpoints into the unified
   laps table defined in :mod:`tyredeg.loading_common` (D16):

   ===============  ==========================================================
   Endpoint         Used for
   ===============  ==========================================================
   ``sessions``     find the race session (matched on the race date)
   ``drivers``      driver code and team name for each car number
   ``laps``         lap number, lap time, out-lap flag, lap start time
   ``stints``       compound, stint number, tyre age at the stint start
   ``pit``          in-laps (the lap on which a car entered the pit lane)
   ``race_control`` flags and safety cars -> ``IsGreenLap``
   ===============  ==========================================================

OpenF1 fields used (from https://openf1.org/docs, checked 2026-10-24):
sessions: ``session_key, date_start, is_cancelled``; drivers:
``driver_number, name_acronym, team_name``; laps: ``driver_number,
lap_number, lap_duration, is_pit_out_lap, date_start``; stints:
``driver_number, stint_number, compound, lap_start, lap_end,
tyre_age_at_start``; pit: ``driver_number, lap_number``; race_control:
``date, category, flag, scope, sector, message``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import fastf1
import pandas as pd
import requests

from tyredeg.config import OPENF1_FIRST_YEAR
from tyredeg.loading_common import (
    RaceDataUnavailableError,
    RaceNotFoundError,
    check_event_name,
    finalise_laps,
    unknown_total_laps,
    validate_event,
    validate_year,
)
from tyredeg.race_control import is_green_lap, messages_from_records, non_green_intervals, to_naive_utc

logger = logging.getLogger(__name__)

OPENF1_BASE_URL = "https://api.openf1.org/v1"

# OPENF1_FIRST_YEAR (2023, imported from config) comes from OpenF1's docs:
# historical data is free "from 2023 onwards".

# Seconds to wait for the server before giving up on one request.
REQUEST_TIMEOUT_S = 30


class OpenF1Client:
    """Small OpenF1 HTTP client with an on-disk cache.

    Parameters
    ----------
    cache_dir : str or pathlib.Path
        Folder for cached JSON responses, e.g. ``"cache/openf1"``. Created if
        missing. Git-ignored, because the data must not be committed (rule 10).
    request_delay_s : float, optional
        Pause [s] after every real download, to stay polite to the free
        service. Must be >= 0. Default 0.4 (D15).
    max_retries : int, optional
        How many times to retry after HTTP 429 ("too many requests").
        Must be >= 1. Default 5 (D15).

    Raises
    ------
    TypeError, ValueError
        If an argument has the wrong type or range.

    Example
    -------
    >>> client = OpenF1Client("cache/openf1")  # doctest: +SKIP
    >>> client.get("sessions", year=2023, session_name="Race")  # doctest: +SKIP
    """

    def __init__(self, cache_dir, request_delay_s=0.4, max_retries=5):
        if not isinstance(cache_dir, (str, Path)) or str(cache_dir).strip() == "":
            raise TypeError("cache_dir must be a non-empty str or Path.")
        if isinstance(request_delay_s, bool) or not isinstance(request_delay_s, (int, float)):
            raise TypeError("request_delay_s must be a number.")
        if request_delay_s < 0:
            raise ValueError("request_delay_s must be >= 0.")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int):
            raise TypeError("max_retries must be an int.")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1.")
        self.cache_dir = Path(cache_dir)
        self.request_delay_s = float(request_delay_s)
        self.max_retries = max_retries
        self.downloads = 0  # number of real HTTP requests made (useful in tests)

    def cache_path(self, endpoint, params):
        """Return the cache file for one request, e.g. ``cache/openf1/laps/session_key=9566.json``.

        The parameters are sorted so the same request always maps to the same file.
        """
        parts = [f"{key}={params[key]}" for key in sorted(params)]
        file_name = ("_".join(parts) or "all") + ".json"
        return self.cache_dir / endpoint / file_name

    def get(self, endpoint, **params):
        """Return the JSON list for ``endpoint`` with query ``params``, using the cache.

        Parameters
        ----------
        endpoint : str
            OpenF1 endpoint name, e.g. ``"laps"``.
        **params
            Query parameters, e.g. ``session_key=9566``.

        Returns
        -------
        list of dict
            The records. An empty list if OpenF1 has no matching data.

        Raises
        ------
        RaceDataUnavailableError
            If OpenF1 refuses access (e.g. HTTP 401 during a live session),
            keeps rate-limiting after ``max_retries`` attempts, returns another
            error, or cannot be reached.

        Example
        -------
        >>> OpenF1Client("cache/openf1").get("pit", session_key=9566)  # doctest: +SKIP
        """
        path = self.cache_path(endpoint, params)
        if path.is_file():
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)

        records = self._download(endpoint, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(records, file)
        return records

    def _download(self, endpoint, params):
        """Fetch one endpoint from the network, retrying on HTTP 429."""
        url = f"{OPENF1_BASE_URL}/{endpoint}"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
            except requests.RequestException as error:
                raise RaceDataUnavailableError(f"Could not reach OpenF1 ({url}): {error}") from error
            self.downloads += 1
            time.sleep(self.request_delay_s)

            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                # OpenF1 answers 404 when a query simply has no results
                # (observed for a cancelled race); that is not an error.
                return []
            if response.status_code == 429:
                # Rate-limited: wait a little longer after each attempt.
                wait_s = 2.0 * attempt
                logger.info("OpenF1 rate limit hit; waiting %.0f s (attempt %d)", wait_s, attempt)
                time.sleep(wait_s)
                continue
            if response.status_code in (401, 403):
                raise RaceDataUnavailableError(
                    f"OpenF1 refused access to {endpoint} (HTTP {response.status_code}). "
                    f"OpenF1 blocks free access while a live F1 session is running; "
                    f"try again after the session. Server said: {response.text[:200]}"
                )
            raise RaceDataUnavailableError(
                f"OpenF1 returned HTTP {response.status_code} for {endpoint} {params}."
            )
        raise RaceDataUnavailableError(
            f"OpenF1 kept rate-limiting {endpoint} after {self.max_retries} attempts."
        )


# ---------------------------------------------------------------------------
# Finding the race
# ---------------------------------------------------------------------------
def race_date_utc(year, event):
    """Return the official event name and race start (UTC) from FastF1's schedule.

    The schedule is still free (unlike F1's timing archive) and gives the same
    official event names as the FastF1 loader, so both sources agree on names.

    Raises
    ------
    RaceNotFoundError
        If the event is unknown or FastF1 matches a different event (D7).
    RaceDataUnavailableError
        If the schedule cannot be downloaded.
    """
    try:
        event_info = fastf1.get_event(year, event)
    except ValueError as error:
        raise RaceNotFoundError(f"FastF1 could not find {year} {event!r}: {error}") from error
    except Exception as error:
        raise RaceDataUnavailableError(f"Could not fetch the {year} schedule: {error}") from error
    event_name = check_event_name(event_info["EventName"], event)
    race_start = pd.Timestamp(event_info.get_session_date("R", utc=True))
    if race_start.tzinfo is not None:
        race_start = race_start.tz_convert("UTC").tz_localize(None)
    return event_name, race_start


def find_race_session(client, year, race_start):
    """Return the OpenF1 race session that starts on the same UTC date as ``race_start``.

    Raises
    ------
    RaceDataUnavailableError
        If OpenF1 has no (or more than one) race session on that date.
    """
    sessions = client.get("sessions", year=year, session_name="Race")
    matches = []
    for session in sessions:
        if session.get("is_cancelled"):
            continue
        start = to_naive_utc(pd.Series([session["date_start"]])).iloc[0]
        if start.date() == race_start.date():
            matches.append(session)
    if len(matches) != 1:
        raise RaceDataUnavailableError(
            f"Expected exactly one OpenF1 race session on {race_start.date()}, found {len(matches)}."
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Building the laps table
# ---------------------------------------------------------------------------
def _driver_lookup(drivers):
    """Return {car number: (driver code, team name)} from OpenF1 driver records."""
    lookup = {}
    for driver in drivers:
        lookup[driver["driver_number"]] = (driver.get("name_acronym"), driver.get("team_name"))
    return lookup


def _stint_for_lap(stints_of_driver, lap_number):
    """Return the stint record that contains ``lap_number``, or None."""
    for stint in stints_of_driver:
        lap_end = stint.get("lap_end")
        if lap_end is None:
            continue
        if stint["lap_start"] <= lap_number <= lap_end:
            return stint
    return None


def _tyre_life(stint, lap_number):
    """Laps completed on the tyre set by the END of ``lap_number``.

    OpenF1 gives ``tyre_age_at_start`` = laps already completed before the
    stint began. On the stint's first lap the set has therefore completed
    ``tyre_age_at_start + 1`` laps by the end of that lap. This matches
    FastF1's ``TyreLife``, which is 1 on the out-lap of a new set (seen in the
    2022 Bahrain data).
    """
    return stint["tyre_age_at_start"] + (lap_number - stint["lap_start"]) + 1


def build_laps_rows(laps, drivers, stints, pits, race_control):
    """Combine OpenF1 records into one row per lap (unified columns from Driver on).

    Parameters
    ----------
    laps, drivers, stints, pits, race_control : list of dict
        Records from the OpenF1 endpoints of one race session.

    Returns
    -------
    pandas.DataFrame
        Columns Driver, DriverNumber, Team, LapNumber, LapTime, Stint,
        Compound, TyreLife, IsPitInLap, IsPitOutLap, IsGreenLap.

    Raises
    ------
    RaceDataUnavailableError
        If there are no laps.

    Example
    -------
    >>> rows = build_laps_rows(laps, drivers, stints, pits, rc)  # doctest: +SKIP
    """
    if len(laps) == 0:
        raise RaceDataUnavailableError("OpenF1 returned no laps for this session.")

    driver_info = _driver_lookup(drivers)
    stints_by_driver = {}
    for stint in stints:
        stints_by_driver.setdefault(stint["driver_number"], []).append(stint)
    # The pit endpoint's lap_number is the lap on which the car entered the
    # pit lane, i.e. the in-lap.
    in_laps = {(pit["driver_number"], pit["lap_number"]) for pit in pits}
    not_green = non_green_intervals(messages_from_records(race_control))

    start_times = to_naive_utc(pd.Series([lap.get("date_start") for lap in laps]))
    rows = []
    for lap, start_time in zip(laps, start_times):
        number = lap["driver_number"]
        lap_number = lap["lap_number"]
        code, team = driver_info.get(number, (None, None))
        stint = _stint_for_lap(stints_by_driver.get(number, []), lap_number)
        lap_time = lap.get("lap_duration")
        rows.append(
            {
                "Driver": code,
                "DriverNumber": str(number),
                "Team": team,
                "LapNumber": lap_number,
                "LapTime": float(lap_time) if lap_time is not None else float("nan"),
                "Stint": stint["stint_number"] if stint else float("nan"),
                "Compound": stint["compound"] if stint else None,
                "TyreLife": _tyre_life(stint, lap_number) if stint else float("nan"),
                "IsPitInLap": (number, lap_number) in in_laps,
                "IsPitOutLap": bool(lap.get("is_pit_out_lap")),
                "IsGreenLap": is_green_lap(start_time, lap_time, not_green),
            }
        )
    table = pd.DataFrame(rows)
    _log_pit_consistency(table)
    return table


def _log_pit_consistency(table):
    """Warn if an in-lap is not followed by an out-lap (a sanity check on the data).

    After entering the pit lane on lap n, a car normally starts lap n+1 from
    the pit lane. Mismatches can happen legitimately (e.g. retiring in the
    pits) but many of them would suggest the in-lap interpretation is wrong.
    """
    out_laps = set(zip(table.loc[table["IsPitOutLap"], "DriverNumber"],
                       table.loc[table["IsPitOutLap"], "LapNumber"]))
    in_laps = table.loc[table["IsPitInLap"], ["DriverNumber", "LapNumber"]]
    unmatched = 0
    for driver, lap_number in in_laps.itertuples(index=False):
        if (driver, lap_number + 1) not in out_laps:
            unmatched += 1
    if unmatched:
        logger.warning("%d of %d in-laps are not followed by an out-lap.", unmatched, len(in_laps))


def load_openf1_laps(year, event, client):
    """Load every lap of one race from OpenF1 as a unified laps table.

    Parameters
    ----------
    year : int
        Championship season, >= 2023 (OpenF1's free historical data starts in 2023).
    event : str
        Official event name exactly as in FastF1's schedule, e.g.
        ``"Hungarian Grand Prix"`` (case-insensitive; fuzzy matches refused).
    client : OpenF1Client
        Client used for (cached) downloads.

    Returns
    -------
    pandas.DataFrame
        Unified laps table (see :mod:`tyredeg.loading_common`) with
        ``Source == "openf1"``. ``TotalLaps`` is NaN because OpenF1 does not
        report the scheduled race length. No laps are removed here.

    Raises
    ------
    TypeError
        If ``year``/``event``/``client`` has the wrong type.
    ValueError
        If ``year`` < 2023 or ``event`` is empty.
    RaceNotFoundError
        If the event name is unknown or does not match exactly.
    RaceDataUnavailableError
        If OpenF1 cannot be reached, refuses access or has no data.

    Example
    -------
    >>> client = OpenF1Client("cache/openf1")  # doctest: +SKIP
    >>> laps = load_openf1_laps(2023, "Hungarian Grand Prix", client)  # doctest: +SKIP
    """
    validate_year(year)
    validate_event(event)
    if year < OPENF1_FIRST_YEAR:
        raise ValueError(f"OpenF1 has free data from {OPENF1_FIRST_YEAR} onward; got {year}.")
    if not isinstance(client, OpenF1Client):
        raise TypeError(f"client must be an OpenF1Client, got {type(client).__name__}.")

    event_name, race_start = race_date_utc(year, event)
    session = find_race_session(client, year, race_start)
    key = session["session_key"]
    rows = build_laps_rows(
        laps=client.get("laps", session_key=key),
        drivers=client.get("drivers", session_key=key),
        stints=client.get("stints", session_key=key),
        pits=client.get("pit", session_key=key),
        race_control=client.get("race_control", session_key=key),
    )
    logger.info("Loaded %d laps for %d %s from OpenF1", len(rows), year, event_name)
    return finalise_laps(rows, year, event_name, unknown_total_laps(), "openf1")
