"""Offline tests for tyredeg.openf1_loading.

Nothing is downloaded (rule 9):
- the HTTP layer is replaced by monkeypatching ``requests.get`` with
  :class:`FakeResponse` objects, and ``time.sleep`` so tests run instantly;
- the race-building tests use :class:`FakeClient`, which returns canned
  OpenF1 records for a small, hand-checkable race scenario.
"""

import json
import math

import pandas as pd
import pytest

from tyredeg import openf1_loading
from tyredeg.loading_common import UNIFIED_COLUMNS, RaceDataUnavailableError, RaceNotFoundError
from tyredeg.openf1_loading import (
    OpenF1Client,
    build_laps_rows,
    find_race_session,
    load_openf1_laps,
    race_date_utc,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code, data=None, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        return self._data


@pytest.fixture
def no_sleep(monkeypatch):
    """Record sleeps instead of waiting."""
    sleeps = []
    monkeypatch.setattr(openf1_loading.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def fake_requests(monkeypatch, responses):
    """Make requests.get return the given responses in order; returns the call log."""
    calls = []
    queue = list(responses)

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return queue.pop(0)

    monkeypatch.setattr(openf1_loading.requests, "get", fake_get)
    return calls


# A small race: VER does laps 1-4 (pit on lap 3), LEC one lap without stint data.
RACE_START = "2023-07-23T13:00:00+00:00"
SESSIONS = [
    {"session_key": 1111, "date_start": "2023-07-22T14:00:00+00:00", "is_cancelled": False},
    {"session_key": 9999, "date_start": RACE_START, "is_cancelled": False},
]
DRIVERS = [
    {"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull Racing"},
    {"driver_number": 16, "name_acronym": "LEC", "team_name": "Ferrari"},
]
LAPS = [
    {"driver_number": 1, "lap_number": 1, "lap_duration": None,
     "is_pit_out_lap": False, "date_start": None},
    {"driver_number": 1, "lap_number": 2, "lap_duration": 80.0,
     "is_pit_out_lap": False, "date_start": "2023-07-23T13:04:30+00:00"},
    {"driver_number": 1, "lap_number": 3, "lap_duration": 85.0,
     "is_pit_out_lap": False, "date_start": "2023-07-23T13:05:50+00:00"},
    {"driver_number": 1, "lap_number": 4, "lap_duration": 100.0,
     "is_pit_out_lap": True, "date_start": "2023-07-23T13:07:15+00:00"},
    {"driver_number": 16, "lap_number": 2, "lap_duration": 81.0,
     "is_pit_out_lap": False, "date_start": "2023-07-23T13:04:31+00:00"},
]
STINTS = [
    {"driver_number": 1, "stint_number": 1, "compound": "MEDIUM",
     "lap_start": 1, "lap_end": 3, "tyre_age_at_start": 3},
    {"driver_number": 1, "stint_number": 2, "compound": "HARD",
     "lap_start": 4, "lap_end": 70, "tyre_age_at_start": 0},
]
PITS = [{"driver_number": 1, "lap_number": 3}]
# A yellow flag from 13:05:00 to 13:05:10 overlaps lap 2 of both drivers.
RACE_CONTROL = [
    {"date": "2023-07-23T13:05:00+00:00", "category": "Flag", "flag": "YELLOW",
     "scope": "Sector", "sector": 4, "message": "YELLOW IN TRACK SECTOR 4"},
    {"date": "2023-07-23T13:05:10+00:00", "category": "Flag", "flag": "CLEAR",
     "scope": "Sector", "sector": 4, "message": "CLEAR IN TRACK SECTOR 4"},
]


class FakeClient(OpenF1Client):
    """OpenF1Client that serves canned records instead of downloading."""

    def __init__(self, data):
        super().__init__("unused-cache-dir")
        self.data = data
        self.requests = []

    def get(self, endpoint, **params):
        self.requests.append((endpoint, params))
        return self.data[endpoint]


def scenario_client():
    return FakeClient({"sessions": SESSIONS, "drivers": DRIVERS, "laps": LAPS,
                       "stints": STINTS, "pit": PITS, "race_control": RACE_CONTROL})


class FakeEvent(dict):
    """Stand-in for fastf1.events.Event (a dict with get_session_date)."""

    def get_session_date(self, identifier, utc=False):
        return pd.Timestamp("2023-07-23 13:00:00")


@pytest.fixture
def fake_schedule(monkeypatch):
    def fake_get_event(year, event):
        return FakeEvent(EventName="Hungarian Grand Prix")

    monkeypatch.setattr(openf1_loading.fastf1, "get_event", fake_get_event)


# ---------------------------------------------------------------------------
# OpenF1Client: caching, retries, errors
# ---------------------------------------------------------------------------
def test_client_downloads_once_then_uses_cache(tmp_path, monkeypatch, no_sleep):
    calls = fake_requests(monkeypatch, [FakeResponse(200, [{"lap_number": 1}])])
    client = OpenF1Client(tmp_path, request_delay_s=0.4)
    first = client.get("laps", session_key=9999)
    second = client.get("laps", session_key=9999)  # served from the cache
    assert first == second == [{"lap_number": 1}]
    assert len(calls) == 1
    assert client.downloads == 1
    assert no_sleep == [0.4]  # polite delay after the one real download
    cached = tmp_path / "laps" / "session_key=9999.json"
    assert json.loads(cached.read_text(encoding="utf-8")) == [{"lap_number": 1}]


def test_cache_path_is_independent_of_parameter_order(tmp_path):
    client = OpenF1Client(tmp_path)
    assert client.cache_path("laps", {"b": 2, "a": 1}) == client.cache_path("laps", {"a": 1, "b": 2})


def test_404_means_no_data(tmp_path, monkeypatch, no_sleep):
    fake_requests(monkeypatch, [FakeResponse(404)])
    assert OpenF1Client(tmp_path).get("drivers", session_key=1) == []


def test_429_is_retried_with_backoff(tmp_path, monkeypatch, no_sleep):
    calls = fake_requests(monkeypatch, [FakeResponse(429), FakeResponse(429), FakeResponse(200, [1])])
    client = OpenF1Client(tmp_path, request_delay_s=0.0, max_retries=5)
    assert client.get("pit", session_key=1) == [1]
    assert len(calls) == 3
    assert [s for s in no_sleep if s > 0] == [2.0, 4.0]  # waits grow with each attempt


def test_429_gives_up_after_max_retries(tmp_path, monkeypatch, no_sleep):
    fake_requests(monkeypatch, [FakeResponse(429)] * 2)
    client = OpenF1Client(tmp_path, max_retries=2)
    with pytest.raises(RaceDataUnavailableError, match="rate-limiting"):
        client.get("pit", session_key=1)


def test_401_live_session_is_reported_clearly(tmp_path, monkeypatch, no_sleep):
    fake_requests(monkeypatch, [FakeResponse(401, text="Live F1 session in progress.")])
    with pytest.raises(RaceDataUnavailableError, match="live F1 session"):
        OpenF1Client(tmp_path).get("laps", session_key=1)
    # A refused request must not leave a (wrong) cache file behind.
    assert not (tmp_path / "laps").exists()


def test_other_http_error(tmp_path, monkeypatch, no_sleep):
    fake_requests(monkeypatch, [FakeResponse(500)])
    with pytest.raises(RaceDataUnavailableError, match="500"):
        OpenF1Client(tmp_path).get("laps", session_key=1)


def test_network_failure(tmp_path, monkeypatch, no_sleep):
    def broken_get(url, params=None, timeout=None):
        raise openf1_loading.requests.ConnectionError("offline")

    monkeypatch.setattr(openf1_loading.requests, "get", broken_get)
    with pytest.raises(RaceDataUnavailableError, match="Could not reach"):
        OpenF1Client(tmp_path).get("laps", session_key=1)


@pytest.mark.parametrize(
    "kwargs, error",
    [({"request_delay_s": -1}, ValueError), ({"request_delay_s": "fast"}, TypeError),
     ({"max_retries": 0}, ValueError), ({"max_retries": 1.5}, TypeError)],
)
def test_client_rejects_bad_settings(tmp_path, kwargs, error):
    with pytest.raises(error):
        OpenF1Client(tmp_path, **kwargs)


def test_client_rejects_bad_cache_dir():
    with pytest.raises(TypeError):
        OpenF1Client("")


# ---------------------------------------------------------------------------
# Finding the race session
# ---------------------------------------------------------------------------
def test_find_race_session_matches_date():
    session = find_race_session(scenario_client(), 2023, pd.Timestamp("2023-07-23 13:00"))
    assert session["session_key"] == 9999


def test_find_race_session_skips_cancelled_and_reports_missing():
    client = FakeClient({"sessions": [dict(SESSIONS[1], is_cancelled=True)]})
    with pytest.raises(RaceDataUnavailableError, match="found 0"):
        find_race_session(client, 2023, pd.Timestamp("2023-07-23 13:00"))


def test_race_date_utc_refuses_fuzzy_match(monkeypatch):
    monkeypatch.setattr(openf1_loading.fastf1, "get_event",
                        lambda year, event: FakeEvent(EventName="Australian Grand Prix"))
    with pytest.raises(RaceNotFoundError, match="Australian"):
        race_date_utc(2023, "Atlantis Grand Prix")


def test_race_date_utc_returns_name_and_date(fake_schedule):
    name, start = race_date_utc(2023, "hungarian grand prix")
    assert name == "Hungarian Grand Prix"
    assert start == pd.Timestamp("2023-07-23 13:00:00")


# ---------------------------------------------------------------------------
# Building the laps
# ---------------------------------------------------------------------------
def scenario_rows():
    rows = build_laps_rows(LAPS, DRIVERS, STINTS, PITS, RACE_CONTROL)
    return rows.set_index(["Driver", "LapNumber"])


def test_lap_times_and_missing_values():
    rows = scenario_rows()
    assert math.isnan(rows.loc[("VER", 1), "LapTime"])
    assert rows.loc[("VER", 2), "LapTime"] == 80.0


def test_tyre_life_counts_laps_completed_by_end_of_lap():
    rows = scenario_rows()
    # Stint 1 started on a set with 3 laps already completed.
    assert rows.loc[("VER", 1), "TyreLife"] == 4
    assert rows.loc[("VER", 3), "TyreLife"] == 6
    # New set on lap 4: 1 lap completed by the end of the out-lap (as FastF1).
    assert rows.loc[("VER", 4), "TyreLife"] == 1
    assert rows.loc[("VER", 4), "Compound"] == "HARD"
    assert rows.loc[("VER", 4), "Stint"] == 2


def test_pit_flags():
    rows = scenario_rows()
    assert rows["IsPitInLap"].sum() == 1 and rows.loc[("VER", 3), "IsPitInLap"]
    assert rows["IsPitOutLap"].sum() == 1 and rows.loc[("VER", 4), "IsPitOutLap"]


def test_green_flags_from_race_control():
    rows = scenario_rows()
    assert not rows.loc[("VER", 1), "IsGreenLap"]  # no timing -> not provably green
    assert not rows.loc[("VER", 2), "IsGreenLap"]  # overlaps the yellow flag
    assert rows.loc[("VER", 3), "IsGreenLap"]
    assert rows.loc[("VER", 4), "IsGreenLap"]
    assert not rows.loc[("LEC", 2), "IsGreenLap"]


def test_lap_without_stint_data():
    rows = scenario_rows()
    assert rows.loc[("LEC", 2), "Team"] == "Ferrari"
    assert rows.loc[("LEC", 2), "Compound"] is None
    assert math.isnan(rows.loc[("LEC", 2), "TyreLife"])


def test_build_laps_rows_needs_laps():
    with pytest.raises(RaceDataUnavailableError):
        build_laps_rows([], DRIVERS, STINTS, PITS, RACE_CONTROL)


# ---------------------------------------------------------------------------
# load_openf1_laps (end to end with fakes)
# ---------------------------------------------------------------------------
def test_load_openf1_laps_returns_unified_table(fake_schedule):
    client = scenario_client()
    laps = load_openf1_laps(2023, "Hungarian Grand Prix", client)
    assert list(laps.columns) == list(UNIFIED_COLUMNS)
    assert (laps["Source"] == "openf1").all()
    assert (laps["RaceId"] == "2023_hungarian_grand_prix").all()
    assert laps["TotalLaps"].isna().all()  # OpenF1 does not report race length
    assert laps["DriverNumber"].tolist() == ["16", "1", "1", "1", "1"]  # sorted by driver code
    requested = {endpoint for endpoint, _ in client.requests}
    assert requested == {"sessions", "laps", "drivers", "stints", "pit", "race_control"}


def test_load_openf1_laps_rejects_years_before_2023():
    with pytest.raises(ValueError, match="2023"):
        load_openf1_laps(2022, "Hungarian Grand Prix", scenario_client())


def test_load_openf1_laps_needs_a_client():
    with pytest.raises(TypeError):
        load_openf1_laps(2023, "Hungarian Grand Prix", client="not a client")
