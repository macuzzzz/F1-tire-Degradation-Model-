"""Offline tests for tyredeg.tyre_allocation (SOFT/MEDIUM/HARD -> Pirelli C-number)."""

from pathlib import Path

import pandas as pd
import pytest

from tyredeg.tyre_allocation import add_pirelli_compound, compound_number, load_allocation

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOCATION_FILE = REPO_ROOT / "reference" / "pirelli_allocation.csv"


def write_allocation(tmp_path, rows):
    """Write a small allocation CSV (with a comment line) and return its path."""
    path = tmp_path / "allocation.csv"
    header = "# test file\nyear,event,hard,medium,soft,source_url,cross_checked\n"
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The committed reference file
# ---------------------------------------------------------------------------
def test_reference_file_is_valid():
    allocation = load_allocation(ALLOCATION_FILE)
    assert len(allocation) > 0
    assert allocation["source_url"].str.startswith("http").all()


@pytest.mark.parametrize(
    "year, expected",
    [(2022, ["C2", "C3", "C4"]), (2023, ["C3", "C4", "C5"]),
     (2024, ["C3", "C4", "C5"]), (2025, ["C3", "C4", "C5"])],
)
def test_reference_hungary_matches_pirelli(year, expected):
    # Cross-checked against Pirelli / formula1.com (DECISIONS.md D4 amendment 2).
    allocation = load_allocation(ALLOCATION_FILE)
    row = allocation[(allocation["year"] == year) & (allocation["event"] == "Hungarian Grand Prix")]
    assert row[["hard", "medium", "soft"]].values.tolist() == [expected]
    assert row["cross_checked"].item() == "yes"


# ---------------------------------------------------------------------------
# compound_number
# ---------------------------------------------------------------------------
def test_compound_number():
    assert compound_number("C0") == 0
    assert compound_number("C6") == 6


@pytest.mark.parametrize("bad", ["C7", "c3", "3", "HARD", None, 3])
def test_compound_number_rejects_bad_codes(bad):
    # Codes other than C1-C6 are rejected.
    with pytest.raises(ValueError):
        compound_number(bad)


# ---------------------------------------------------------------------------
# load_allocation validation
# ---------------------------------------------------------------------------
def test_gap_allocation_is_allowed(tmp_path):
    # Pirelli sometimes skips a compound (e.g. C1/C3/C4 at 2025 Austin).
    path = write_allocation(tmp_path, ["2025,United States Grand Prix,C1,C3,C4,https://x,no"])
    assert len(load_allocation(path)) == 1


def test_wrong_order_is_rejected(tmp_path):
    # Hard, medium and soft must be in increasing C-number order.
    path = write_allocation(tmp_path, ["2023,Test Grand Prix,C3,C2,C4,https://x,no"])
    with pytest.raises(ValueError, match="hard < medium < soft"):
        load_allocation(path)


def test_invalid_code_is_rejected(tmp_path):
    # An unknown compound code is reported by name.
    path = write_allocation(tmp_path, ["2023,Test Grand Prix,C1,C2,C9,https://x,no"])
    with pytest.raises(ValueError, match="C9"):
        load_allocation(path)


def test_duplicate_race_is_rejected(tmp_path):
    # The same race twice (in any case) is rejected.
    path = write_allocation(tmp_path, [
        "2023,Test Grand Prix,C1,C2,C3,https://x,no",
        "2023,test grand prix,C2,C3,C4,https://x,no",
    ])
    with pytest.raises(ValueError, match="more than once"):
        load_allocation(path)


def test_missing_column_is_rejected(tmp_path):
    # A missing column is reported by name.
    path = tmp_path / "bad.csv"
    path.write_text("year,event,hard\n2023,Test,C1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_allocation(path)


def test_missing_file(tmp_path):
    # A missing allocation file gives FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        load_allocation(tmp_path / "nope.csv")


# ---------------------------------------------------------------------------
# add_pirelli_compound
# ---------------------------------------------------------------------------
def make_laps():
    return pd.DataFrame(
        {
            "Year": [2022, 2022, 2023, 2023, 2023],
            "EventName": ["Hungarian Grand Prix"] * 5,
            "Compound": ["MEDIUM", "HARD", "HARD", "SOFT", "INTERMEDIATE"],
        }
    )


def test_add_pirelli_compound_maps_labels_per_year():
    result = add_pirelli_compound(make_laps(), load_allocation(ALLOCATION_FILE))
    # C3 is the MEDIUM in 2022 but the HARD in 2023 at the Hungaroring.
    assert result["PirelliCompound"].tolist() == ["C3", "C2", "C3", "C5", None]


def test_add_pirelli_compound_does_not_modify_input():
    # Adding the Pirelli compound works on a copy, so the caller's table is unchanged.
    laps = make_laps()
    add_pirelli_compound(laps, load_allocation(ALLOCATION_FILE))
    assert "PirelliCompound" not in laps.columns


def test_missing_race_in_allocation_raises(tmp_path):
    # A race missing from the allocation table is reported clearly.
    path = write_allocation(tmp_path, ["2022,Hungarian Grand Prix,C2,C3,C4,https://x,yes"])
    with pytest.raises(ValueError, match="No Pirelli allocation"):
        add_pirelli_compound(make_laps(), load_allocation(path))


def test_add_pirelli_compound_input_checks():
    # Invalid tables and missing columns are rejected.
    allocation = load_allocation(ALLOCATION_FILE)
    with pytest.raises(TypeError):
        add_pirelli_compound("laps", allocation)
    with pytest.raises(ValueError, match="Compound"):
        add_pirelli_compound(make_laps().drop(columns=["Compound"]), allocation)
