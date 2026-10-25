"""Offline tests for tyredeg.race_control (green-lap detection from messages).

The message texts mirror real race-control messages seen in the 2022
Hungarian and Bahrain Grands Prix. On those two races the message-based
method agreed with FastF1's own track-status codes on 100.0 % and 99.8 % of
timed laps (DECISIONS.md, D16); these tests pin down the logic on small,
hand-checkable cases.
"""

import pandas as pd
import pytest

from tyredeg.race_control import (
    is_green_lap,
    messages_from_records,
    non_green_intervals,
    to_naive_utc,
)

T = pd.Timestamp


def msg(time, category, message, flag=None, scope=None, sector=None):
    """One race-control record in OpenF1 format (time as 'HH:MM:SS' on a fixed day)."""
    return {
        "date": f"2023-07-23T{time}+00:00",
        "category": category,
        "flag": flag,
        "scope": scope,
        "sector": sector,
        "message": message,
    }


def windows(records):
    # Non-green windows from a list of messages.
    return non_green_intervals(messages_from_records(records))


# ---------------------------------------------------------------------------
# non_green_intervals
# ---------------------------------------------------------------------------
def test_no_messages_means_always_green():
    assert windows([]) == []


def test_sector_yellow_until_cleared():
    # A sector yellow lasts until that sector is cleared.
    result = windows([
        msg("13:20:00", "Flag", "YELLOW IN TRACK SECTOR 5", "YELLOW", "Sector", 5),
        msg("13:20:30", "Flag", "CLEAR IN TRACK SECTOR 5", "CLEAR", "Sector", 5),
    ])
    assert result == [(T("2023-07-23 13:20:00"), T("2023-07-23 13:20:30"))]


def test_overlapping_sector_yellows_form_one_window():
    # Sector 10 clears first, but sector 9 is still yellow, so the track is
    # only green again once BOTH are clear (real pattern from 2022 Hungary).
    result = windows([
        msg("13:52:42", "Flag", "DOUBLE YELLOW IN TRACK SECTOR 10", "DOUBLE YELLOW", "Sector", 10),
        msg("13:52:49", "Flag", "YELLOW IN TRACK SECTOR 9", "YELLOW", "Sector", 9),
        msg("13:52:55", "Flag", "CLEAR IN TRACK SECTOR 10", "CLEAR", "Sector", 10),
        msg("13:52:57", "Flag", "CLEAR IN TRACK SECTOR 9", "CLEAR", "Sector", 9),
    ])
    assert result == [(T("2023-07-23 13:52:42"), T("2023-07-23 13:52:57"))]


def test_vsc_lasts_until_track_clear_not_until_ending():
    # A VSC lasts until "TRACK CLEAR", not until "VSC ENDING".
    result = windows([
        msg("13:04:36", "SafetyCar", "VIRTUAL SAFETY CAR DEPLOYED"),
        msg("13:06:43", "SafetyCar", "VIRTUAL SAFETY CAR ENDING"),
        msg("13:06:53", "Flag", "TRACK CLEAR", "CLEAR", "Track"),
    ])
    assert result == [(T("2023-07-23 13:04:36"), T("2023-07-23 13:06:53"))]


def test_safety_car_until_track_clear():
    # A safety car lasts until "TRACK CLEAR".
    result = windows([
        msg("16:18:40", "SafetyCar", "SAFETY CAR DEPLOYED"),
        msg("16:28:00", "SafetyCar", "SAFETY CAR IN THIS LAP"),
        msg("16:29:54", "Flag", "TRACK CLEAR", "CLEAR", "Track"),
    ])
    assert result == [(T("2023-07-23 16:18:40"), T("2023-07-23 16:29:54"))]


def test_track_clear_also_clears_sector_yellows():
    # "TRACK CLEAR" also ends any sector yellow still open.
    result = windows([
        msg("13:00:00", "Flag", "YELLOW IN TRACK SECTOR 3", "YELLOW", "Sector", 3),
        msg("13:00:10", "Flag", "TRACK CLEAR", "CLEAR", "Track"),
    ])
    assert result == [(T("2023-07-23 13:00:00"), T("2023-07-23 13:00:10"))]


def test_red_flag_until_green():
    # A red flag lasts until the green light.
    result = windows([
        msg("14:00:00", "Flag", "RED FLAG", "RED", "Track"),
        msg("14:30:00", "Flag", "GREEN LIGHT - PIT EXIT OPEN", "GREEN", "Track"),
    ])
    assert result == [(T("2023-07-23 14:00:00"), T("2023-07-23 14:30:00"))]


def test_unfinished_window_is_open_ended():
    # A window never closed stays open until the end of the race.
    result = windows([msg("15:00:00", "SafetyCar", "SAFETY CAR DEPLOYED")])
    assert result == [(T("2023-07-23 15:00:00"), pd.Timestamp.max)]


def test_irrelevant_messages_are_ignored():
    # Blue flags, DRS and track-limit messages do not affect green status.
    result = windows([
        msg("13:00:00", "Flag", "BLUE FLAG FOR CAR 2 (SAR)", "BLUE", "Driver"),
        msg("13:01:00", "Drs", "DRS ENABLED"),
        msg("13:02:00", "Other", "CAR 44 (HAM) TIME 1:25.186 DELETED - TRACK LIMITS"),
        msg("14:40:00", "Flag", "CHEQUERED FLAG", "CHEQUERED", "Track"),
    ])
    assert result == []


def test_messages_are_processed_in_time_order():
    # Messages are sorted by time before processing.
    unordered = [
        msg("13:20:30", "Flag", "CLEAR IN TRACK SECTOR 5", "CLEAR", "Sector", 5),
        msg("13:20:00", "Flag", "YELLOW IN TRACK SECTOR 5", "YELLOW", "Sector", 5),
    ]
    assert windows(unordered) == [(T("2023-07-23 13:20:00"), T("2023-07-23 13:20:30"))]


def test_non_green_intervals_rejects_bad_input():
    # Invalid message tables are rejected.
    with pytest.raises(TypeError):
        non_green_intervals([{"date": "x"}])
    with pytest.raises(ValueError, match="missing"):
        non_green_intervals(pd.DataFrame({"date": [T("2023-07-23")]}))


# ---------------------------------------------------------------------------
# is_green_lap
# ---------------------------------------------------------------------------
WINDOW = [(T("2023-07-23 13:20:00"), T("2023-07-23 13:20:30"))]


@pytest.mark.parametrize(
    "start, lap_time, expected",
    [
        ("13:18:00", 80.0, True),    # ends 13:19:20, before the window
        ("13:19:00", 80.0, False),   # ends 13:20:20, overlaps the start of the window
        ("13:20:10", 5.0, False),    # entirely inside the window
        ("13:19:50", 60.0, False),   # covers the whole window
        ("13:20:30", 80.0, True),    # starts exactly when the window ends
        ("13:18:40", 80.0, True),    # ends exactly when the window starts
    ],
)
def test_is_green_lap_overlap_cases(start, lap_time, expected):
    # A lap is green only if it does not overlap any non-green window.
    assert is_green_lap(T(f"2023-07-23 {start}"), lap_time, WINDOW) is expected


def test_missing_timing_is_not_green():
    # A lap with missing timing cannot be shown to be green, so it is not green.
    assert is_green_lap(None, 80.0, []) is False
    assert is_green_lap(pd.NaT, 80.0, []) is False
    assert is_green_lap(T("2023-07-23 13:00:00"), None, []) is False
    assert is_green_lap(T("2023-07-23 13:00:00"), float("nan"), []) is False


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------
def test_to_naive_utc_converts_timezones():
    result = to_naive_utc(pd.Series(["2023-07-23T15:10:00+02:00", "2023-07-23T13:10:00Z"]))
    assert result.tolist() == [T("2023-07-23 13:10:00"), T("2023-07-23 13:10:00")]
    assert result.dt.tz is None


def test_to_naive_utc_rejects_garbage():
    # Text that is not a date is rejected.
    with pytest.raises(ValueError):
        to_naive_utc(pd.Series(["not a date"]))


def test_messages_from_records_validates():
    # Messages must be a list of records with the required keys.
    with pytest.raises(TypeError):
        messages_from_records("SAFETY CAR DEPLOYED")
    with pytest.raises(ValueError, match="missing keys"):
        messages_from_records([{"date": "2023-07-23T13:00:00Z", "message": "X"}])
