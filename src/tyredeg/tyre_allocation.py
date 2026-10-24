"""Map relative tyre labels (SOFT/MEDIUM/HARD) to Pirelli compounds (C1-C6).

Why this is needed
------------------
Timing data only says whether a tyre was the event's SOFT, MEDIUM or HARD.
Pirelli, however, chooses a different set of three compounds for each event.
At the Hungarian Grand Prix, for example, the C3 compound was the MEDIUM in
2022 (allocation C2/C3/C4) but the HARD in 2023-2025 (allocation C3/C4/C5).
The project studies one physical compound, C3 (DECISIONS.md D4), so every lap
needs its Pirelli compound, looked up per race from
``reference/pirelli_allocation.csv`` (D16).

File format of the allocation table
-----------------------------------
CSV with lines starting with ``#`` as comments and the columns:
``year, event, hard, medium, soft, source_url, cross_checked``,
where hard/medium/soft hold compound codes such as ``"C3"``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ALLOCATION_COLUMNS = ("year", "event", "hard", "medium", "soft", "source_url", "cross_checked")

# Relative label in the laps table -> column of the allocation table.
LABEL_TO_COLUMN = {"HARD": "hard", "MEDIUM": "medium", "SOFT": "soft"}

# C0 (hardest, 2023-2024 only) to C6 (softest, 2025 only).
COMPOUND_PATTERN = re.compile(r"^C[0-6]$")


def compound_number(code):
    """Return the number in a compound code, e.g. ``compound_number("C3") == 3``.

    Raises
    ------
    ValueError
        If ``code`` is not of the form ``"C0"`` ... ``"C6"``.

    Example
    -------
    >>> compound_number("C4")
    4
    """
    if not isinstance(code, str) or COMPOUND_PATTERN.match(code) is None:
        raise ValueError(f"Invalid Pirelli compound code {code!r}; expected 'C0' to 'C6'.")
    return int(code[1])


def _check_allocation_rows(allocation):
    """Raise ValueError if any row has a bad code or an impossible order."""
    for row in allocation.itertuples(index=False):
        label = f"{row.year} {row.event}"
        hard = compound_number(row.hard)
        medium = compound_number(row.medium)
        soft = compound_number(row.soft)
        # A lower C number is a harder compound, so the "hard" tyre must have
        # the lowest number. Gaps (e.g. C1/C3/C4) are allowed: Pirelli used them.
        if not hard < medium < soft:
            raise ValueError(
                f"Allocation for {label} must satisfy hard < medium < soft, "
                f"got {row.hard}/{row.medium}/{row.soft}."
            )

    keys = allocation["year"].astype(str) + "|" + allocation["event"].str.casefold()
    duplicated = allocation.loc[keys.duplicated(), ["year", "event"]]
    if not duplicated.empty:
        raise ValueError(f"Allocation table lists races more than once: {duplicated.values.tolist()}")


def load_allocation(path):
    """Read and validate the Pirelli allocation table.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the CSV file, e.g. ``"reference/pirelli_allocation.csv"``.

    Returns
    -------
    pandas.DataFrame
        One row per race with the columns ``ALLOCATION_COLUMNS``.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If a column is missing, a compound code is invalid, the compounds are
        not ordered hard < medium < soft, or a race appears twice.

    Example
    -------
    >>> allocation = load_allocation("reference/pirelli_allocation.csv")
    >>> row = allocation[(allocation.year == 2022)
    ...                  & (allocation.event == "Hungarian Grand Prix")]
    >>> row[["hard", "medium", "soft"]].values.tolist()
    [['C2', 'C3', 'C4']]
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Allocation file not found: {path.resolve()}")
    allocation = pd.read_csv(path, comment="#", encoding="utf-8")

    missing = [column for column in ALLOCATION_COLUMNS if column not in allocation.columns]
    if missing:
        raise ValueError(f"Allocation file {path} is missing columns: {missing}")
    if allocation.empty:
        raise ValueError(f"Allocation file {path} has no rows.")

    _check_allocation_rows(allocation)
    return allocation[list(ALLOCATION_COLUMNS)]


def add_pirelli_compound(laps, allocation):
    """Return a copy of ``laps`` with a ``PirelliCompound`` column (e.g. ``"C3"``).

    Parameters
    ----------
    laps : pandas.DataFrame
        Unified laps table (needs ``Year``, ``EventName`` and ``Compound``).
    allocation : pandas.DataFrame
        Output of :func:`load_allocation`.

    Returns
    -------
    pandas.DataFrame
        Copy of ``laps`` with the extra column. Laps on INTERMEDIATE or WET
        tyres, or with an unknown compound, get ``None``: they have no C number.

    Raises
    ------
    TypeError
        If ``laps`` or ``allocation`` is not a DataFrame.
    ValueError
        If a needed column is missing, or a race in ``laps`` has no row in the
        allocation table (failing loudly avoids silently dropping a race).

    Example
    -------
    >>> laps = add_pirelli_compound(laps, load_allocation(
    ...     "reference/pirelli_allocation.csv"))  # doctest: +SKIP
    >>> laps.loc[laps.Year == 2023, ["Compound", "PirelliCompound"]].drop_duplicates()  # doctest: +SKIP
    """
    if not isinstance(laps, pd.DataFrame) or not isinstance(allocation, pd.DataFrame):
        raise TypeError("laps and allocation must both be pandas DataFrames.")
    for column in ("Year", "EventName", "Compound"):
        if column not in laps.columns:
            raise ValueError(f"laps is missing column {column!r}.")

    # Build a lookup {(year, lower-case event name): row} for fast access.
    lookup = {}
    for row in allocation.itertuples(index=False):
        lookup[(int(row.year), str(row.event).casefold())] = row

    races = laps[["Year", "EventName"]].drop_duplicates()
    for year, event in races.itertuples(index=False):
        if (int(year), str(event).casefold()) not in lookup:
            raise ValueError(f"No Pirelli allocation found for {year} {event!r}.")

    pirelli = []
    for year, event, label in zip(laps["Year"], laps["EventName"], laps["Compound"]):
        column = LABEL_TO_COLUMN.get(label)  # None for INTERMEDIATE/WET/unknown
        if column is None:
            pirelli.append(None)
        else:
            row = lookup[(int(year), str(event).casefold())]
            pirelli.append(getattr(row, column))

    result = laps.copy()
    result["PirelliCompound"] = pirelli
    return result
