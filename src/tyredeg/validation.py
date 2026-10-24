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

    Example
    -------
    >>> round(rmse([1, 2, 3, 4], [1, 3, 2, 6]), 6)
    1.224745
    """
    actual, predicted = _errors(actual, predicted)
    return float(np.sqrt(np.mean((predicted - actual) ** 2)))


def mae(actual, predicted):
    """Mean absolute error mean(|predicted - actual|) [s].

    Example
    -------
    >>> mae([1, 2, 3, 4], [1, 3, 2, 6])
    1.0
    """
    actual, predicted = _errors(actual, predicted)
    return float(np.mean(np.abs(predicted - actual)))


def max_abs_error(actual, predicted):
    """Largest |predicted - actual| [s].

    Example
    -------
    >>> max_abs_error([1, 2, 3, 4], [1, 3, 2, 6])
    2.0
    """
    actual, predicted = _errors(actual, predicted)
    return float(np.max(np.abs(predicted - actual)))


def bias(actual, predicted):
    """Mean signed error mean(predicted - actual) [s/lap]; > 0 means too slow.

    Strategy adds up lap times, so a consistent bias accumulates over a stint
    (0.1 s/lap over 35 laps = 3.5 s); hence the acceptance criterion (D51).

    Example
    -------
    >>> bias([1, 2, 3, 4], [1, 3, 2, 6])
    0.5
    """
    actual, predicted = _errors(actual, predicted)
    return float(np.mean(predicted - actual))


def r_squared(actual, predicted):
    """Coefficient of determination 1 - SS_res / SS_tot (NaN if actual is constant).

    Note: anchoring each stint's base pace already explains much of the
    lap-time variance, so R^2 is high even for the baseline; it is reported
    but not used for selection (D47).

    Example
    -------
    >>> round(r_squared([1, 2, 3, 4], [1, 3, 2, 6]), 6)
    -0.2
    """
    actual, predicted = _errors(actual, predicted)
    total = float(np.sum((actual - actual.mean()) ** 2))
    if total == 0.0:
        return float("nan")
    return 1.0 - float(np.sum((predicted - actual) ** 2)) / total


def compute_metrics(actual, predicted):
    """All metrics as a dict: rmse, mae, max_abs_error, bias, r_squared, n.

    Raises
    ------
    ValueError
        For empty, mismatched or non-finite inputs.

    Example
    -------
    >>> compute_metrics([1, 2], [1, 2])["rmse"]
    0.0
    """
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
    """One train/test split. Races are identified by their RaceId."""

    train_races: tuple
    test_races: tuple

    def __post_init__(self):
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
    races = sorted(set(race_ids))
    if len(races) < 2:
        raise ValueError("Leave-one-race-out needs at least 2 races.")
    return [Fold(tuple(r for r in races if r != held_out), (held_out,)) for held_out in races]


def holdout_split(race_ids, test_races):
    """Train on every race except ``test_races``; test on ``test_races``.

    Raises
    ------
    ValueError
        If a test race is not among ``race_ids`` or nothing is left to train on.

    Example
    -------
    >>> holdout_split(["r1", "r2", "r3"], ["r3"])
    Fold(train_races=('r1', 'r2'), test_races=('r3',))
    """
    races = sorted(set(race_ids))
    test = tuple(sorted(set(test_races)))
    unknown = set(test) - set(races)
    if unknown:
        raise ValueError(f"Test races not found in the data: {sorted(unknown)}.")
    return Fold(tuple(r for r in races if r not in test), test)


def fold_masks(laps, fold, race_column=RACE_COLUMN):
    """Boolean masks (train, test) selecting the laps of a fold's races.

    Raises
    ------
    ValueError
        If a lap ends up in both sets (impossible with a valid Fold; checked anyway).

    Example
    -------
    >>> laps = pd.DataFrame({"RaceId": ["r1", "r2"]})
    >>> [m.tolist() for m in fold_masks(laps, Fold(("r1",), ("r2",)))]
    [[True, False], [False, True]]
    """
    train = laps[race_column].isin(fold.train_races).to_numpy()
    test = laps[race_column].isin(fold.test_races).to_numpy()
    if np.any(train & test):
        raise ValueError("A lap is in both the training and the test set.")
    return train, test


# ---------------------------------------------------------------------------
# 3. Candidate models and anchored prediction (D49, D50)
# ---------------------------------------------------------------------------
class _ZeroDegradation:
    """The baseline (D50): constant pace, d(n) = 0 for every tyre age."""

    def degradation(self, tyre_age):
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

    Example
    -------
    >>> specs = candidate_models("C3", load_config("config.yaml").models)  # doctest: +SKIP
    >>> specs[0].name  # doctest: +SKIP
    'baseline (no degradation)'
    """
    specs = [ModelSpec(BASELINE_NAME, "baseline", 0, 0, lambda a, t, s: _ZeroDegradation())]
    for degree in models.candidate_degrees:
        specs.append(ModelSpec(
            f"polynomial degree {degree}", "polynomial", degree, 0,
            lambda a, t, s, d=degree: PolynomialDegradationModel(compound, degree=d).fit(a, t, s)))
    specs.append(ModelSpec(
        "wear ODE", "wear_ode", 2, 0,
        lambda a, t, s: WearODEModel(compound, solver=models.ode_solver,
                                     b_bracket=models.b_bracket).fit(a, t, s)))
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
    """
    if isinstance(anchor_laps, bool) or not isinstance(anchor_laps, (int, np.integer)) or anchor_laps < 1:
        raise ValueError(f"anchor_laps must be an integer >= 1, got {anchor_laps!r}.")
    pieces = []
    ordered = laps.sort_values([STINT_COLUMN, LAP_COLUMN], kind="stable")
    for _, stint in ordered.groupby(STINT_COLUMN, sort=False):
        anchor, rest = stint.iloc[:anchor_laps], stint.iloc[anchor_laps:]
        if rest.empty:
            continue
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
    laps : pandas.DataFrame
        Laps with TyreLife, FuelCorrectedTime and StintId.

    Returns
    -------
    object
        The fitted model (has ``degradation``).

    Example
    -------
    >>> model = fit_on(spec, training_laps)  # doctest: +SKIP
    """
    return spec.fit(laps[AGE_COLUMN].to_numpy(float), laps[TIME_COLUMN].to_numpy(float),
                    laps[STINT_COLUMN].to_numpy())


def cross_validate(laps, spec, folds, anchor_laps):
    """Evaluate one candidate on every fold.

    Parameters
    ----------
    laps : pandas.DataFrame
        Clean laps of ONE compound from the TRAINING races only.
    spec : ModelSpec
    folds : list of Fold
        E.g. :func:`leave_one_race_out`.
    anchor_laps : int

    Returns
    -------
    fold_table : pandas.DataFrame
        One row per fold with the metrics, or ``applicable = False`` if the
        fold had too few training laps for this candidate.
    predictions : pandas.DataFrame
        All scored laps of all folds (with a ``fold`` column).

    Example
    -------
    >>> table, scored = cross_validate(c3_laps, spec, leave_one_race_out(c3_laps["RaceId"]), 3)  # doctest: +SKIP
    """
    rows, predictions = [], []
    for number, fold in enumerate(folds):
        train_mask, test_mask = fold_masks(laps, fold)
        train, test = laps[train_mask], laps[test_mask]
        row = {"model": spec.name, "family": spec.family, "fold": number,
               "test_race": ",".join(fold.test_races)}
        if len(train) < spec.min_training_laps:
            rows.append({**row, "applicable": False})
            continue
        scored = predict_held_out(fit_on(spec, train), test, anchor_laps)
        scored["fold"] = number
        predictions.append(scored)
        rows.append({**row, "applicable": True,
                     **compute_metrics(scored["actual"], scored["predicted"])})
    combined = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    return pd.DataFrame(rows), combined


def summarize_folds(fold_table, max_abs_bias):
    """Mean +/- standard error over folds per model, plus the D51 checks.

    Columns: model, family, rmse_mean, rmse_se, mae_mean, max_abs_error_max,
    r_squared_mean, bias_mean, bias_max_abs_fold, beats_baseline_all_folds,
    bias_ok. Candidates not applicable in every fold are dropped.

    Example
    -------
    >>> summary = summarize_folds(fold_table, max_abs_bias=0.10)  # doctest: +SKIP
    """
    applicable = fold_table.groupby("model")["applicable"].transform("all")
    table = fold_table[applicable.astype(bool)]
    baseline = table[table["model"] == BASELINE_NAME].set_index("fold")["rmse"]
    rows = []
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
    candidates = summary[summary["family"] != "baseline"]
    if candidates.empty:
        raise ValueError("No candidate model to select from.")
    winners = candidates.loc[candidates.groupby("family", sort=False)["rmse_mean"].idxmin()]
    best = winners.loc[winners["rmse_mean"].idxmin()]
    threshold = best["rmse_mean"] + best["rmse_se"]
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
    """Result of :func:`check_monotonic`."""

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

    Example
    -------
    >>> check_monotonic(lambda n: 0.07 * n, 40.0, 0.05).ok
    True
    """
    if not tolerance_s >= 0:
        raise ValueError("tolerance_s must be >= 0.")
    ages = np.arange(0.0, np.floor(max_age) + 1.0)
    drops = -np.diff(np.asarray(degradation(ages), dtype=float))
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

    Example
    -------
    >>> df = pd.DataFrame({"compound": ["C3", "C4"], "rate": [0.07, 0.09],
    ...                    "lower": [0.06, 0.08], "upper": [0.08, 0.10]})
    >>> rank_compounds(df)["compound"].tolist()
    ['C4', 'C3']
    """
    ranked = rates.sort_values("rate", ascending=False).reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
    return ranked


# ---------------------------------------------------------------------------
# 5. Residual analysis (D54)
# ---------------------------------------------------------------------------
def binned_residuals(values, residuals, bin_edges):
    """Mean residual (+/- standard error) in bins of ``values`` (tyre age or lap number).

    Returns
    -------
    pandas.DataFrame
        Columns bin_low, bin_high, n, mean, se. A trend across bins shows a
        systematic error the model has not captured.

    Example
    -------
    >>> binned_residuals([1, 2, 11, 12], [0.1, -0.1, 0.5, 0.7], [0, 10, 20])["mean"].round(3).tolist()
    [0.0, 0.6]
    """
    values = np.asarray(values, dtype=float)
    residuals = np.asarray(residuals, dtype=float)
    rows = []
    for low, high in zip(bin_edges[:-1], bin_edges[1:]):
        inside = (values > low) & (values <= high)
        n = int(inside.sum())
        mean = float(residuals[inside].mean()) if n else float("nan")
        se = float(residuals[inside].std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
        rows.append({"bin_low": low, "bin_high": high, "n": n, "mean": mean, "se": se})
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class FuelDiagnostic:
    """Leftover fuel effect [s/lap] with a group-bootstrap interval (D54)."""

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
    data = laps[laps["PirelliCompound"].isin(compounds)]
    if data.empty:
        raise ValueError("No laps of the requested compounds.")
    if n_resamples < 2 or not 0 < confidence_level < 1:
        raise ValueError("Need n_resamples >= 2 and 0 < confidence_level < 1.")
    groups = (data[RACE_COLUMN].astype(str) + "|" + data["Driver"].astype(str)).to_numpy()
    arrays = {
        "age": data[AGE_COLUMN].to_numpy(float), "lap": data[LAP_COLUMN].to_numpy(float),
        "time": data[TIME_COLUMN].to_numpy(float), "compound": data["PirelliCompound"].to_numpy(),
    }

    def slope(selection, labels):
        """Coefficient on lap number for the laps in ``selection``, grouped by ``labels``."""
        _, index = np.unique(labels, return_inverse=True)
        counts = np.bincount(index)

        def demean(values):
            # Within transformation: subtract each driver-race group's mean.
            return values - (np.bincount(index, weights=values) / counts)[index]

        age, lap = arrays["age"][selection], arrays["lap"][selection]
        compound, time = arrays["compound"][selection], arrays["time"][selection]
        columns = [demean(np.where(compound == c, age, 0.0)) for c in compounds]
        columns.append(demean(lap))
        result = fit_linear_least_squares(np.column_stack(columns), demean(time))
        return float(result.coefficients[-1])

    everything = np.arange(len(groups))
    estimate = slope(everything, groups)
    unique_groups = np.unique(groups)
    members = {g: np.flatnonzero(groups == g) for g in unique_groups}
    rng = np.random.default_rng(seed)
    resampled = []
    for _ in range(n_resamples):
        chosen = rng.integers(0, unique_groups.size, size=unique_groups.size)
        selection = np.concatenate([members[unique_groups[i]] for i in chosen])
        # A group drawn twice becomes two groups with their own offsets.
        labels = np.concatenate([np.full(members[unique_groups[i]].size, n) for n, i in enumerate(chosen)])
        resampled.append(slope(selection, labels))
    resampled = np.array(resampled)
    tail = (1.0 - confidence_level) / 2.0 * 100.0
    lower, upper = np.percentile(resampled, [tail, 100.0 - tail])
    return FuelDiagnostic(estimate, float(np.std(resampled, ddof=1)), float(lower), float(upper),
                          bool(lower > 0 or upper < 0), int(unique_groups.size))


# ---------------------------------------------------------------------------
# 6. Test-set firewall (D55)
# ---------------------------------------------------------------------------
class FirewallError(RuntimeError):
    """The test stage was called in a way that could leak or repeat the test."""


def write_selection(path, selection, metadata):
    """Save the CV model selection (JSON) so the test stage can load it unchanged.

    Parameters
    ----------
    path : str or Path
    selection : dict
        Per compound: the output of :func:`select_models`.
    metadata : dict
        E.g. training races, git commit; a UTC timestamp is added.

    Returns
    -------
    dict
        What was written.

    Example
    -------
    >>> write_selection("reports/model_selection.json", selection, {"git_commit": "abc"})  # doctest: +SKIP
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {"created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               **metadata, "selection": selection}
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    return content


def load_selection(path):
    """Load the CV model selection; refuse if cross-validation has not been run.

    Raises
    ------
    FirewallError
        If the selection file does not exist.

    Example
    -------
    >>> load_selection("reports/model_selection.json")["selection"]["C3"]["selected"]  # doctest: +SKIP
    'polynomial degree 1'
    """
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

    Raises
    ------
    FirewallError
        If the test results already exist and ``force`` is False.

    Example
    -------
    >>> guard_test_run("reports/phase5_test_results.csv", "reports/test_runs.log")  # doctest: +SKIP
    """
    results_path, log_path = Path(results_path), Path(log_path)
    if results_path.exists() and not force:
        raise FirewallError(
            f"{results_path} already exists: the test race has been evaluated. "
            f"Re-running needs --force and is logged (D55)."
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"{stamp} test evaluation{' (FORCED re-run)' if force else ''}\n")
