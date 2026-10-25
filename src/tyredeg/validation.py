"""Validation: metrics, race-wise splits, cross-validation, model selection and checks.

Why splits are by RACE, never by random lap (DECISIONS.md D48)
---------------------------------------------------------------
Laps are not independent. Laps of one stint share the stint's base pace
(offset) and have correlated noise (lag-1 residual correlation ~0.45, D45),
and all stints of a race share track, weather and car-development conditions.
If laps were split at random, every test lap would have neighbours from the
same stint and race in the training set: the model could effectively "look
up" the answer and the measured error would be far too optimistic. Holding
out WHOLE races measures what we actually need - how well the model predicts
a race it has never seen.

How a held-out stint is predicted (D49)
---------------------------------------
Its base pace is unknown, so the first ``anchor_laps`` (3) clean laps of the
stint are used to estimate it: offset = mean(lap_time - d(tyre_age)) over
those laps. The remaining laps are predicted as offset + d(tyre_age) and only
they are scored. This mirrors a real race, where a team knows its pace after
a few laps on a new set.

Model selection (D48) uses leave-one-race-out cross-validation on the
TRAINING races only. The test race is evaluated once, by a separate stage
that refuses to run before the selection has been written (D55).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from tyredeg.models.common import check_compound
from tyredeg.models.knn import KNNDegradationModel
from tyredeg.models.polynomial import PolynomialDegradationModel
from tyredeg.models.wear_ode import WearODEModel
from tyredeg.numerics.least_squares import fit_linear_least_squares

AGE_COLUMN = "TyreLife"
TIME_COLUMN = "FuelCorrectedTime"
LAP_COLUMN = "LapNumber"
RACE_COLUMN = "RaceId"
STINT_COLUMN = "StintId"
BASELINE_NAME = "baseline (no degradation)"


# ---------------------------------------------------------------------------
# 1. Metrics (D47)
# ---------------------------------------------------------------------------
def _errors(actual, predicted):
    """Return (actual, predicted) as checked float arrays."""
    # Turn both inputs into 1-D float arrays and check they are non-empty, equal-length and finite.
    actual = np.asarray(actual, dtype=float).reshape(-1)
    predicted = np.asarray(predicted, dtype=float).reshape(-1)
    if actual.size == 0:
        raise ValueError("actual must not be empty.")
    if actual.size != predicted.size:
        raise ValueError(f"actual and predicted differ in length ({actual.size} vs {predicted.size}).")
    if not (np.all(np.isfinite(actual)) and np.all(np.isfinite(predicted))):
        raise ValueError("actual and predicted must not contain NaN or infinite values.")
    return actual, predicted


def rmse(actual, predicted):
    """Root-mean-square error sqrt(mean((predicted - actual)^2)) [s].

    The primary metric (D47): it is the quantity least squares minimises and
    it penalises large misses more than small ones.

    Parameters
    ----------
    actual : array_like of float
        Observed lap times [s]; non-empty and finite.
    predicted : array_like of float
        Predicted lap times [s]; same length, finite.

    Returns
    -------
    float
        RMSE [s], >= 0.

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> round(rmse([1, 2, 3, 4], [1, 3, 2, 6]), 6)
    1.224745
    """
    # Check the inputs, then the root of the mean squared error.
    actual, predicted = _errors(actual, predicted)
    return float(np.sqrt(np.mean((predicted - actual) ** 2)))


def mae(actual, predicted):
    """Mean absolute error mean(|predicted - actual|) [s].

    Parameters
    ----------
    actual : array_like of float
        Observed lap times [s]; non-empty and finite.
    predicted : array_like of float
        Predicted lap times [s]; same length, finite.

    Returns
    -------
    float
        MAE [s], >= 0.

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> mae([1, 2, 3, 4], [1, 3, 2, 6])
    1.0
    """
    # Check the inputs, then the average size of the errors (ignoring sign).
    actual, predicted = _errors(actual, predicted)
    return float(np.mean(np.abs(predicted - actual)))


def max_abs_error(actual, predicted):
    """Largest |predicted - actual| [s].

    Parameters
    ----------
    actual : array_like of float
        Observed lap times [s]; non-empty and finite.
    predicted : array_like of float
        Predicted lap times [s]; same length, finite.

    Returns
    -------
    float
        Largest absolute error [s], >= 0.

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> max_abs_error([1, 2, 3, 4], [1, 3, 2, 6])
    2.0
    """
    # Check the inputs, then the single worst error.
    actual, predicted = _errors(actual, predicted)
    return float(np.max(np.abs(predicted - actual)))


def bias(actual, predicted):
    """Mean signed error mean(predicted - actual) [s/lap]; > 0 means too slow.

    Strategy adds up lap times, so a consistent bias accumulates over a stint
    (0.1 s/lap over 35 laps = 3.5 s); hence the acceptance criterion (D51).

    Parameters
    ----------
    actual : array_like of float
        Observed lap times [s]; non-empty and finite.
    predicted : array_like of float
        Predicted lap times [s]; same length, finite.

    Returns
    -------
    float
        Bias [s/lap]; positive when the model predicts slower laps than observed.

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> bias([1, 2, 3, 4], [1, 3, 2, 6])
    0.5
    """
    # Check the inputs, then the average signed error (positive = predicted too slow).
    actual, predicted = _errors(actual, predicted)
    return float(np.mean(predicted - actual))


def r_squared(actual, predicted):
    """Coefficient of determination 1 - SS_res / SS_tot (NaN if actual is constant).

    Note: anchoring each stint's base pace already explains much of the
    lap-time variance, so R^2 is high even for the baseline; it is reported
    but not used for selection (D47).

    Parameters
    ----------
    actual : array_like of float
        Observed lap times [s]; non-empty and finite.
    predicted : array_like of float
        Predicted lap times [s]; same length, finite.

    Returns
    -------
    float
        R^2 (dimensionless, <= 1; negative if worse than the mean); NaN if ``actual`` is constant.

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> round(r_squared([1, 2, 3, 4], [1, 3, 2, 6]), 6)
    -0.2
    """
    # Total variation of the actual values around their mean.
    actual, predicted = _errors(actual, predicted)
    total = float(np.sum((actual - actual.mean()) ** 2))
    # A constant series has no variation to explain, so R^2 is undefined.
    if total == 0.0:
        return float("nan")
    # Fraction of the variation explained: 1 - (error variation / total variation).
    return 1.0 - float(np.sum((predicted - actual) ** 2)) / total


def compute_metrics(actual, predicted):
    """All metrics as a dict: rmse, mae, max_abs_error, bias, r_squared, n.

    Parameters
    ----------
    actual : array_like of float
        Observed lap times [s]; non-empty and finite.
    predicted : array_like of float
        Predicted lap times [s]; same length, finite.

    Returns
    -------
    dict
        rmse, mae, max_abs_error [s], bias [s/lap], r_squared and n (number of laps).

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> compute_metrics([1, 2], [1, 2])["rmse"]
    0.0
    """
    # All five metrics plus the number of laps scored.
    return {
        "rmse": rmse(actual, predicted),
        "mae": mae(actual, predicted),
        "max_abs_error": max_abs_error(actual, predicted),
        "bias": bias(actual, predicted),
        "r_squared": r_squared(actual, predicted),
        "n": int(np.asarray(actual).size),
    }


# ---------------------------------------------------------------------------
# 2. Splits by race (D48)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fold:
    """One train/test split. Races are identified by their RaceId.

    Attributes
    ----------
    train_races : tuple of str
        Races used for fitting.
    test_races : tuple of str
        Races used for scoring; none of them may be a training race.

    Raises
    ------
    ValueError
        If a race is in both sets, or either set is empty.

    Example
    -------
    >>> Fold(("r1", "r2"), ("r3",)).test_races
    ('r3',)
    >>> Fold(("r1",), ("r1",))
    Traceback (most recent call last):
    ...
    ValueError: A race cannot be in both train and test: ['r1'].
    """

    train_races: tuple
    test_races: tuple

    def __post_init__(self):
        # No race may be in both sets, and both sets must be non-empty.
        overlap = set(self.train_races) & set(self.test_races)
        if overlap:
            raise ValueError(f"A race cannot be in both train and test: {sorted(overlap)}.")
        if not self.train_races or not self.test_races:
            raise ValueError("A fold needs at least one training and one test race.")


def leave_one_race_out(race_ids):
    """One fold per race: test on that race, train on all the others.

    Parameters
    ----------
    race_ids : iterable of str
        Race identifiers (duplicates are ignored), at least 2 distinct.

    Returns
    -------
    list of Fold
        In sorted race order.

    Raises
    ------
    ValueError
        If fewer than 2 distinct races are given.

    Example
    -------
    >>> [fold.test_races for fold in leave_one_race_out(["r1", "r2", "r1", "r3"])]
    [('r1',), ('r2',), ('r3',)]
    """
    # Every distinct race becomes the held-out race once; all the others are training.
    races = sorted(set(race_ids))
    if len(races) < 2:
        raise ValueError("Leave-one-race-out needs at least 2 races.")
    return [Fold(tuple(r for r in races if r != held_out), (held_out,)) for held_out in races]


def holdout_split(race_ids, test_races):
    """Train on every race except ``test_races``; test on ``test_races``.

    Parameters
    ----------
    race_ids : iterable of str
        Race identifier of every lap (duplicates are ignored).
    test_races : iterable of str
        Races to hold out; each must be in ``race_ids``.

    Returns
    -------
    Fold
        Races sorted alphabetically within each set.

    Raises
    ------
    ValueError
        If a test race is not among ``race_ids`` or nothing is left to train on.

    Example
    -------
    >>> holdout_split(["r1", "r2", "r3"], ["r3"])
    Fold(train_races=('r1', 'r2'), test_races=('r3',))
    """
    # Train on everything except the requested test races, which must exist in the data.
    races = sorted(set(race_ids))
    test = tuple(sorted(set(test_races)))
    unknown = set(test) - set(races)
    if unknown:
        raise ValueError(f"Test races not found in the data: {sorted(unknown)}.")
    return Fold(tuple(r for r in races if r not in test), test)


def fold_masks(laps, fold, race_column=RACE_COLUMN):
    """Boolean masks (train, test) selecting the laps of a fold's races.

    Parameters
    ----------
    laps : pandas.DataFrame
        Laps with a race-identifier column.
    fold : Fold
        The split.
    race_column : str, optional
        Name of the race column (default ``"RaceId"``).

    Returns
    -------
    train, test : numpy.ndarray of bool
        One entry per lap.

    Raises
    ------
    TypeError
        If ``laps`` is not a DataFrame or ``fold`` is not a Fold.
    ValueError
        If the race column is missing, or a lap ends up in both sets
        (impossible with a valid Fold; checked anyway).

    Example
    -------
    >>> laps = pd.DataFrame({"RaceId": ["r1", "r2"]})
    >>> [m.tolist() for m in fold_masks(laps, Fold(("r1",), ("r2",)))]
    [[True, False], [False, True]]
    """
    # Validate the table, the fold and the race column.
    if not isinstance(laps, pd.DataFrame):
        raise TypeError(f"laps must be a DataFrame, got {type(laps).__name__}.")
    if not isinstance(fold, Fold):
        raise TypeError(f"fold must be a Fold, got {type(fold).__name__}.")
    if race_column not in laps.columns:
        raise ValueError(f"laps has no {race_column!r} column.")
    # Select the laps of the training races and of the test races.
    train = laps[race_column].isin(fold.train_races).to_numpy()
    test = laps[race_column].isin(fold.test_races).to_numpy()
    # Safety check: the two sets must never overlap.
    if np.any(train & test):
        raise ValueError("A lap is in both the training and the test set.")
    return train, test


# ---------------------------------------------------------------------------
# 3. Candidate models and anchored prediction (D49, D50)
# ---------------------------------------------------------------------------
class _ZeroDegradation:
    """The baseline (D50): constant pace, d(n) = 0 for every tyre age."""

    def degradation(self, tyre_age):
        # Baseline model: no degradation at any tyre age.
        return np.zeros(np.asarray(tyre_age, dtype=float).reshape(-1).size)


@dataclass(frozen=True)
class ModelSpec:
    """A candidate model: how to fit it and how complex it is.

    Attributes
    ----------
    name : str
        Unique label, e.g. "polynomial degree 1".
    family : str
        "baseline", "polynomial", "wear_ode" or "knn".
    complexity : int
        Used by the one-standard-error rule (lower = simpler).
    min_training_laps : int
        The candidate is skipped if a fold has fewer training laps (KNN's k).
    fit : callable
        ``fit(tyre_age, lap_time, stint_id)`` -> object with ``degradation``.

    Example
    -------
    >>> from tyredeg.config import load_config
    >>> specs = candidate_models("C3", load_config("config.yaml").models)
    >>> [(spec.name, spec.complexity) for spec in specs[:3]]
    [('baseline (no degradation)', 0), ('polynomial degree 1', 1), ('polynomial degree 2', 2)]
    """

    name: str
    family: str
    complexity: int
    min_training_laps: int
    fit: object


def candidate_models(compound, models):
    """All candidates of Phase 5 for one compound (D48).

    Parameters
    ----------
    compound : str
        Pirelli code, e.g. "C3".
    models : ModelSettings
        ``config.models`` (candidate degrees, k values, weightings, ODE solver).

    Returns
    -------
    list of ModelSpec
        Baseline, polynomial degrees, wear ODE, then every KNN (k, weighting).
        Complexity: degree d -> d, wear ODE -> 2 (two parameters), KNN -> 10
        (non-parametric, most flexible).

    Raises
    ------
    ValueError
        If ``compound`` is not a valid Pirelli code (C0-C6).

    Example
    -------
    >>> from tyredeg.config import load_config
    >>> specs = candidate_models("C3", load_config("config.yaml").models)
    >>> len(specs), specs[0].name
    (17, 'baseline (no degradation)')
    """
    # The baseline is always the first candidate.
    check_compound(compound)
    specs = [ModelSpec(BASELINE_NAME, "baseline", 0, 0, lambda a, t, s: _ZeroDegradation())]
    # One polynomial per candidate degree (degree d binds d into the lambda).
    for degree in models.candidate_degrees:
        specs.append(ModelSpec(
            f"polynomial degree {degree}", "polynomial", degree, 0,
            lambda a, t, s, d=degree: PolynomialDegradationModel(compound, degree=d).fit(a, t, s)))
    # One wear-ODE model with the configured solver and b bracket.
    specs.append(ModelSpec(
        "wear ODE", "wear_ode", 2, 0,
        lambda a, t, s: WearODEModel(compound, solver=models.ode_solver,
                                     b_bracket=models.b_bracket).fit(a, t, s)))
    # One KNN model per (weighting, k) pair; k is also the minimum number of training laps.
    for weights in models.candidate_weights:
        for k in models.candidate_k:
            specs.append(ModelSpec(
                f"knn k={k} {weights}", "knn", 10, k,
                lambda a, t, s, k=k, w=weights: KNNDegradationModel(compound, k=k, weights=w).fit(a, t, s)))
    return specs


def predict_held_out(model, laps, anchor_laps):
    """Anchor each stint's base pace on its first laps; predict the rest (D49).

    Parameters
    ----------
    model : object
        Anything with ``degradation(tyre_age)`` -> d [s].
    laps : pandas.DataFrame
        Held-out laps with RaceId, StintId, LapNumber, TyreLife and
        FuelCorrectedTime.
    anchor_laps : int
        Number of first clean laps per stint used for the offset (>= 1).
        Stints with no laps left after the anchor are skipped.

    Returns
    -------
    pandas.DataFrame
        One row per scored lap: RaceId, StintId, LapNumber, TyreLife,
        actual, predicted, residual (= predicted - actual).

    Raises
    ------
    ValueError
        If ``anchor_laps`` < 1 or no lap could be scored.

    Example
    -------
    >>> class Linear:
    ...     def degradation(self, n):
    ...         return 0.1 * np.asarray(n, dtype=float)
    >>> laps = pd.DataFrame({"RaceId": "r", "StintId": "s", "LapNumber": [1.0, 2.0, 3.0],
    ...                      "TyreLife": [1.0, 2.0, 3.0], "FuelCorrectedTime": [80.1, 80.2, 80.4]})
    >>> predict_held_out(Linear(), laps, anchor_laps=2)["predicted"].round(6).tolist()
    [80.3]

    Implementation (Phase 8, D80): the original version looped over stints,
    building pandas objects and calling the model twice per stint; profiling
    showed it took 67 % of the cross-validation time. This version calls the
    model ONCE for all laps and finds every stint's offset at once with
    ``numpy.bincount`` (per-stint sums). It returns the same rows in the
    same order; :func:`predict_held_out_loop` keeps the original for the
    equivalence test and the before/after benchmark.
    """
    # anchor_laps must be a whole number >= 1.
    if isinstance(anchor_laps, bool) or not isinstance(anchor_laps, (int, np.integer)) or anchor_laps < 1:
        raise ValueError(f"anchor_laps must be an integer >= 1, got {anchor_laps!r}.")
    # Order laps by stint and lap number so the first laps of each stint come first.
    ordered = laps.sort_values([STINT_COLUMN, LAP_COLUMN], kind="stable").reset_index(drop=True)
    # Position of each lap within its stint: 0, 1, 2, ... (laps are sorted).
    # Position of each lap within its stint; the first anchor_laps laps set the stint's base pace.
    position = ordered.groupby(STINT_COLUMN, sort=False).cumcount().to_numpy()
    is_anchor = position < anchor_laps
    # Give each stint an integer index and evaluate the model once for all laps (vectorised).
    _, stint_index = np.unique(ordered[STINT_COLUMN].to_numpy(), return_inverse=True)
    ages = ordered[AGE_COLUMN].to_numpy(float)
    actual_all = ordered[TIME_COLUMN].to_numpy(float)
    degradation = np.asarray(model.degradation(ages), dtype=float)

    # Offset of each stint = mean over its anchor laps of (lap time - d(age)).
    # Offset per stint = mean of (lap time - degradation) over its anchor laps.
    n_stints = int(stint_index.max()) + 1
    anchor_sums = np.bincount(stint_index[is_anchor], weights=(actual_all - degradation)[is_anchor],
                              minlength=n_stints)
    anchor_counts = np.bincount(stint_index[is_anchor], minlength=n_stints)
    offsets = anchor_sums / anchor_counts

    # Score only the laps after the anchor laps; at least one must remain.
    scored = ~is_anchor
    if not np.any(scored):
        raise ValueError(f"No stint has more than {anchor_laps} laps; nothing to score.")
    # Prediction = stint offset + degradation at that lap's tyre age.
    predicted = offsets[stint_index[scored]] + degradation[scored]
    actual = actual_all[scored]
    rest = ordered[scored]
    # One row per scored lap with the actual and predicted times.
    return pd.DataFrame({
        RACE_COLUMN: rest[RACE_COLUMN].to_numpy(), STINT_COLUMN: rest[STINT_COLUMN].to_numpy(),
        LAP_COLUMN: rest[LAP_COLUMN].to_numpy(float), AGE_COLUMN: ages[scored],
        "actual": actual, "predicted": predicted, "residual": predicted - actual,
    })


def predict_held_out_loop(model, laps, anchor_laps):
    """Original stint-by-stint version of :func:`predict_held_out` (reference only).

    Kept unchanged from Phase 5 so the Phase 8 optimisation can be checked
    for identical results and timed before/after.

    Parameters
    ----------
    model : object
        Fitted model with ``degradation(tyre_age)`` [s].
    laps : pandas.DataFrame
        Held-out laps with RaceId, StintId, LapNumber, TyreLife and
        FuelCorrectedTime [s].
    anchor_laps : int
        Number of first laps per stint used to set its base pace, >= 1.

    Returns
    -------
    pandas.DataFrame
        One row per scored lap: RaceId, StintId, LapNumber, TyreLife,
        actual, predicted and residual = predicted - actual [s].

    Raises
    ------
    ValueError
        If ``anchor_laps`` is not an integer >= 1, or no stint has more than
        ``anchor_laps`` laps.

    Example
    -------
    >>> laps = pd.DataFrame({"RaceId": "r1", "StintId": "r1|A|1", "LapNumber": [1.0, 2.0, 3.0, 4.0],
    ...                      "TyreLife": [1.0, 2.0, 3.0, 4.0], "FuelCorrectedTime": [80.1, 80.2, 80.3, 80.5]})
    >>> class Linear:
    ...     def degradation(self, n):
    ...         return 0.1 * np.asarray(n, dtype=float)
    >>> scored = predict_held_out_loop(Linear(), laps, 3)
    >>> scored[["actual", "predicted"]].round(6).values.tolist()
    [[80.5, 80.4]]
    """
    # anchor_laps must be a whole number >= 1.
    if isinstance(anchor_laps, bool) or not isinstance(anchor_laps, (int, np.integer)) or anchor_laps < 1:
        raise ValueError(f"anchor_laps must be an integer >= 1, got {anchor_laps!r}.")
    # Same calculation as predict_held_out, one stint at a time (kept as the reference).
    pieces = []
    ordered = laps.sort_values([STINT_COLUMN, LAP_COLUMN], kind="stable")
    for _, stint in ordered.groupby(STINT_COLUMN, sort=False):
        # Split each stint into its anchor laps and the laps to score.
        anchor, rest = stint.iloc[:anchor_laps], stint.iloc[anchor_laps:]
        if rest.empty:
            continue
        # Offset from the anchor laps, then predict the remaining laps.
        anchor_age = anchor[AGE_COLUMN].to_numpy(float)
        offset = float(np.mean(anchor[TIME_COLUMN].to_numpy(float) - model.degradation(anchor_age)))
        predicted = offset + model.degradation(rest[AGE_COLUMN].to_numpy(float))
        actual = rest[TIME_COLUMN].to_numpy(float)
        pieces.append(pd.DataFrame({
            RACE_COLUMN: rest[RACE_COLUMN].to_numpy(), STINT_COLUMN: rest[STINT_COLUMN].to_numpy(),
            LAP_COLUMN: rest[LAP_COLUMN].to_numpy(float), AGE_COLUMN: rest[AGE_COLUMN].to_numpy(float),
            "actual": actual, "predicted": predicted, "residual": predicted - actual,
        }))
    if not pieces:
        raise ValueError(f"No stint has more than {anchor_laps} laps; nothing to score.")
    return pd.concat(pieces, ignore_index=True)


def fit_on(spec, laps):
    """Fit a candidate on the given laps.

    Parameters
    ----------
    spec : ModelSpec
        The candidate to fit.
    laps : pandas.DataFrame
        Laps with TyreLife [laps], FuelCorrectedTime [s] and StintId.

    Returns
    -------
    object
        The fitted model (has ``degradation``).

    Raises
    ------
    TypeError
        If ``spec`` has no callable ``fit`` or ``laps`` is not a DataFrame.
    ValueError
        If a required column is missing, or the model's own checks fail.

    Example
    -------
    >>> laps = pd.DataFrame({"TyreLife": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
    ...                      "FuelCorrectedTime": [80.0, 80.1, 80.2, 81.0, 81.1, 81.2],
    ...                      "StintId": ["a", "a", "a", "b", "b", "b"]})
    >>> from tyredeg.config import load_config
    >>> spec = candidate_models("C3", load_config("config.yaml").models)[1]
    >>> spec.name, fit_on(spec, laps).degradation([10.0]).round(6).tolist()
    ('polynomial degree 1', [1.0])
    """
    # Any object with a callable ``fit`` works (the tests use a recording stand-in).
    # Validate the candidate and the columns it needs.
    if not callable(getattr(spec, "fit", None)):
        raise TypeError(f"spec must be a ModelSpec (with a callable fit), got {type(spec).__name__}.")
    if not isinstance(laps, pd.DataFrame):
        raise TypeError(f"laps must be a DataFrame, got {type(laps).__name__}.")
    missing = [column for column in (AGE_COLUMN, TIME_COLUMN, STINT_COLUMN) if column not in laps.columns]
    if missing:
        raise ValueError(f"laps is missing columns: {missing}")
    # Fit on tyre age, fuel-corrected lap time and stint id.
    return spec.fit(laps[AGE_COLUMN].to_numpy(float), laps[TIME_COLUMN].to_numpy(float),
                    laps[STINT_COLUMN].to_numpy())


def cross_validate(laps, spec, folds, anchor_laps, implementation="vectorised"):
    """Evaluate one candidate on every fold.

    Parameters
    ----------
    laps : pandas.DataFrame
        Clean laps of ONE compound from the TRAINING races only.
    spec : ModelSpec
        The candidate to evaluate.
    folds : list of Fold
        E.g. :func:`leave_one_race_out`; at least one.
    anchor_laps : int
        First laps per held-out stint used to set its base pace (D49), >= 1.
    implementation : str, optional
        "vectorised" (default, :func:`predict_held_out`) or "loop" (the
        original :func:`predict_held_out_loop`, for the Phase 8 benchmark).

    Returns
    -------
    fold_table : pandas.DataFrame
        One row per fold with the metrics, or ``applicable = False`` if the
        fold had too few training laps for this candidate.
    predictions : pandas.DataFrame
        All scored laps of all folds (with a ``fold`` column).

    Raises
    ------
    ValueError
        For an unknown ``implementation``, an empty ``folds`` list, or invalid
        laps (see :func:`fit_on` and :func:`predict_held_out`).

    Example
    -------
    >>> ages = np.tile(np.arange(1.0, 9.0), 6)
    >>> laps = pd.DataFrame({"RaceId": np.repeat(["r1", "r2", "r3"], 16), "StintId": np.repeat([f"s{i}" for i in range(6)], 8),
    ...                      "LapNumber": ages, "TyreLife": ages, "FuelCorrectedTime": 80.0 + 0.06 * ages + 0.05 * np.sin(7 * ages)})
    >>> from tyredeg.config import load_config
    >>> spec = candidate_models("C3", load_config("config.yaml").models)[1]
    >>> table, scored = cross_validate(laps, spec, leave_one_race_out(laps["RaceId"]), 3)
    >>> table[["test_race", "rmse"]].round(6).values.tolist()
    [['r1', 0.019808], ['r2', 0.019808], ['r3', 0.019808]]
    """
    # Need at least one fold and a known implementation of the prediction step.
    if len(folds) == 0:
        raise ValueError("folds must contain at least one Fold.")
    predictors = {"vectorised": predict_held_out, "loop": predict_held_out_loop}
    if implementation not in predictors:
        raise ValueError(f"implementation must be one of {sorted(predictors)}, got {implementation!r}.")
    predictor = predictors[implementation]
    # For each fold: fit on the training races, predict the held-out race, score it.
    rows, predictions = [], []
    for number, fold in enumerate(folds):
        train_mask, test_mask = fold_masks(laps, fold)
        train, test = laps[train_mask], laps[test_mask]
        row = {"model": spec.name, "family": spec.family, "fold": number,
               "test_race": ",".join(fold.test_races)}
        # KNN needs at least k training laps; otherwise the candidate does not apply to this fold.
        if len(train) < spec.min_training_laps:
            rows.append({**row, "applicable": False})
            continue
        # Fit, predict the held-out laps and compute the metrics.
        scored = predictor(fit_on(spec, train), test, anchor_laps)
        scored["fold"] = number
        predictions.append(scored)
        rows.append({**row, "applicable": True,
                     **compute_metrics(scored["actual"], scored["predicted"])})
    # All predictions together (for residual analysis) and one metrics row per fold.
    combined = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    return pd.DataFrame(rows), combined


def summarize_folds(fold_table, max_abs_bias):
    """Mean +/- standard error over folds per model, plus the D51 checks.

    Columns: model, family, rmse_mean, rmse_se, mae_mean, max_abs_error_max,
    r_squared_mean, bias_mean, bias_max_abs_fold, beats_baseline_all_folds,
    bias_ok. Candidates not applicable in every fold are dropped.

    Parameters
    ----------
    fold_table : pandas.DataFrame
        The concatenated ``fold_table`` outputs of :func:`cross_validate`
        for every candidate, including the baseline.
    max_abs_bias : float
        Largest accepted |mean bias| [s/lap], >= 0 (config: 0.10).

    Returns
    -------
    pandas.DataFrame
        One row per candidate, with the columns listed above.

    Raises
    ------
    TypeError
        If ``fold_table`` is not a DataFrame.
    ValueError
        If a required column or the baseline is missing, or ``max_abs_bias`` < 0.

    Example
    -------
    >>> ages = np.tile(np.arange(1.0, 9.0), 6)
    >>> laps = pd.DataFrame({"RaceId": np.repeat(["r1", "r2", "r3"], 16), "StintId": np.repeat([f"s{i}" for i in range(6)], 8),
    ...                      "LapNumber": ages, "TyreLife": ages, "FuelCorrectedTime": 80.0 + 0.06 * ages + 0.05 * np.sin(7 * ages)})
    >>> from tyredeg.config import load_config
    >>> specs = candidate_models("C3", load_config("config.yaml").models)[:2]   # baseline, degree 1
    >>> tables = [cross_validate(laps, spec, leave_one_race_out(laps["RaceId"]), 3)[0] for spec in specs]
    >>> summary = summarize_folds(pd.concat(tables), max_abs_bias=0.10)
    >>> summary[["model", "beats_baseline_all_folds", "bias_ok"]].values.tolist()
    [['baseline (no degradation)', False, False], ['polynomial degree 1', True, True]]
    """
    # Validate the table: required columns, a baseline to compare with, a valid bias limit.
    if not isinstance(fold_table, pd.DataFrame):
        raise TypeError(f"fold_table must be a DataFrame, got {type(fold_table).__name__}.")
    required = ("model", "family", "fold", "applicable", "rmse", "mae", "max_abs_error", "r_squared", "bias")
    missing = [column for column in required if column not in fold_table.columns]
    if missing:
        raise ValueError(f"fold_table is missing columns: {missing}")
    if not (fold_table["model"] == BASELINE_NAME).any():
        raise ValueError(f"fold_table has no {BASELINE_NAME!r} rows; every candidate is compared with it.")
    if not max_abs_bias >= 0:
        raise ValueError(f"max_abs_bias must be >= 0 s/lap, got {max_abs_bias}.")
    # Drop candidates that could not run in every fold (e.g. KNN with too few laps).
    applicable = fold_table.groupby("model")["applicable"].transform("all")
    table = fold_table[applicable.astype(bool)]
    # Baseline RMSE per fold, to check every candidate beats it.
    baseline = table[table["model"] == BASELINE_NAME].set_index("fold")["rmse"]
    rows = []
    # Summarise each candidate over its folds: mean and standard error of RMSE, and the checks.
    for (model, family), group in table.groupby(["model", "family"], sort=False):
        folds = group.set_index("fold")
        rows.append({
            "model": model, "family": family,
            "rmse_mean": folds["rmse"].mean(),
            "rmse_se": folds["rmse"].std(ddof=1) / np.sqrt(len(folds)),
            "mae_mean": folds["mae"].mean(),
            "max_abs_error_max": folds["max_abs_error"].max(),
            "r_squared_mean": folds["r_squared"].mean(),
            "bias_mean": folds["bias"].mean(),
            "bias_max_abs_fold": folds["bias"].abs().max(),
            "beats_baseline_all_folds": bool(np.all(folds["rmse"] < baseline.loc[folds.index])),
            "bias_ok": abs(folds["bias"].mean()) <= max_abs_bias,
        })
    return pd.DataFrame(rows)


def select_models(summary, complexity):
    """Selection rule (D48): best per family, then the one-standard-error rule.

    1. Within each family the candidate with the lowest mean CV RMSE wins.
    2. Among the family winners (baseline excluded), take the best mean RMSE
       and its standard error; choose the SIMPLEST winner whose mean RMSE is
       within one standard error of the best (ties in simplicity: lower RMSE).

    Parameters
    ----------
    summary : pandas.DataFrame
        Output of :func:`summarize_folds`.
    complexity : dict
        Model name -> complexity (lower = simpler).

    Returns
    -------
    dict
        ``family_winners`` (family -> model name), ``selected`` (model name),
        ``best_rmse``, ``best_rmse_se``, ``threshold``.

    Raises
    ------
    ValueError
        If there is no non-baseline candidate.

    Example
    -------
    >>> s = pd.DataFrame({"model": ["p1", "p3", "k"], "family": ["poly", "poly", "knn"],
    ...                   "rmse_mean": [0.64, 0.62, 0.63], "rmse_se": [0.05, 0.05, 0.05]})
    >>> # p1 and p3 are one family: only p3 (lower RMSE) goes forward. Best
    >>> # winner p3 = 0.62 +/- 0.05; k (0.63) is also within 1 SE, but p3 is simpler.
    >>> select_models(s, {"p1": 1, "p3": 3, "k": 10})["selected"]
    'p3'
    """
    # The baseline is a reference, never selected.
    candidates = summary[summary["family"] != "baseline"]
    if candidates.empty:
        raise ValueError("No candidate model to select from.")
    # Step 1: the best candidate of each family by mean cross-validated RMSE.
    winners = candidates.loc[candidates.groupby("family", sort=False)["rmse_mean"].idxmin()]
    # Step 2: the overall best and the one-standard-error threshold above it.
    best = winners.loc[winners["rmse_mean"].idxmin()]
    threshold = best["rmse_mean"] + best["rmse_se"]
    # Step 3: among family winners within the threshold, choose the simplest.
    eligible = winners[winners["rmse_mean"] <= threshold].copy()
    eligible["complexity"] = eligible["model"].map(complexity)
    chosen = eligible.sort_values(["complexity", "rmse_mean"]).iloc[0]
    return {
        "family_winners": dict(zip(winners["family"], winners["model"])),
        "selected": chosen["model"],
        "best_rmse": float(best["rmse_mean"]),
        "best_rmse_se": float(best["rmse_se"]),
        "threshold": float(threshold),
    }


# ---------------------------------------------------------------------------
# 4. Physical consistency (D53) and compound ranking
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MonotonicCheck:
    """Result of :func:`check_monotonic`.

    Attributes
    ----------
    largest_drop_s : float
        Largest fall of d between consecutive tyre ages [s] (negative if d
        always rises).
    n_drops_over_tolerance : int
        Number of consecutive-age drops larger than the tolerance.
    ok : bool
        True if there are none.
    tolerance_s : float
        The tolerance used [s].

    Example
    -------
    >>> check = check_monotonic(lambda n: -0.1 * n, 3.0, 0.05)
    >>> check.ok, check.n_drops_over_tolerance, round(check.largest_drop_s, 6)
    (False, 3, 0.1)
    """

    largest_drop_s: float
    n_drops_over_tolerance: int
    ok: bool
    tolerance_s: float


def check_monotonic(degradation, max_age, tolerance_s):
    """Check that d(n) does not fall by more than ``tolerance_s`` from lap to lap.

    Parameters
    ----------
    degradation : callable
        d(ages) [s].
    max_age : float
        Oldest tyre age to check [laps]; ages 0, 1, ..., floor(max_age).
    tolerance_s : float
        Allowed drop between consecutive laps [s], >= 0 (config: 0.05 s,
        about the noise of an average over one tyre age, 0.45/sqrt(59)).

    Returns
    -------
    MonotonicCheck

    Raises
    ------
    TypeError
        If ``degradation`` is not callable.
    ValueError
        If ``max_age`` is negative or not finite, or ``tolerance_s`` < 0.

    Example
    -------
    >>> check_monotonic(lambda n: 0.07 * n, 40.0, 0.05).ok
    True
    """
    # Validate the inputs.
    if not callable(degradation):
        raise TypeError("degradation must be callable, d(ages) -> degradation [s].")
    if not np.isfinite(max_age) or max_age < 0:
        raise ValueError(f"max_age must be a finite number of laps >= 0, got {max_age}.")
    if not tolerance_s >= 0:
        raise ValueError("tolerance_s must be >= 0.")
    # d at every whole tyre age from 0 to the oldest age, and the drop between consecutive ages.
    ages = np.arange(0.0, np.floor(max_age) + 1.0)
    drops = -np.diff(np.asarray(degradation(ages), dtype=float))
    # The largest drop and how many drops exceed the tolerance.
    largest = float(np.max(drops)) if drops.size else 0.0
    count = int(np.sum(drops > tolerance_s))
    return MonotonicCheck(largest, count, count == 0, float(tolerance_s))


def rank_compounds(rates):
    """Sort compounds by degradation rate, highest first (no expected order imposed).

    Parameters
    ----------
    rates : pandas.DataFrame
        Columns compound, rate [s/lap], lower, upper (confidence interval).

    Returns
    -------
    pandas.DataFrame
        Same rows sorted by rate (descending) with a ``rank`` column (1 = fastest wear).

    Raises
    ------
    TypeError
        If ``rates`` is not a DataFrame.
    ValueError
        If the ``rate`` column is missing.

    Example
    -------
    >>> df = pd.DataFrame({"compound": ["C3", "C4"], "rate": [0.07, 0.09],
    ...                    "lower": [0.06, 0.08], "upper": [0.08, 0.10]})
    >>> rank_compounds(df)["compound"].tolist()
    ['C4', 'C3']
    """
    # Validate the table, then sort by wear rate, fastest wear first, and number the ranks.
    if not isinstance(rates, pd.DataFrame):
        raise TypeError(f"rates must be a DataFrame, got {type(rates).__name__}.")
    if "rate" not in rates.columns:
        raise ValueError("rates has no 'rate' column.")
    ranked = rates.sort_values("rate", ascending=False).reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
    return ranked


# ---------------------------------------------------------------------------
# 5. Residual analysis (D54)
# ---------------------------------------------------------------------------
def binned_residuals(values, residuals, bin_edges):
    """Mean residual (+/- standard error) in bins of ``values`` (tyre age or lap number).

    A lap belongs to the bin (low, high]: above the lower edge, up to and
    including the upper edge.

    Parameters
    ----------
    values : array_like of float
        Binning variable of each lap, e.g. tyre age [laps].
    residuals : array_like of float
        Residual (predicted - actual) of each lap [s]; same length.
    bin_edges : sequence of float
        At least 2 strictly increasing edges.

    Returns
    -------
    pandas.DataFrame
        Columns bin_low, bin_high, n, mean, se. A trend across bins shows a
        systematic error the model has not captured.

    Raises
    ------
    ValueError
        If ``values`` and ``residuals`` differ in length, or ``bin_edges`` has
        fewer than 2 values or is not strictly increasing.

    Example
    -------
    >>> binned_residuals([1, 2, 11, 12], [0.1, -0.1, 0.5, 0.7], [0, 10, 20])["mean"].round(3).tolist()
    [0.0, 0.6]
    """
    # Convert to 1-D arrays and check lengths and bin edges.
    values = np.asarray(values, dtype=float).reshape(-1)
    residuals = np.asarray(residuals, dtype=float).reshape(-1)
    if values.size != residuals.size:
        raise ValueError(f"values and residuals differ in length ({values.size} vs {residuals.size}).")
    edges = np.asarray(bin_edges, dtype=float)
    if edges.ndim != 1 or edges.size < 2 or np.any(np.diff(edges) <= 0):
        raise ValueError("bin_edges must contain at least 2 strictly increasing values.")
    rows = []
    # For each bin (low, high]: count the laps, mean residual and its standard error.
    for low, high in zip(bin_edges[:-1], bin_edges[1:]):
        inside = (values > low) & (values <= high)
        n = int(inside.sum())
        mean = float(residuals[inside].mean()) if n else float("nan")
        se = float(residuals[inside].std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
        rows.append({"bin_low": low, "bin_high": high, "n": n, "mean": mean, "se": se})
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class FuelDiagnostic:
    """Leftover fuel effect [s/lap] with a group-bootstrap interval (D54).

    Attributes
    ----------
    estimate : float
        Coefficient on lap number after fuel correction [s/lap]; 0 if the
        fuel correction is right.
    standard_error : float
        Bootstrap standard error [s/lap].
    lower, upper : float
        Confidence interval [s/lap].
    flagged : bool
        True if the interval excludes 0.
    n_groups : int
        Number of driver-races (bootstrap units).

    Example
    -------
    >>> FuelDiagnostic(0.0008, 0.002, -0.003, 0.005, False, 120).flagged
    False
    """

    estimate: float
    standard_error: float
    lower: float
    upper: float
    flagged: bool
    n_groups: int


def leftover_fuel_effect(laps, compounds, n_resamples, confidence_level, seed):
    """Estimate any fuel effect left after fuel correction (D54).

    Within a stint, lap number and tyre age both rise by 1 per lap, so a
    per-stint model cannot separate them. Here each DRIVER-RACE gets one
    offset shared by all its stints: tyre age resets at a pit stop but lap
    number does not, so the coefficient on lap number is identifiable. With
    fuel-corrected times it estimates (k_fuel - true fuel effect) [s/lap]:
    zero if the fuel correction is right. Uncertainty: bootstrap that
    resamples whole driver-races (the units that own an offset).

    Parameters
    ----------
    laps : pandas.DataFrame
        Clean laps with RaceId, Driver, TyreLife, LapNumber,
        FuelCorrectedTime and PirelliCompound.
    compounds : sequence of str
        Compounds included (each gets its own tyre-age slope).
    n_resamples : int
        Bootstrap resamples (>= 2).
    confidence_level : float
        In (0, 1).
    seed : int
        Random seed (rule 11).

    Returns
    -------
    FuelDiagnostic
        ``flagged`` is True if the interval excludes 0.

    Raises
    ------
    ValueError
        For invalid settings or no usable laps.

    Example
    -------
    >>> leftover_fuel_effect(clean, ["C3", "C4"], 200, 0.95, 42).flagged  # doctest: +SKIP
    False
    """
    # Keep the requested compounds and check the settings.
    data = laps[laps["PirelliCompound"].isin(compounds)]
    if data.empty:
        raise ValueError("No laps of the requested compounds.")
    if n_resamples < 2 or not 0 < confidence_level < 1:
        raise ValueError("Need n_resamples >= 2 and 0 < confidence_level < 1.")
    # Each driver in each race is one group (one shared base pace).
    groups = (data[RACE_COLUMN].astype(str) + "|" + data["Driver"].astype(str)).to_numpy()
    arrays = {
        "age": data[AGE_COLUMN].to_numpy(float), "lap": data[LAP_COLUMN].to_numpy(float),
        "time": data[TIME_COLUMN].to_numpy(float), "compound": data["PirelliCompound"].to_numpy(),
    }

    # Least-squares slope on lap number after removing each group's mean (one offset per group).
    def slope(selection, labels):
        """Coefficient on lap number for the laps in ``selection``, grouped by ``labels``."""
        _, index = np.unique(labels, return_inverse=True)
        counts = np.bincount(index)

        # Within transformation: subtract each group's mean.
        def demean(values):
            # Within transformation: subtract each driver-race group's mean.
            return values - (np.bincount(index, weights=values) / counts)[index]

        age, lap = arrays["age"][selection], arrays["lap"][selection]
        compound, time = arrays["compound"][selection], arrays["time"][selection]
        # Regressors: tyre age per compound (separate wear slopes) and lap number (leftover fuel
        # effect).
        columns = [demean(np.where(compound == c, age, 0.0)) for c in compounds]
        columns.append(demean(lap))
        result = fit_linear_least_squares(np.column_stack(columns), demean(time))
        # The last coefficient is the lap-number slope.
        return float(result.coefficients[-1])

    # Estimate on all data.
    everything = np.arange(len(groups))
    estimate = slope(everything, groups)
    # Bootstrap: resample whole driver-races with replacement, with a seeded generator.
    unique_groups = np.unique(groups)
    members = {g: np.flatnonzero(groups == g) for g in unique_groups}
    rng = np.random.default_rng(seed)
    resampled = []
    for _ in range(n_resamples):
        # Draw groups and collect their laps.
        chosen = rng.integers(0, unique_groups.size, size=unique_groups.size)
        selection = np.concatenate([members[unique_groups[i]] for i in chosen])
        # A group drawn twice becomes two groups with their own offsets.
        # A group drawn twice becomes two separate groups (its own offset each time).
        labels = np.concatenate([np.full(members[unique_groups[i]].size, n) for n, i in enumerate(chosen)])
        resampled.append(slope(selection, labels))
    resampled = np.array(resampled)
    # Percentile interval; flag the estimate if the interval excludes zero.
    tail = (1.0 - confidence_level) / 2.0 * 100.0
    lower, upper = np.percentile(resampled, [tail, 100.0 - tail])
    return FuelDiagnostic(estimate, float(np.std(resampled, ddof=1)), float(lower), float(upper),
                          bool(lower > 0 or upper < 0), int(unique_groups.size))


# ---------------------------------------------------------------------------
# 6. Test-set firewall (D55)
# ---------------------------------------------------------------------------
class FirewallError(RuntimeError):
    """The test stage was called in a way that could leak or repeat the test.

    Example
    -------
    >>> issubclass(FirewallError, RuntimeError)
    True
    """


def write_selection(path, selection, metadata):
    """Save the CV model selection (JSON) so the test stage can load it unchanged.

    It does not check the firewall itself: callers run :func:`guard_cv_rerun`
    first (C16).

    Parameters
    ----------
    path : str or Path
        JSON file to write (its folder is created if needed).
    selection : dict
        Per compound: the output of :func:`select_models`.
    metadata : dict
        E.g. training races, git commit; a UTC timestamp is added.

    Returns
    -------
    dict
        What was written.

    Raises
    ------
    TypeError
        If ``selection`` or ``metadata`` is not a dict.

    Example
    -------
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     content = write_selection(pathlib.Path(folder) / "selection.json", {"C3": {"selected": "x"}}, {})
    ...     load_selection(pathlib.Path(folder) / "selection.json")["selection"]
    {'C3': {'selected': 'x'}}
    """
    # Validate the inputs and create the folder.
    if not isinstance(selection, dict) or not isinstance(metadata, dict):
        raise TypeError("selection and metadata must both be dicts.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Save the selection with a UTC timestamp, so it is clear it was fixed before the test.
    content = {"created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               **metadata, "selection": selection}
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return content


def guard_cv_rerun(selection_path, test_results_path, force=False):
    """Refuse to overwrite the frozen model selection once the test has been run.

    After the single test evaluation, ``model_selection.json`` is the
    evidence that the selection was fixed BEFORE the test (D55). Re-running
    the cross-validation stage would overwrite it with a later timestamp and
    commit, so it is only allowed with ``force`` (added after C16).

    Parameters
    ----------
    selection_path : str or Path
        The frozen ``model_selection.json``.
    test_results_path : str or Path
        The test results file; its existence means the test has been run.
    force : bool, optional
        Allow the re-run anyway (default False).

    Raises
    ------
    FirewallError
        If a selection file and test results both exist and ``force`` is False.

    Example
    -------
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     selection, results = pathlib.Path(folder) / "s.json", pathlib.Path(folder) / "r.csv"
    ...     guard_cv_rerun(selection, results)          # nothing frozen yet: allowed
    ...     _ = selection.write_text("{}"); _ = results.write_text("")
    ...     guard_cv_rerun(selection, results)
    Traceback (most recent call last):
    ...
    tyredeg.validation.FirewallError: r.csv exists: the test race has already been evaluated, so the frozen s.json must not be overwritten. Use --force only if you deliberately want a new selection (and say so in the report).
    """
    # If the test was already run, refuse to overwrite the frozen selection (unless forced).
    if Path(selection_path).exists() and Path(test_results_path).exists() and not force:
        raise FirewallError(
            f"{Path(test_results_path).name} exists: the test race has already been evaluated, so the "
            f"frozen {Path(selection_path).name} must not be overwritten. Use --force only if you "
            f"deliberately want a new selection (and say so in the report)."
        )


def load_selection(path):
    """Load the CV model selection; refuse if cross-validation has not been run.

    Parameters
    ----------
    path : str or Path
        The ``model_selection.json`` written by :func:`write_selection`.

    Returns
    -------
    dict
        The file's content (``created_utc``, metadata and ``selection``).

    Raises
    ------
    FirewallError
        If the selection file does not exist.

    Example
    -------
    >>> load_selection("reports/model_selection.json")["selection"]["C3"]["selected"]  # doctest: +SKIP
    'polynomial degree 1'
    """
    # The test stage needs a selection made earlier by the cross-validation stage.
    path = Path(path)
    if not path.is_file():
        raise FirewallError(
            f"{path} not found: run the cross-validation stage first. The test race may "
            f"only be evaluated after model selection is fixed (D55)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def guard_test_run(results_path, log_path, force=False):
    """Allow the single test evaluation; refuse a repeat unless ``force``.

    Every allowed run is appended to ``log_path`` with a timestamp, so a
    repeated (forced) evaluation is always visible.

    Parameters
    ----------
    results_path : str or Path
        The test results file; its existence means the test has been run.
    log_path : str or Path
        Log file to which each allowed run is appended.
    force : bool, optional
        Allow a repeat (default False); the log marks it as forced.

    Raises
    ------
    FirewallError
        If the test results already exist and ``force`` is False.

    Example
    -------
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     log = pathlib.Path(folder) / "runs.log"
    ...     guard_test_run(pathlib.Path(folder) / "results.csv", log)   # first run: allowed and logged
    ...     log.read_text().endswith("test evaluation\\n")
    True
    """
    # Refuse a second test run unless explicitly forced.
    results_path, log_path = Path(results_path), Path(log_path)
    if results_path.exists() and not force:
        raise FirewallError(
            f"{results_path} already exists: the test race has been evaluated. "
            f"Re-running needs --force and is logged (D55)."
        )
    # Log every allowed run with a timestamp, so a repeated test is always visible.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"{stamp} test evaluation{' (FORCED re-run)' if force else ''}\n")
