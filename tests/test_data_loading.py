"""Offline tests for tyredeg.data_loading (FastF1 path and the public API).

No test downloads anything (project rule 9). Instead, ``fastf1.get_session``
is replaced ("monkeypatched") by a function returning :class:`FakeSession`,
a tiny stand-in that behaves like the parts of a FastF1 session we use:
``.event["EventName"]``, ``.load(...)``, ``.laps`` and ``.total_laps``.
"""

import math

import fastf1
import fastf1.exceptions
import pandas as pd
import pytest

from tyredeg import data_loading
from tyredeg.data_loading import (
    RaceDataUnavailableError,
    RaceNotFoundError,
    enable_cache,
    is_green_track_status,
    load_many,
    load_race_laps,
    make_race_id,
    select_laps,
    timedelta_to_seconds,
)
from tyredeg.loading_common import UNIFIED_COLUMNS
from tyredeg.openf1_loading import OpenF1Client


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
def make_fake_laps():
    """Three laps shaped like FastF1's laps table (timedelta columns included).

    Lap 1 is a normal green-flag lap, lap 2 is an in-lap (PitInTime set) and
    lap 3 is the out-lap (PitOutTime set) with a missing lap time (NaT) run
    partly under yellow ("12"). "Sector1Time" is an extra FastF1 column that
    the loader should drop.
    """
    return pd.DataFrame(
        {
            "Driver": ["VER", "VER", "VER"],
            "DriverNumber": ["1", "1", "1"],
            "Team": ["Red Bull Racing"] * 3,
            "LapNumber": [1.0, 2.0, 3.0],
            "LapTime": pd.to_timedelta(["0:01:35.250", "0:01:40.000", None]),
            "Stint": [1.0, 1.0, 2.0],
            "Compound": ["SOFT", "SOFT", "HARD"],
            "TyreLife": [4.0, 5.0, 1.0],
            "FreshTyre": [False, False, True],
            "PitInTime": pd.to_timedelta([None, "1:05:00", None]),
            "PitOutTime": pd.to_timedelta([None, None, "1:05:25.5"]),
            "TrackStatus": ["1", "1", "12"],
            "IsAccurate": [True, False, False],
            "Deleted": [False, False, False],
            "FastF1Generated": [False, False, False],
            "Sector1Time": pd.to_timedelta(["0:00:30", "0:00:31", None]),
        }
    )


class FakeSession:
    """Minimal stand-in for ``fastf1.core.Session``."""

    def __init__(self, event_name="Hungarian Grand Prix", laps=None, total_laps=70,
                 load_error=None):
        self.event = {"EventName": event_name}
        self._laps = laps
        self.total_laps = total_laps
        self._load_error = load_error
        self.load_kwargs = None  # records how load() was called

    def load(self, **kwargs):
        self.load_kwargs = kwargs
        if self._load_error is not None:
            raise self._load_error

    @property
    def laps(self):
        # Real FastF1 raises DataNotLoadedError when the download failed.
        if self._laps is None:
            raise fastf1.exceptions.DataNotLoadedError("not loaded")
        return self._laps


@pytest.fixture
def fake_get_session(monkeypatch):
    """Replace fastf1.get_session; returns a dict to configure the fake per test.

    By default every (year, event) returns a FakeSession whose event name is the
    requested name and whose laps are :func:`make_fake_laps`.
    """
    settings = {"sessions": {}, "calls": []}

    def fake(year, event, identifier):
        settings["calls"].append((year, event, identifier))
        if (year, event) in settings["sessions"]:
            return settings["sessions"][(year, event)]
        return FakeSession(event_name=event, laps=make_fake_laps())

    monkeypatch.setattr(fastf1, "get_session", fake)
    return settings


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def test_timedelta_to_seconds_known_values():
    values = pd.Series(pd.to_timedelta(["0:01:32.500", "0:00:00", "1:00:00.001"]))
    result = timedelta_to_seconds(values)
    assert result.dtype == float
    assert result.tolist() == pytest.approx([92.5, 0.0, 3600.001])


def test_timedelta_to_seconds_keeps_missing_as_nan():
    values = pd.Series(pd.to_timedelta(["0:01:30", None]))
    result = timedelta_to_seconds(values)
    assert len(result) == 2  # the missing lap is kept, not dropped
    assert math.isnan(result.iloc[1])


@pytest.mark.parametrize("bad", [[92.5], pd.Series([92.5]), pd.Series(["1:32"])])
def test_timedelta_to_seconds_rejects_wrong_types(bad):
    with pytest.raises(TypeError):
        timedelta_to_seconds(bad)


@pytest.mark.parametrize(
    "status, expected",
    [("1", True), ("11", True), ("12", False), ("4", False), ("671", False),
     ("", False), (None, False), (float("nan"), False)],
)
def test_is_green_track_status(status, expected):
    assert is_green_track_status(status) is expected


def test_make_race_id_format():
    assert make_race_id(2023, "Hungarian Grand Prix") == "2023_hungarian_grand_prix"
    assert make_race_id(2024, "  São Paulo Grand Prix ") == "2024_s_o_paulo_grand_prix"


def test_make_race_id_rejects_bad_input():
    with pytest.raises(ValueError):
        make_race_id(2023, "!!!")
    with pytest.raises(TypeError):
        make_race_id("2023", "Hungarian Grand Prix")


# ---------------------------------------------------------------------------
# FastF1 path: successful load
# ---------------------------------------------------------------------------
def test_fastf1_load_produces_unified_columns(fake_get_session):
    laps = load_race_laps(2022, "Hungarian Grand Prix")
    assert list(laps.columns[: len(UNIFIED_COLUMNS)]) == list(UNIFIED_COLUMNS)
    for column in ("FreshTyre", "TrackStatus", "IsAccurate", "Deleted", "FastF1Generated"):
        assert column in laps.columns
    assert "Sector1Time" not in laps.columns
    assert "PitInTime" not in laps.columns  # replaced by IsPitInLap
    assert len(laps) == 3  # no laps are removed at the loading stage


def test_fastf1_load_converts_times_and_flags(fake_get_session):
    laps = load_race_laps(2022, "Hungarian Grand Prix")
    assert laps["LapTime"].iloc[0] == pytest.approx(95.25)
    assert math.isnan(laps["LapTime"].iloc[2])  # NaT -> NaN, row kept
    assert laps["IsPitInLap"].tolist() == [False, True, False]
    assert laps["IsPitOutLap"].tolist() == [False, False, True]
    assert laps["IsGreenLap"].tolist() == [True, True, False]


def test_fastf1_load_adds_identifier_columns(fake_get_session):
    laps = load_race_laps(2022, "Hungarian Grand Prix")
    assert (laps["Year"] == 2022).all()
    assert (laps["RaceId"] == "2022_hungarian_grand_prix").all()
    assert (laps["TotalLaps"] == 70.0).all()
    assert (laps["Source"] == "fastf1").all()


def test_fastf1_load_requests_only_lap_data(fake_get_session):
    session = FakeSession(laps=make_fake_laps())
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = session
    load_race_laps(2022, "Hungarian Grand Prix")
    assert session.load_kwargs == {
        "laps": True, "telemetry": False, "weather": False, "messages": True
    }


def test_fastf1_load_without_optional_columns(fake_get_session):
    laps_without_flags = make_fake_laps().drop(columns=["IsAccurate", "Deleted"])
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = FakeSession(
        laps=laps_without_flags
    )
    laps = load_race_laps(2022, "Hungarian Grand Prix")
    assert "IsAccurate" not in laps.columns
    assert "Deleted" not in laps.columns


def test_fastf1_missing_total_laps_gives_nan(fake_get_session):
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = FakeSession(
        laps=make_fake_laps(), total_laps=None
    )
    laps = load_race_laps(2022, "Hungarian Grand Prix")
    assert laps["TotalLaps"].isna().all()


def test_event_name_match_is_case_insensitive(fake_get_session):
    fake_get_session["sessions"][(2022, "hungarian grand prix")] = FakeSession(
        event_name="Hungarian Grand Prix", laps=make_fake_laps()
    )
    laps = load_race_laps(2022, "hungarian grand prix")
    assert (laps["EventName"] == "Hungarian Grand Prix").all()  # official spelling kept


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("year", ["2022", 2022.0, True, None])
def test_rejects_non_int_year(year):
    with pytest.raises(TypeError):
        load_race_laps(year, "Hungarian Grand Prix")


def test_rejects_year_before_2018():
    with pytest.raises(ValueError):
        load_race_laps(2017, "Hungarian Grand Prix")


@pytest.mark.parametrize("event, error", [("", ValueError), ("   ", ValueError), (5, TypeError)])
def test_rejects_bad_event(event, error):
    with pytest.raises(error):
        load_race_laps(2022, event)


@pytest.mark.parametrize("session", ["Q", "FP1", "r", ""])
def test_rejects_unsupported_session(session):
    with pytest.raises(ValueError):
        load_race_laps(2022, "Hungarian Grand Prix", session=session)


def test_rejects_unknown_source():
    with pytest.raises(ValueError, match="source"):
        load_race_laps(2023, "Hungarian Grand Prix", source="ergast")


def test_openf1_source_needs_a_client():
    with pytest.raises(ValueError, match="OpenF1Client"):
        load_race_laps(2023, "Hungarian Grand Prix", source="openf1")


# ---------------------------------------------------------------------------
# FastF1 path: failure handling
# ---------------------------------------------------------------------------
def test_fuzzy_matched_event_is_refused(fake_get_session):
    # Reproduces real FastF1 behaviour seen during development:
    # "Atlantis Grand Prix" was silently matched to the Australian GP.
    fake_get_session["sessions"][(2022, "Atlantis Grand Prix")] = FakeSession(
        event_name="Australian Grand Prix", laps=make_fake_laps()
    )
    with pytest.raises(RaceNotFoundError, match="Australian Grand Prix"):
        load_race_laps(2022, "Atlantis Grand Prix")


def test_race_not_found_is_a_value_error(fake_get_session):
    fake_get_session["sessions"][(2022, "Atlantis Grand Prix")] = FakeSession(
        event_name="Australian Grand Prix"
    )
    # Callers that catch ValueError for bad input also catch this.
    with pytest.raises(ValueError):
        load_race_laps(2022, "Atlantis Grand Prix")


def test_get_session_value_error_becomes_race_not_found(monkeypatch):
    def raise_value_error(year, event, identifier):
        raise ValueError("no such event")

    monkeypatch.setattr(fastf1, "get_session", raise_value_error)
    with pytest.raises(RaceNotFoundError):
        load_race_laps(2022, "Hungarian Grand Prix")


def test_get_session_network_error_becomes_data_unavailable(monkeypatch):
    def raise_connection_error(year, event, identifier):
        raise ConnectionError("offline")

    monkeypatch.setattr(fastf1, "get_session", raise_connection_error)
    with pytest.raises(RaceDataUnavailableError):
        load_race_laps(2022, "Hungarian Grand Prix")


def test_load_exception_becomes_data_unavailable(fake_get_session):
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = FakeSession(
        laps=make_fake_laps(), load_error=ConnectionError("timeout")
    )
    with pytest.raises(RaceDataUnavailableError, match="timeout"):
        load_race_laps(2022, "Hungarian Grand Prix")


def test_laps_not_loaded_becomes_data_unavailable(fake_get_session):
    # Real FastF1: load() only logs warnings, then accessing .laps raises.
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = FakeSession(laps=None)
    with pytest.raises(RaceDataUnavailableError, match="No lap data"):
        load_race_laps(2022, "Hungarian Grand Prix")


def test_empty_laps_becomes_data_unavailable(fake_get_session):
    empty = make_fake_laps().iloc[0:0]
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = FakeSession(laps=empty)
    with pytest.raises(RaceDataUnavailableError, match="no laps"):
        load_race_laps(2022, "Hungarian Grand Prix")


def test_missing_required_column_becomes_data_unavailable(fake_get_session):
    no_compound = make_fake_laps().drop(columns=["Compound"])
    fake_get_session["sessions"][(2022, "Hungarian Grand Prix")] = FakeSession(laps=no_compound)
    with pytest.raises(RaceDataUnavailableError, match="Compound"):
        load_race_laps(2022, "Hungarian Grand Prix")


# ---------------------------------------------------------------------------
# load_many
# ---------------------------------------------------------------------------
def test_load_many_stacks_races_with_ids(fake_get_session):
    laps = load_many([(2022, "Hungarian Grand Prix"), (2021, "Hungarian Grand Prix", "fastf1")])
    assert len(laps) == 6
    assert list(laps.index) == list(range(6))
    assert laps["RaceId"].unique().tolist() == [
        "2022_hungarian_grand_prix", "2021_hungarian_grand_prix"
    ]


def test_load_many_dispatches_openf1_races(fake_get_session, monkeypatch, tmp_path):
    received = []

    def fake_openf1(year, event, client):
        received.append((year, event, client))
        return load_race_laps(2022, "Hungarian Grand Prix").assign(Year=year, Source="openf1")

    monkeypatch.setattr(data_loading, "load_openf1_laps", fake_openf1)
    client = OpenF1Client(tmp_path)
    laps = load_many([(2022, "Hungarian Grand Prix", "fastf1"),
                      (2023, "Hungarian Grand Prix", "openf1")], openf1_client=client)
    assert received == [(2023, "Hungarian Grand Prix", client)]
    assert sorted(laps["Source"].unique()) == ["fastf1", "openf1"]


def test_load_many_rejects_empty_list():
    with pytest.raises(ValueError):
        load_many([])


def test_load_many_rejects_duplicate_race():
    with pytest.raises(ValueError, match="more than once"):
        load_many([(2022, "Hungarian Grand Prix"), (2022, "hungarian grand prix")])


@pytest.mark.parametrize(
    "races", ["2022 Hungary", [2022], [(2022,)], [("2022", "Hungary")], [(2022, "Hungary", "x", 1)]]
)
def test_load_many_rejects_malformed_races(races):
    with pytest.raises(TypeError):
        load_many(races)


def test_load_many_rejects_unknown_source():
    with pytest.raises(ValueError, match="source"):
        load_many([(2022, "Hungarian Grand Prix", "ergast")])


def test_load_many_validates_everything_before_downloading(fake_get_session):
    # The bad second entry must be caught before the first race is fetched.
    with pytest.raises(ValueError):
        load_many([(2022, "Hungarian Grand Prix"), (2010, "Hungarian Grand Prix")])
    assert fake_get_session["calls"] == []


def test_load_many_propagates_failure(fake_get_session):
    fake_get_session["sessions"][(2021, "Hungarian Grand Prix")] = FakeSession(laps=None)
    with pytest.raises(RaceDataUnavailableError):
        load_many([(2022, "Hungarian Grand Prix"), (2021, "Hungarian Grand Prix")])


# ---------------------------------------------------------------------------
# select_laps
# ---------------------------------------------------------------------------
def make_mixed_laps():
    return pd.DataFrame(
        {
            "Team": ["Red Bull Racing", "Red Bull Racing", "Ferrari", "Red Bull Racing"],
            "Driver": ["VER", "PER", "LEC", "VER"],
            "Compound": ["HARD", "HARD", "HARD", "SOFT"],
            "PirelliCompound": ["C3", "C3", "C3", "C5"],
            "LapTime": [95.0, 95.5, 95.2, 94.0],
        }
    )


def test_select_laps_by_team_and_compound():
    selected = select_laps(make_mixed_laps(), teams=["Red Bull Racing"], compounds=["HARD"])
    assert selected["Driver"].tolist() == ["VER", "PER"]
    assert list(selected.index) == [0, 1]


def test_select_laps_by_pirelli_compound():
    selected = select_laps(make_mixed_laps(), pirelli_compounds=["C3"])
    assert selected["Driver"].tolist() == ["VER", "PER", "LEC"]


def test_select_laps_pirelli_filter_needs_column():
    with pytest.raises(ValueError, match="PirelliCompound"):
        select_laps(make_mixed_laps().drop(columns=["PirelliCompound"]), pirelli_compounds=["C3"])


def test_select_laps_none_means_no_filter():
    laps = make_mixed_laps()
    assert len(select_laps(laps)) == len(laps)


def test_select_laps_by_driver():
    selected = select_laps(make_mixed_laps(), drivers=["VER"])
    assert selected["Compound"].tolist() == ["HARD", "SOFT"]


def test_select_laps_unknown_compound():
    with pytest.raises(ValueError, match="Unknown compound"):
        select_laps(make_mixed_laps(), compounds=["SUPERSOFT"])


def test_select_laps_no_match_raises():
    with pytest.raises(ValueError, match="No laps match"):
        select_laps(make_mixed_laps(), teams=["Williams"])


def test_select_laps_rejects_bad_inputs():
    with pytest.raises(TypeError):
        select_laps("not a dataframe")
    with pytest.raises(ValueError):
        select_laps(pd.DataFrame())
    with pytest.raises(ValueError):
        select_laps(make_mixed_laps(), teams=[])
    with pytest.raises(TypeError):
        select_laps(make_mixed_laps(), teams="Red Bull Racing")


# ---------------------------------------------------------------------------
# enable_cache
# ---------------------------------------------------------------------------
def test_enable_cache_creates_folder_and_calls_fastf1(tmp_path, monkeypatch):
    received = []
    monkeypatch.setattr(fastf1.Cache, "enable_cache", lambda path: received.append(path))
    target = tmp_path / "nested" / "cache"
    result = enable_cache(target)
    assert target.is_dir()
    assert result == target.resolve()
    assert received == [str(target.resolve())]


@pytest.mark.parametrize("bad, error", [("", ValueError), (None, TypeError), (42, TypeError)])
def test_enable_cache_rejects_bad_path(bad, error):
    with pytest.raises(error):
        enable_cache(bad)
