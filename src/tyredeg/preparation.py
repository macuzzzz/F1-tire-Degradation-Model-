"""Turn raw downloaded laps into clean, fuel-corrected laps ready for modelling.

This runs the Phase 1-2 chain in the approved order (DECISIONS.md D17):

    load races -> add Pirelli compound -> fill race length -> fuel-correct
    -> clean -> add stint labels

so that every later stage (cross-validation, final test, strategy) prepares
its data in exactly the same way. Which races are passed in decides what the
caller can see: the cross-validation stage passes ONLY the training races, so
the test race is never even loaded during model selection (D55).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tyredeg.cleaning import clean_laps
from tyredeg.data_loading import enable_cache, load_many
from tyredeg.fuel_correction import add_fuel_corrected_times, fill_total_laps
from tyredeg.models.common import stint_labels_from_laps
from tyredeg.openf1_loading import OpenF1Client
from tyredeg.tyre_allocation import add_pirelli_compound, load_allocation

STINT_COLUMN = "StintId"


@dataclass(frozen=True)
class PreparedLaps:
    """Output of :func:`prepare_laps`.

    Attributes
    ----------
    all_laps : pandas.DataFrame
        Every lap (before cleaning) with ``PirelliCompound``, filled
        ``TotalLaps`` and ``FuelCorrectedTime`` (needed for the pit loss).
    clean : pandas.DataFrame
        Laps that passed every cleaning rule, plus a ``StintId`` column.
    cleaning_report : pandas.DataFrame
        Laps removed per rule (see :func:`tyredeg.cleaning.clean_laps`).
    """

    all_laps: pd.DataFrame
    clean: pd.DataFrame
    cleaning_report: pd.DataFrame


def prepare_laps(config, races):
    """Load and prepare the given races.

    Parameters
    ----------
    config : Config
        The validated project configuration.
    races : sequence of RaceSpec
        Races to load, e.g. ``config.train_races``. Must be non-empty.

    Returns
    -------
    PreparedLaps

    Raises
    ------
    ValueError
        If ``races`` is empty or a setting needed here (k_fuel, cleaning
        thresholds) is not set.
    RaceNotFoundError, RaceDataUnavailableError
        If a race cannot be loaded.

    Example
    -------
    >>> prepared = prepare_laps(config, config.train_races)  # doctest: +SKIP
    """
    races = list(races)
    if not races:
        raise ValueError("races must contain at least one race.")
    if config.k_fuel is None:
        raise ValueError("fuel.k_fuel must be set in config.yaml.")
    enable_cache(config.fastf1_cache_dir)
    client = OpenF1Client(config.openf1_cache_dir, config.openf1_request_delay_s,
                          config.openf1_max_retries)
    laps = load_many([(race.year, race.event, race.source) for race in races],
                     openf1_client=client)
    laps = add_pirelli_compound(laps, load_allocation(config.allocation_file))
    laps = fill_total_laps(laps, config.total_laps_override)
    laps = add_fuel_corrected_times(laps, config.k_fuel)
    clean, report = clean_laps(laps, config)
    clean = clean.copy()
    clean[STINT_COLUMN] = stint_labels_from_laps(clean)
    return PreparedLaps(all_laps=laps, clean=clean, cleaning_report=report)
