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
    """A model method that needs fitted parameters was called before ``fit``.

    Example
    -------
    >>> issubclass(NotFittedError, ValueError)
    True
    """


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

    Example
    -------
    >>> data = prepare_stint_data([1, 2, 3, 1, 2], [80.0, 80.1, 80.2, 81.0, 81.2], ["A", "A", "A", "B", "B"])
    >>> data.n_laps, data.n_stints, data.stint_index.tolist()
    (5, 2, [0, 0, 0, 1, 1])
    """

    tyre_age: np.ndarray
    lap_time: np.ndarray
    stint_index: np.ndarray
    stint_labels: np.ndarray

    @property
    def n_laps(self):
        return self.tyre_age.size

    def _per_lap(self, values):
        """Return ``values`` as a float array, after checking there is one value per lap."""
        values = np.asarray(values, dtype=float)
        if values.shape != (self.n_laps,):
            raise ValueError(f"values must have shape ({self.n_laps},), one per lap; got {values.shape}.")
        return values

    @property
    def n_stints(self):
        return self.stint_labels.size

    def demean(self, values):
        """Subtract each stint's mean from ``values`` (the within transformation).

        Parameters
        ----------
        values : array_like of float, shape (n_laps,)
            One value per lap, e.g. lap times [s] or tyre ages [laps].

        Returns
        -------
        numpy.ndarray of float, shape (n_laps,)
            ``values`` minus the mean of its own stint.

        Raises
        ------
        ValueError
            If ``values`` does not have exactly one entry per lap.

        Example
        -------
        >>> data = prepare_stint_data([1, 2, 3, 1, 2], [80.0, 80.1, 80.2, 81.0, 81.2], ["A", "A", "A", "B", "B"])
        >>> data.demean(data.lap_time).round(6).tolist()
        [-0.1, -0.0, 0.1, -0.1, 0.1]
        """
        values = self._per_lap(values)
        return values - self.stint_means(values)[self.stint_index]

    def stint_means(self, values):
        """Mean of ``values`` within each stint, shape (n_stints,).

        Parameters
        ----------
        values : array_like of float, shape (n_laps,)
            One value per lap.

        Returns
        -------
        numpy.ndarray of float, shape (n_stints,)
            Mean of ``values`` within each stint, in stint-index order.

        Raises
        ------
        ValueError
            If ``values`` does not have exactly one entry per lap.

        Example
        -------
        >>> data = prepare_stint_data([1, 2, 3, 1, 2], [80.0, 80.1, 80.2, 81.0, 81.2], ["A", "A", "A", "B", "B"])
        >>> data.stint_means(data.lap_time).round(6).tolist()
        [80.1, 81.1]
        """
        values = self._per_lap(values)
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

    Parameters
    ----------
    tyre_age : array_like of float
        Tyre ages [laps], each finite and >= 0. A scalar is treated as one age.
    name : str, optional
        Name used in error messages (default ``"tyre_age"``).

    Returns
    -------
    numpy.ndarray of float, shape (n,)
        The ages as a 1-D float array.

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

    Parameters
    ----------
    data : StintData
        The training data.
    n_parameters : int
        Number of degradation parameters, >= 0 (e.g. 1 for a straight line).

    Returns
    -------
    int
        Residual degrees of freedom, n_laps - n_stints - n_parameters (>= 1).

    Raises
    ------
    TypeError
        If ``data`` is not a :class:`StintData`.
    ValueError
        If ``n_parameters`` is not an integer >= 0, or fewer than 1 residual
        degree of freedom is left.

    Example
    -------
    >>> data = prepare_stint_data([1, 2, 3, 1, 2], [80.0, 80.1, 80.2, 81.0, 81.2], ["A", "A", "A", "B", "B"])
    >>> check_degrees_of_freedom(data, 1)
    2
    >>> check_degrees_of_freedom(data, 3)
    Traceback (most recent call last):
    ...
    ValueError: Too few laps: 5 laps, 2 stints and 3 degradation parameters leave 0 residual degrees of freedom.
    """
    if not isinstance(data, StintData):
        raise TypeError(f"data must be a StintData, got {type(data).__name__}.")
    if isinstance(n_parameters, bool) or not isinstance(n_parameters, (int, np.integer)) or n_parameters < 0:
        raise ValueError(f"n_parameters must be an integer >= 0, got {n_parameters!r}.")
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

    Example
    -------
    >>> check = check_non_negative(lambda n: 0.05 * n - 0.1, 40.0, 0.01)
    >>> check.min_degradation_s, check.age_of_minimum, check.violated
    (-0.1, 0.0, True)
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

    Raises
    ------
    TypeError
        If ``degradation_function`` is not callable.
    ValueError
        If ``max_age`` or ``tolerance_s`` is negative or not finite, ``ages``
        contains invalid ages, or the function returns the wrong shape.

    Example
    -------
    >>> check_non_negative(lambda n: 0.07 * n, 40.0, 0.01).violated
    False
    """
    if not callable(degradation_function):
        raise TypeError("degradation_function must be callable, d(ages) -> degradation [s].")
    if not np.isfinite(max_age) or max_age < 0:
        raise ValueError(f"max_age must be a finite number of laps >= 0, got {max_age}.")
    if not np.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError(f"tolerance_s must be a finite number >= 0, got {tolerance_s}.")
    if ages is None:
        ages = np.arange(0.0, max_age + 0.25, 0.5)
    ages = check_tyre_age(ages, "ages")
    values = np.asarray(degradation_function(ages), dtype=float)
    if values.shape != ages.shape:
        raise ValueError(f"degradation_function returned shape {values.shape}, expected {ages.shape}.")
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

    Example
    -------
    >>> data = prepare_stint_data([1, 2, 3, 1, 2, 3], [80.0, 80.1, 80.2, 81.0, 81.1, 81.3], ["A", "A", "A", "B", "B", "B"])
    >>> mean_time = lambda age, time, ids: [np.mean(time)]
    >>> result = stint_bootstrap(data, mean_time, ("mean lap time",), 50, 0.95, 42)
    >>> result.estimates.shape, result.seed
    ((50, 1), 42)
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

    Parameters
    ----------
    data : StintData
        The original training data.
    rng : numpy.random.Generator
        Random number generator (seeded by the caller, rule 11).

    Returns
    -------
    tyre_age : numpy.ndarray of float
        Tyre ages [laps] of the resampled laps.
    lap_time : numpy.ndarray of float
        Their lap times [s].
    stint_id : numpy.ndarray of int
        New stint ids 0 .. n_stints - 1, one per drawn stint.

    Raises
    ------
    TypeError
        If ``data`` is not a :class:`StintData` or ``rng`` is not a NumPy Generator.

    Example
    -------
    >>> data = prepare_stint_data([1, 2, 3, 1, 2], [80.0, 80.1, 80.2, 81.0, 81.2], ["A", "A", "A", "B", "B"])
    >>> ages, times, ids = resample_stints(data, np.random.default_rng(42))
    >>> ids.tolist(), times.tolist()
    ([0, 0, 0, 1, 1], [80.0, 80.1, 80.2, 81.0, 81.2])
    """
    if not isinstance(data, StintData):
        raise TypeError(f"data must be a StintData, got {type(data).__name__}.")
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator, e.g. numpy.random.default_rng(42).")
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
    """Return text lines 'name  value  (analytic SE)  [bootstrap SE, CI]'.

    Parameters
    ----------
    names : sequence of str
        Parameter names.
    values : sequence of float
        Fitted values, same length as ``names`` (units of each parameter).
    analytic_se : sequence of float
        Analytic standard errors, same length.
    bootstrap : BootstrapResult or None, optional
        If given, its standard errors and confidence interval are appended.

    Returns
    -------
    list of str
        One formatted line per parameter.

    Raises
    ------
    ValueError
        If the lengths of ``names``, ``values``, ``analytic_se`` (and the
        bootstrap) differ.

    Example
    -------
    >>> format_parameter_table(["a [s/lap]"], [0.0597], [0.0021])
    ['  a [s/lap]       0.0597   SE(analytic) 0.0021']
    """
    if not len(names) == len(values) == len(analytic_se):
        raise ValueError(f"names, values and analytic_se must have the same length, got "
                         f"{len(names)}, {len(values)} and {len(analytic_se)}.")
    if bootstrap is not None and len(bootstrap.standard_errors) != len(names):
        raise ValueError("bootstrap must have one standard error per parameter name.")
    lines = []
    for i, name in enumerate(names):
        line = f"  {name:<14s} {values[i]: .6g}   SE(analytic) {analytic_se[i]:.3g}"
        if bootstrap is not None:
            line += (f"   SE(bootstrap) {bootstrap.standard_errors[i]:.3g}"
                     f"   {bootstrap.confidence_level:.0%} CI [{bootstrap.lower[i]:.4g}, "
                     f"{bootstrap.upper[i]:.4g}]")
        lines.append(line)
    return lines
