"""Shared building blocks for the three degradation models.

Model structure (DECISIONS.md D39)
----------------------------------
Every model describes a lap time as

    lap_time = offset_of_its_stint + d(tyre_age)

- ``offset`` is a separate base lap time for each stint. It absorbs the
  differences between cars, drivers and races (car pace is not modelled).
- ``d(tyre_age)`` is the degradation curve, SHARED by all stints of one
  compound, with d(0) = 0 (a fresh tyre has not degraded).

Lap times are fuel-corrected (D21) and tyre age is ``TyreLife`` [laps].

The within-stint transformation (Frisch-Waugh-Lovell)
-----------------------------------------------------
Fitting 87 stint offsets plus 1-3 degradation parameters by least squares
would need a ~90 x 90 system. The Frisch-Waugh-Lovell theorem gives the SAME
degradation parameters more cheaply: subtract each stint's mean from the lap
times and from every degradation regressor, then fit the regressors without
an intercept. Each offset is afterwards the stint mean of
``lap_time - d(tyre_age)``. Only the residual degrees of freedom change:
n - (number of stints) - (number of degradation parameters).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tyredeg.config import VALID_PIRELLI_COMPOUNDS


class NotFittedError(ValueError):
    """A model method that needs fitted parameters was called before ``fit``."""


@dataclass(frozen=True)
class StintData:
    """Validated training data with stints encoded as integers 0..n_stints-1.

    Attributes
    ----------
    tyre_age : numpy.ndarray
        Tyre age [laps] of each lap, >= 0.
    lap_time : numpy.ndarray
        (Fuel-corrected) lap time [s] of each lap, > 0.
    stint_index : numpy.ndarray of int
        Stint number of each lap, 0 .. n_stints - 1.
    stint_labels : numpy.ndarray
        Original stint identifier for each stint index.
    """

    tyre_age: np.ndarray
    lap_time: np.ndarray
    stint_index: np.ndarray
    stint_labels: np.ndarray

    @property
    def n_laps(self):
        return self.tyre_age.size

    @property
    def n_stints(self):
        return self.stint_labels.size

    def demean(self, values):
        """Subtract each stint's mean from ``values`` (the within transformation)."""
        return values - self.stint_means(values)[self.stint_index]

    def stint_means(self, values):
        """Mean of ``values`` within each stint, shape (n_stints,)."""
        sums = np.bincount(self.stint_index, weights=values, minlength=self.n_stints)
        counts = np.bincount(self.stint_index, minlength=self.n_stints)
        return sums / counts


def check_compound(compound):
    """Return the Pirelli compound code if valid, else raise.

    Parameters
    ----------
    compound : str
        Pirelli code "C0" (hardest) ... "C6" (softest), e.g. "C3".

    Returns
    -------
    str

    Raises
    ------
    TypeError
        If ``compound`` is not a string.
    ValueError
        If it is not one of C0-C6 (e.g. "HARD" or "C9").

    Example
    -------
    >>> check_compound("C3")
    'C3'
    """
    if not isinstance(compound, str):
        raise TypeError(f"compound must be a string such as 'C3', got {compound!r}.")
    if compound not in VALID_PIRELLI_COMPOUNDS:
        raise ValueError(
            f"Unknown compound {compound!r}; use a Pirelli code from {VALID_PIRELLI_COMPOUNDS}."
        )
    return compound


def check_tyre_age(tyre_age, name="tyre_age"):
    """Return ``tyre_age`` as a 1-D float array of finite values >= 0, else raise.

    Raises
    ------
    ValueError
        If it is empty, not 1-D, contains NaN/inf or negative values.

    Example
    -------
    >>> check_tyre_age([0, 1.5]).tolist()
    [0.0, 1.5]
    """
    values = np.asarray(tyre_age, dtype=float)
    if values.ndim == 0:
        values = values.reshape(1)
    if values.ndim != 1 or values.size == 0:
        raise ValueError(f"{name} must be a non-empty 1-D array.")
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} must not contain NaN or infinite values.")
    if np.any(values < 0):
        raise ValueError(f"{name} must be >= 0 (tyre age in laps).")
    return values


def prepare_stint_data(tyre_age, lap_time, stint_id=None):
    """Validate training inputs and encode the stints.

    Parameters
    ----------
    tyre_age : array_like
        Tyre age [laps] of each lap, >= 0.
    lap_time : array_like
        Fuel-corrected lap time [s] of each lap, > 0, same length.
    stint_id : array_like or None, optional
        Stint identifier of each lap (any hashable values, e.g. strings).
        None means all laps belong to one stint.

    Returns
    -------
    StintData

    Raises
    ------
    ValueError
        For empty or mismatched arrays, NaN values, negative ages or
        non-positive lap times.

    Example
    -------
    >>> data = prepare_stint_data([1, 2, 1], [80.0, 80.1, 81.0], ["a", "a", "b"])
    >>> data.n_stints, data.stint_index.tolist()
    (2, [0, 0, 1])
    """
    age = check_tyre_age(tyre_age)
    time = np.asarray(lap_time, dtype=float).reshape(-1)
    if time.size != age.size:
        raise ValueError(
            f"tyre_age and lap_time must have the same length, got {age.size} and {time.size}."
        )
    if not np.all(np.isfinite(time)):
        raise ValueError("lap_time must not contain NaN or infinite values.")
    if np.any(time <= 0):
        raise ValueError("lap_time must be > 0 seconds.")
    if stint_id is None:
        stint_id = np.zeros(age.size, dtype=int)
    stint_id = np.asarray(stint_id)
    if stint_id.ndim != 1 or stint_id.size != age.size:
        raise ValueError("stint_id must be 1-D with one entry per lap.")
    labels, index = np.unique(stint_id, return_inverse=True)
    return StintData(tyre_age=age, lap_time=time, stint_index=index, stint_labels=labels)


def check_degrees_of_freedom(data, n_parameters):
    """Raise unless there is at least 1 residual degree of freedom.

    With one offset per stint plus ``n_parameters`` degradation parameters,
    the residual degrees of freedom are n_laps - n_stints - n_parameters.
    """
    dof = data.n_laps - data.n_stints - n_parameters
    if dof < 1:
        raise ValueError(
            f"Too few laps: {data.n_laps} laps, {data.n_stints} stints and "
            f"{n_parameters} degradation parameters leave {dof} residual degrees of freedom."
        )
    return dof


def stint_labels_from_laps(laps):
    """Return one label per lap, e.g. ``"2023_hungarian_grand_prix|VER|2"``.

    Parameters
    ----------
    laps : pandas.DataFrame
        Needs ``RaceId``, ``Driver`` and ``Stint``.

    Returns
    -------
    numpy.ndarray of str

    Raises
    ------
    ValueError
        If a column is missing.

    Example
    -------
    >>> import pandas as pd
    >>> df = pd.DataFrame({"RaceId": ["r"], "Driver": ["VER"], "Stint": [2.0]})
    >>> stint_labels_from_laps(df).tolist()
    ['r|VER|2']
    """
    for column in ("RaceId", "Driver", "Stint"):
        if column not in laps.columns:
            raise ValueError(f"laps is missing column {column!r}.")
    stint = laps["Stint"].astype(int).astype(str)
    return (laps["RaceId"].astype(str) + "|" + laps["Driver"].astype(str) + "|" + stint).to_numpy()


# ---------------------------------------------------------------------------
# Constraint check (D43)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConstraintCheck:
    """Result of the non-negative degradation check.

    Attributes
    ----------
    min_degradation_s : float
        Smallest d(age) over ages 0 .. max fitted age [s].
    age_of_minimum : float
        Tyre age [laps] where that minimum occurs.
    violated : bool
        True if ``min_degradation_s < -tolerance``.
    tolerance_s : float
    """

    min_degradation_s: float
    age_of_minimum: float
    violated: bool
    tolerance_s: float


def check_non_negative(degradation_function, max_age, tolerance_s, ages=None):
    """Evaluate d on a grid of ages and flag clearly negative degradation.

    Parameters
    ----------
    degradation_function : callable
        d(ages) -> degradation [s].
    max_age : float
        Largest tyre age in the training data [laps].
    tolerance_s : float
        Allowed numerical slack [s], >= 0 (config: 0.01 s).
    ages : array_like or None, optional
        Ages to check; default 0, 0.5, ..., max_age.

    Returns
    -------
    ConstraintCheck

    Example
    -------
    >>> check_non_negative(lambda n: 0.07 * n, 40.0, 0.01).violated
    False
    """
    if ages is None:
        ages = np.arange(0.0, max_age + 0.25, 0.5)
    ages = np.asarray(ages, dtype=float)
    values = np.asarray(degradation_function(ages), dtype=float)
    position = int(np.argmin(values))
    minimum = float(values[position])
    return ConstraintCheck(
        min_degradation_s=minimum,
        age_of_minimum=float(ages[position]),
        violated=minimum < -tolerance_s,
        tolerance_s=float(tolerance_s),
    )


# ---------------------------------------------------------------------------
# Stint (cluster) bootstrap (D45)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BootstrapResult:
    """Summary of a stint bootstrap.

    Attributes
    ----------
    names : tuple of str
        Parameter names.
    estimates : numpy.ndarray
        Shape (n_resamples, n_parameters): the parameters from every resample.
    standard_errors : numpy.ndarray
        Standard deviation of each parameter over the resamples.
    lower, upper : numpy.ndarray
        Percentile confidence interval limits.
    confidence_level : float
    seed : int
    """

    names: tuple
    estimates: np.ndarray
    standard_errors: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    confidence_level: float
    seed: int


def resample_stints(data, rng):
    """Draw whole stints with replacement; return (tyre_age, lap_time, new stint ids).

    A stint drawn twice becomes two separate stints (new ids), so each copy
    gets its own offset, exactly as an independent stint would.
    """
    chosen = rng.integers(0, data.n_stints, size=data.n_stints)
    ages, times, ids = [], [], []
    for new_id, stint in enumerate(chosen):
        mask = data.stint_index == stint
        ages.append(data.tyre_age[mask])
        times.append(data.lap_time[mask])
        ids.append(np.full(mask.sum(), new_id))
    return np.concatenate(ages), np.concatenate(times), np.concatenate(ids)


def stint_bootstrap(data, fit_parameters, names, n_resamples, confidence_level, seed):
    """Bootstrap parameter uncertainty by resampling whole stints.

    Laps within a stint are correlated (lag-1 residual correlation ~0.45 in
    the training data), so resampling single laps would understate the
    uncertainty; resampling stints keeps that correlation intact.

    Parameters
    ----------
    data : StintData
        The original training data.
    fit_parameters : callable
        ``fit_parameters(tyre_age, lap_time, stint_id) -> 1-D array`` of the
        parameters of interest, refitted on one resample.
    names : sequence of str
        Parameter names (same order).
    n_resamples : int
        Number of resamples, >= 2 (config: 200).
    confidence_level : float
        In (0, 1), e.g. 0.95 for a 2.5-97.5 percentile interval.
    seed : int
        Random seed (rule 11; config: 42).

    Returns
    -------
    BootstrapResult

    Raises
    ------
    ValueError
        For invalid settings.

    Example
    -------
    >>> result = stint_bootstrap(data, refit, ("a", "b"), 200, 0.95, 42)  # doctest: +SKIP
    """
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, (int, np.integer)) or n_resamples < 2:
        raise ValueError(f"n_resamples must be an integer >= 2, got {n_resamples!r}.")
    if not 0 < confidence_level < 1:
        raise ValueError(f"confidence_level must be in (0, 1), got {confidence_level}.")
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(n_resamples):
        ages, times, ids = resample_stints(data, rng)
        estimates.append(np.asarray(fit_parameters(ages, times, ids), dtype=float))
    estimates = np.array(estimates)
    tail = (1.0 - confidence_level) / 2.0 * 100.0
    return BootstrapResult(
        names=tuple(names),
        estimates=estimates,
        standard_errors=np.std(estimates, axis=0, ddof=1),
        lower=np.percentile(estimates, tail, axis=0),
        upper=np.percentile(estimates, 100.0 - tail, axis=0),
        confidence_level=float(confidence_level),
        seed=int(seed),
    )


def format_parameter_table(names, values, analytic_se, bootstrap=None):
    """Return text lines 'name  value  (analytic SE)  [bootstrap SE, CI]'."""
    lines = []
    for i, name in enumerate(names):
        line = f"  {name:<14s} {values[i]: .6g}   SE(analytic) {analytic_se[i]:.3g}"
        if bootstrap is not None:
            line += (f"   SE(bootstrap) {bootstrap.standard_errors[i]:.3g}"
                     f"   {bootstrap.confidence_level:.0%} CI [{bootstrap.lower[i]:.4g}, "
                     f"{bootstrap.upper[i]:.4g}]")
        lines.append(line)
    return lines
