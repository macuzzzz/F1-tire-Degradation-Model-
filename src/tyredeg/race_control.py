"""Decide from race-control messages whether each lap was run under green flag.

Why this module exists
----------------------
FastF1 gives every lap a ``TrackStatus`` code, but OpenF1 does not. OpenF1
only provides the race-control messages (the texts shown on the official
timing screens). This module rebuilds the "was the track green?" information
from those messages so OpenF1 laps can get the same ``IsGreenLap`` column as
FastF1 laps (DECISIONS.md, D16).

How it works
------------
1. :func:`non_green_intervals` replays the messages in time order and keeps
   track of what is active: yellow flags per track sector, a track-wide
   yellow, safety car (SC), virtual safety car (VSC) and red flag. Whenever at
   least one of these is active the track is "not green". The function
   returns the list of (start, end) time windows when the track was not green.
2. :func:`is_green_lap` says a lap is green if its time window
   [lap start, lap start + lap time] overlaps none of those windows.

The message texts handled here were checked against real race-control
messages of the 2022 Hungarian and Bahrain Grands Prix (via FastF1, which
relays the same official feed as OpenF1), e.g.::

    Flag       YELLOW   Sector 5   "YELLOW IN TRACK SECTOR 5"
    Flag       CLEAR    Sector 5   "CLEAR IN TRACK SECTOR 5"
    SafetyCar                      "VIRTUAL SAFETY CAR DEPLOYED"
    SafetyCar                      "VIRTUAL SAFETY CAR ENDING"
    SafetyCar                      "SAFETY CAR DEPLOYED"
    SafetyCar                      "SAFETY CAR IN THIS LAP"
    Flag       CLEAR    Track      "TRACK CLEAR"

Input format
------------
A DataFrame with one row per message and the (lower-case) columns
``date`` (UTC timestamp), ``category``, ``flag``, ``scope``, ``sector`` and
``message``. :func:`messages_from_records` builds it from OpenF1 records.
"""

from __future__ import annotations

import pandas as pd

MESSAGE_COLUMNS = ("date", "category", "flag", "scope", "sector", "message")

# Flags that mean "slow down, danger ahead".
YELLOW_FLAGS = ("YELLOW", "DOUBLE YELLOW")


def messages_from_records(records):
    """Convert a list of race-control message dictionaries into the input DataFrame.

    Parameters
    ----------
    records : list of dict
        Race-control messages, e.g. as returned by the OpenF1
        ``race_control`` endpoint. Each needs the keys ``date``, ``category``,
        ``flag``, ``scope``, ``sector`` and ``message`` (values may be None).

    Returns
    -------
    pandas.DataFrame
        Columns ``MESSAGE_COLUMNS``; ``date`` as timezone-naive UTC
        timestamps, sorted by date.

    Raises
    ------
    TypeError
        If ``records`` is not a list.
    ValueError
        If a record lacks one of the required keys or has an unreadable date.

    Example
    -------
    >>> df = messages_from_records([{"date": "2023-07-23T13:10:00+00:00",
    ...     "category": "SafetyCar", "flag": None, "scope": None,
    ...     "sector": None, "message": "SAFETY CAR DEPLOYED"}])
    >>> df["category"].tolist()
    ['SafetyCar']
    """
    if not isinstance(records, list):
        raise TypeError(f"records must be a list of dicts, got {type(records).__name__}.")
    if len(records) == 0:
        return pd.DataFrame(columns=list(MESSAGE_COLUMNS))
    for record in records:
        missing = [key for key in MESSAGE_COLUMNS if key not in record]
        if missing:
            raise ValueError(f"Race-control record is missing keys {missing}: {record}")

    messages = pd.DataFrame(records)[list(MESSAGE_COLUMNS)].copy()
    messages["date"] = to_naive_utc(messages["date"])
    return messages.sort_values("date", kind="stable").reset_index(drop=True)


def to_naive_utc(values):
    """Parse timestamps and return them in UTC without timezone information.

    Mixing timezone-aware and timezone-naive timestamps raises errors in
    pandas, so every timestamp in this project is stored as naive UTC.

    Parameters
    ----------
    values : pandas.Series
        ISO 8601 strings (e.g. ``"2023-07-23T13:10:00+00:00"``) or timestamps.

    Returns
    -------
    pandas.Series
        dtype ``datetime64[ns]`` (naive, UTC). Unparseable values raise.

    Raises
    ------
    ValueError
        If a value cannot be parsed as a date.

    Example
    -------
    >>> to_naive_utc(pd.Series(["2023-07-23T15:10:00+02:00"])).iloc[0]
    Timestamp('2023-07-23 13:10:00')
    """
    try:
        parsed = pd.to_datetime(values, utc=True, format="ISO8601")
    except (ValueError, TypeError) as error:
        raise ValueError(f"Could not parse dates: {error}") from error
    return parsed.dt.tz_localize(None)


class _TrackState:
    """What is currently active on track while the messages are replayed."""

    def __init__(self):
        self.yellow_sectors = set()   # sectors currently showing a yellow flag
        self.track_yellow = False     # yellow flag for the whole track
        self.safety_car = False
        self.virtual_safety_car = False
        self.red_flag = False

    def is_green(self):
        """The track is green only if nothing at all is active."""
        return not (
            self.yellow_sectors
            or self.track_yellow
            or self.safety_car
            or self.virtual_safety_car
            or self.red_flag
        )

    def clear_everything(self):
        """"TRACK CLEAR" (or a green flag for the whole track) ends every hazard."""
        self.yellow_sectors.clear()
        self.track_yellow = False
        self.safety_car = False
        self.virtual_safety_car = False
        self.red_flag = False

    def apply(self, category, flag, scope, sector, message):
        """Update the state with one message."""
        if category == "SafetyCar":
            self._apply_safety_car(message)
        elif category == "Flag":
            self._apply_flag(flag, scope, sector)
        # Other categories (DRS, car events, penalties, ...) do not change the
        # track status, so they are ignored.

    def _apply_safety_car(self, message):
        # The VIRTUAL check must come first, because "VIRTUAL SAFETY CAR
        # DEPLOYED" also contains the words "SAFETY CAR DEPLOYED".
        if "VIRTUAL SAFETY CAR DEPLOYED" in message:
            self.virtual_safety_car = True
        elif "SAFETY CAR DEPLOYED" in message:
            self.safety_car = True
        # "VIRTUAL SAFETY CAR ENDING" and "SAFETY CAR IN THIS LAP" only
        # announce the end: cars are still slowed until "TRACK CLEAR", so the
        # state is deliberately left unchanged here.

    def _apply_flag(self, flag, scope, sector):
        if flag in YELLOW_FLAGS:
            if scope == "Sector" and sector is not None:
                self.yellow_sectors.add(sector)
            else:
                self.track_yellow = True
        elif flag == "CLEAR":
            if scope == "Sector" and sector is not None:
                self.yellow_sectors.discard(sector)
            else:
                self.clear_everything()
        elif flag == "RED":
            self.red_flag = True
        elif flag == "GREEN" and scope == "Track":
            self.clear_everything()
        # BLUE (let faster car pass), CHEQUERED, BLACK AND WHITE, ... do not
        # affect everyone's lap time, so they are ignored.


def _text(value):
    """Return ``value`` as an upper-case string, or "" if it is missing."""
    if value is None or pd.isna(value):
        return ""
    return str(value).upper()


def _sector(value):
    """Return the sector number as an int, or None if it is missing."""
    if value is None or pd.isna(value):
        return None
    return int(value)


def non_green_intervals(messages):
    """Return the time windows during which the track was NOT green.

    Parameters
    ----------
    messages : pandas.DataFrame
        Race-control messages with columns ``MESSAGE_COLUMNS`` (see
        :func:`messages_from_records`). Rows are processed in date order.

    Returns
    -------
    list of (pandas.Timestamp, pandas.Timestamp)
        ``(start, end)`` pairs in UTC. If the track is still not green after
        the last message, that window ends at ``pandas.Timestamp.max``.

    Raises
    ------
    TypeError
        If ``messages`` is not a DataFrame.
    ValueError
        If a required column is missing.

    Example
    -------
    >>> msgs = messages_from_records([
    ...     {"date": "2023-07-23T13:20:00Z", "category": "Flag", "flag": "YELLOW",
    ...      "scope": "Sector", "sector": 5, "message": "YELLOW IN TRACK SECTOR 5"},
    ...     {"date": "2023-07-23T13:20:30Z", "category": "Flag", "flag": "CLEAR",
    ...      "scope": "Sector", "sector": 5, "message": "CLEAR IN TRACK SECTOR 5"}])
    >>> non_green_intervals(msgs)
    [(Timestamp('2023-07-23 13:20:00'), Timestamp('2023-07-23 13:20:30'))]
    """
    if not isinstance(messages, pd.DataFrame):
        raise TypeError(f"messages must be a DataFrame, got {type(messages).__name__}.")
    missing = [column for column in MESSAGE_COLUMNS if column not in messages.columns]
    if missing:
        raise ValueError(f"messages is missing columns: {missing}")

    state = _TrackState()
    intervals = []
    window_start = None  # start time of the current not-green window, if any

    for row in messages.sort_values("date", kind="stable").itertuples(index=False):
        state.apply(
            category=str(row.category) if row.category is not None else "",
            flag=_text(row.flag),
            scope=str(row.scope) if row.scope is not None and not pd.isna(row.scope) else "",
            sector=_sector(row.sector),
            message=_text(row.message),
        )
        if not state.is_green() and window_start is None:
            window_start = row.date
        elif state.is_green() and window_start is not None:
            intervals.append((window_start, row.date))
            window_start = None

    if window_start is not None:
        intervals.append((window_start, pd.Timestamp.max))
    return intervals


def is_green_lap(lap_start, lap_time_s, intervals):
    """Return True if the lap overlaps none of the not-green windows.

    Parameters
    ----------
    lap_start : pandas.Timestamp or None
        UTC time at which the lap started (timezone-naive).
    lap_time_s : float or None
        Lap time [s].
    intervals : list of (pandas.Timestamp, pandas.Timestamp)
        Output of :func:`non_green_intervals`.

    Returns
    -------
    bool
        True if the lap was fully green. False if it overlaps any window,
        **or if its start time or lap time is missing**: a lap whose timing is
        unknown cannot be shown to be green, so it is treated as not green.

    Raises
    ------
    ValueError
        If ``lap_time_s`` is negative.

    Example
    -------
    >>> start = pd.Timestamp("2023-07-23 13:19:00")
    >>> window = [(pd.Timestamp("2023-07-23 13:20:00"), pd.Timestamp("2023-07-23 13:20:30"))]
    >>> is_green_lap(start, 80.0, window)   # lap ends 13:20:20, overlaps
    False
    >>> is_green_lap(start, 50.0, window)   # lap ends 13:19:50, before it
    True
    """
    if lap_start is None or pd.isna(lap_start) or lap_time_s is None or pd.isna(lap_time_s):
        return False
    if lap_time_s < 0:
        raise ValueError(f"lap_time_s must be >= 0 s, got {lap_time_s}.")
    lap_end = lap_start + pd.Timedelta(seconds=float(lap_time_s))
    for window_start, window_end in intervals:
        # Two time ranges overlap if each one starts before the other ends.
        if window_start < lap_end and window_end > lap_start:
            return False
    return True
