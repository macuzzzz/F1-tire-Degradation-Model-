"""Race-time model and pit-stop optimisation (Phase 6, DECISIONS.md D56-D66).

Race-time model
---------------
A strategy is a sequence of stints, each on one compound, separated by pit
stops. Every stint starts on a NEW tyre (D61), so on the j-th lap of a stint
the tyre age is j. The predicted time of race lap n, on compound c at tyre
age j, is

    t(n) = base_c + d_c(j) - k_fuel (n - 1)

- ``base_c``: lap time of a new tyre of compound c for a typical car,
  fuel-corrected to full fuel (D57, D60);
- ``d_c(j)``: the degradation model of compound c (d(0) = 0);
- ``-k_fuel (n - 1)``: the fuel effect added back (D62), so the total is a
  real race time. It sums to k_fuel N (N - 1) / 2 for EVERY strategy, so it
  never changes which strategy is best.

The total race time is the sum over all laps plus one pit loss per stop.

Optimising a one-stop race (pit lap L = number of laps on the first set)
-------------------------------------------------------------------------
(a) brute force: evaluate every feasible integer L (the reference);
(b) continuous relaxation: extend the race time to real L, solve
    dT/dL = 0 with my central difference + secant (or Newton with my second
    difference), then round and check the neighbouring integers (D64).

Feasibility (D63): no stint may exceed the largest tyre age with enough data
for its compound, so the models are never extrapolated far.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tyredeg.models.polynomial import PolynomialDegradationModel
from tyredeg.models.wear_ode import WearODEModel
from tyredeg.numerics.differentiation import central_difference, central_second_difference
from tyredeg.numerics.root_finding import (
    DivergenceError,
    NotConvergedError,
    ZeroDerivativeError,
    newton,
    secant,
)

VALID_ROOT_FINDERS = ("secant", "newton")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CompoundModel:
    """Everything the race-time model needs about one compound.

    Attributes
    ----------
    compound : str
        Pirelli code, e.g. "C3".
    model : object
        Fitted degradation model with ``degradation(tyre_age)`` [s].
    base_time : float
        New-tyre lap time [s] for the typical car, fuel-corrected to full fuel.
    max_stint_laps : int
        Longest allowed stint on this compound [laps] (D63).
    """

    compound: str
    model: object
    base_time: float
    max_stint_laps: int

    def __post_init__(self):
        if not (np.isfinite(self.base_time) and self.base_time > 0):
            raise ValueError(f"base_time must be a positive number of seconds, got {self.base_time!r}.")
        if isinstance(self.max_stint_laps, bool) or not isinstance(self.max_stint_laps, (int, np.integer)) \
                or self.max_stint_laps < 1:
            raise ValueError(f"max_stint_laps must be an integer >= 1, got {self.max_stint_laps!r}.")
        if not hasattr(self.model, "degradation"):
            raise TypeError("model must have a degradation(tyre_age) method.")


class LinearDegradation:
    """Degradation d(n) = rate * n with a rate set directly (no fitting).

    Used by the sensitivity analysis to perturb a fitted linear wear rate
    (e.g. by +/- 2 standard errors) while keeping everything else fixed.

    Parameters
    ----------
    rate : float
        Wear rate [s/lap], finite.

    Example
    -------
    >>> LinearDegradation(0.06).degradation([10.0]).tolist()
    [0.6]
    """

    def __init__(self, rate):
        if isinstance(rate, bool) or not np.isfinite(rate):
            raise ValueError(f"rate must be a finite number, got {rate!r}.")
        self.rate = float(rate)

    def degradation(self, tyre_age):
        return self.rate * np.asarray(tyre_age, dtype=float).reshape(-1)


def _check_int(value, name, minimum):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} must be an integer, got {value!r}.")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}.")
    return int(value)


def _check_race_inputs(models, total_laps, pit_loss, k_fuel):
    if not isinstance(models, dict) or not models:
        raise TypeError("models must be a non-empty dict {compound: CompoundModel}.")
    total_laps = _check_int(total_laps, "total_laps", 2)
    if isinstance(pit_loss, bool) or not np.isfinite(pit_loss) or pit_loss <= 0:
        raise ValueError(f"pit_loss must be a positive number of seconds, got {pit_loss!r}.")
    if isinstance(k_fuel, bool) or not np.isfinite(k_fuel) or k_fuel < 0:
        raise ValueError(f"k_fuel must be a number >= 0, got {k_fuel!r}.")
    return total_laps


def _check_compounds(compounds, models):
    """Each compound must be known; a dry race must use at least two different ones."""
    for compound in compounds:
        if compound not in models:
            raise ValueError(f"Unknown compound {compound!r}; available: {sorted(models)}.")
    if len(set(compounds)) < 2:
        raise ValueError(
            f"A dry race must use at least two different compounds, got {list(compounds)}."
        )


# ---------------------------------------------------------------------------
# Race time (integer stint lengths)
# ---------------------------------------------------------------------------
def stint_time(compound_model, n_laps):
    """Sum of predicted fuel-corrected lap times over a stint of ``n_laps`` new-tyre laps [s].

    = n_laps * base + d(1) + d(2) + ... + d(n_laps)

    Example
    -------
    >>> class Linear:
    ...     def degradation(self, n):
    ...         return 0.1 * np.asarray(n, dtype=float)
    >>> stint_time(CompoundModel("C3", Linear(), 80.0, 40), 3)   # 240 + 0.1 (1 + 2 + 3)
    240.6
    """
    if n_laps == 0:
        return 0.0
    ages = np.arange(1.0, n_laps + 1.0)
    return float(n_laps * compound_model.base_time + np.sum(compound_model.model.degradation(ages)))


def fuel_effect_total(total_laps, k_fuel):
    """Total time saved by burning fuel over the race: k_fuel N (N - 1) / 2 [s].

    Example
    -------
    >>> fuel_effect_total(70, 0.046)   # 0.046 * 70 * 69 / 2
    111.09
    """
    return float(round(k_fuel * total_laps * (total_laps - 1) / 2.0, 12))


def total_race_time(compounds, stint_lengths, models, pit_loss, k_fuel=0.0, add_fuel_effect=True,
                    enforce_max_stint=True):
    """Predicted race time for any number of stints [s].

    Parameters
    ----------
    compounds : sequence of str
        Compound of each stint, at least two different ones (dry-race rule).
    stint_lengths : sequence of int
        Laps in each stint, each >= 1; their sum is the race length.
    models : dict
        {compound: CompoundModel}.
    pit_loss : float
        Time lost per pit stop [s], > 0.
    k_fuel : float, optional
        Fuel coefficient [s per lap of fuel], >= 0. Default 0.
    add_fuel_effect : bool, optional
        Subtract the fuel effect so the total is a real race time (D62).
    enforce_max_stint : bool, optional
        Raise if a stint exceeds its compound's ``max_stint_laps`` (D63).

    Returns
    -------
    float

    Raises
    ------
    TypeError, ValueError
        For invalid inputs, a single compound, or a stint that is too long.

    Example
    -------
    >>> # see race_time for the one-stop case
    """
    if len(compounds) != len(stint_lengths) or len(compounds) < 2:
        raise ValueError("Need one compound per stint and at least two stints.")
    total_laps = int(np.sum([_check_int(n, "stint length", 1) for n in stint_lengths]))
    _check_race_inputs(models, total_laps, pit_loss, k_fuel)
    _check_compounds(compounds, models)
    time = 0.0
    for compound, laps in zip(compounds, stint_lengths):
        if enforce_max_stint and laps > models[compound].max_stint_laps:
            raise ValueError(f"A {laps}-lap stint on {compound} exceeds its limit of "
                             f"{models[compound].max_stint_laps} laps (no extrapolation, D63).")
        time += stint_time(models[compound], laps)
    time += pit_loss * (len(stint_lengths) - 1)
    if add_fuel_effect:
        time -= fuel_effect_total(total_laps, k_fuel)
    return time


def race_time(pit_lap, compound_1, compound_2, models, total_laps, pit_loss, k_fuel=0.0,
              add_fuel_effect=True, enforce_max_stint=True):
    """Predicted time of a one-stop race [s].

    Stint 1 runs laps 1..pit_lap on ``compound_1``; stint 2 runs the remaining
    ``total_laps - pit_lap`` laps on a new ``compound_2`` (tyre age resets).

    Parameters
    ----------
    pit_lap : int
        Last lap of the first stint, 1 <= pit_lap < total_laps.
    compound_1, compound_2 : str
        Different compounds (dry-race rule).
    models : dict
        {compound: CompoundModel}.
    total_laps : int
        Race length [laps], >= 2.
    pit_loss : float
        Time lost by the stop [s], > 0.
    k_fuel : float, optional
        Fuel coefficient [s per lap of fuel], >= 0.
    add_fuel_effect : bool, optional
        Return a real race time (True, default) or a fuel-corrected one.
    enforce_max_stint : bool, optional
        Raise for stints longer than the compound's limit (default True).

    Returns
    -------
    float

    Raises
    ------
    TypeError
        For a non-integer pit lap or wrong types.
    ValueError
        If the compounds are equal or unknown, pit_lap is outside
        [1, total_laps - 1], pit_loss <= 0, or a stint is too long.

    Example
    -------
    >>> class Linear:
    ...     def degradation(self, n):
    ...         return 0.1 * np.asarray(n, dtype=float)
    >>> models = {c: CompoundModel(c, Linear(), 80.0, 10) for c in ("C3", "C4")}
    >>> race_time(2, "C3", "C4", models, 4, pit_loss=20.0)   # 2 x (160 + 0.3) + 20
    340.6
    """
    total_laps = _check_race_inputs(models, total_laps, pit_loss, k_fuel)
    pit_lap = _check_int(pit_lap, "pit_lap", 1)
    if pit_lap >= total_laps:
        raise ValueError(f"pit_lap must be < total_laps ({total_laps}), got {pit_lap}.")
    if compound_1 == compound_2:
        raise ValueError(f"The two stints must use different compounds, got {compound_1} twice.")
    return total_race_time((compound_1, compound_2), (pit_lap, total_laps - pit_lap), models,
                           pit_loss, k_fuel, add_fuel_effect, enforce_max_stint)


# ---------------------------------------------------------------------------
# Continuous relaxation
# ---------------------------------------------------------------------------
def _poly_antiderivative(coefficients, x):
    """D(x) = sum_k c_k x^(k+1) / (k+1) for d(x) = sum_k c_k x^k, k = 1..p."""
    value = 0.0
    for power, coefficient in enumerate(coefficients, start=1):
        value += coefficient * x ** (power + 1) / (power + 1)
    return value


def _ode_antiderivative(a, b, x):
    """G(x) = integral_0^x a (exp(b s) - 1) / b ds = a (expm1(b x) - b x) / b^2.

    For |b x| < 1e-4 the series a (x^2/2 + b x^3/6 + b^2 x^4/24) is used,
    because expm1(b x) - b x loses digits to cancellation there.
    """
    if abs(b * x) < 1e-4:
        return a * (x**2 / 2.0 + b * x**3 / 6.0 + b**2 * x**4 / 24.0)
    return a * (np.expm1(b * x) - b * x) / b**2


def cumulative_degradation(model, n_laps):
    """Smooth extension of d(1) + ... + d(n) to real n (for the continuous relaxation).

    The sum is replaced by the integral of d from 1/2 to n + 1/2 (midpoint
    rule): integral_{j-1/2}^{j+1/2} d = d(j) exactly when d is linear, so for
    linear degradation the extension equals the sum at every integer n and
    is smooth in between. For curved d the difference is tiny (O(d'')).

    Parameters
    ----------
    model : PolynomialDegradationModel or WearODEModel
        Fitted model with a closed-form antiderivative.
    n_laps : float
        Stint length [laps], >= 0 (need not be an integer).

    Returns
    -------
    float

    Raises
    ------
    TypeError
        For models without a closed-form integral (e.g. KNN): use brute force.
    ValueError
        If n_laps < 0.

    Example
    -------
    >>> model = PolynomialDegradationModel("C3").fit([1, 2, 3], [80.1, 80.2, 80.3])
    >>> round(cumulative_degradation(model, 3.0), 9)   # 0.1 + 0.2 + 0.3
    0.6
    """
    if not n_laps >= 0:
        raise ValueError(f"n_laps must be >= 0, got {n_laps}.")
    if n_laps == 0:
        return 0.0
    upper, lower = n_laps + 0.5, 0.5
    if isinstance(model, PolynomialDegradationModel):
        coefficients = model.params()["coefficients"]
        return float(_poly_antiderivative(coefficients, upper) - _poly_antiderivative(coefficients, lower))
    if isinstance(model, WearODEModel):
        p = model.params()
        return float(_ode_antiderivative(p["a"], p["b"], upper) - _ode_antiderivative(p["a"], p["b"], lower))
    if isinstance(model, LinearDegradation):
        return float(_poly_antiderivative([model.rate], upper) - _poly_antiderivative([model.rate], lower))
    raise TypeError(
        f"{type(model).__name__} has no closed-form integral; use the brute-force optimiser."
    )


def race_time_continuous(pit_lap, compound_1, compound_2, models, total_laps, pit_loss, k_fuel=0.0,
                         add_fuel_effect=True):
    """One-stop race time for a REAL-valued pit lap L (the continuous relaxation).

    Same as :func:`race_time` with each stint's sum of degradation replaced by
    :func:`cumulative_degradation`; equal to it at integer L for linear models.
    Stint limits are not applied here (they are applied after rounding).

    Raises
    ------
    ValueError
        If L is outside (0, total_laps) or the compounds are invalid.
    TypeError
        For models without a closed-form integral.

    Example
    -------
    >>> race_time_continuous(32.5, "C3", "C4", models, 70, 20.9)  # doctest: +SKIP
    """
    total_laps = _check_race_inputs(models, total_laps, pit_loss, k_fuel)
    _check_compounds((compound_1, compound_2), models)
    if not 0 < pit_lap < total_laps:
        raise ValueError(f"pit_lap must lie in (0, {total_laps}), got {pit_lap}.")
    first, second = models[compound_1], models[compound_2]
    second_laps = total_laps - pit_lap
    time = (pit_lap * first.base_time + cumulative_degradation(first.model, pit_lap)
            + second_laps * second.base_time + cumulative_degradation(second.model, second_laps)
            + pit_loss)
    if add_fuel_effect:
        time -= fuel_effect_total(total_laps, k_fuel)
    return time


# ---------------------------------------------------------------------------
# Optimisers
# ---------------------------------------------------------------------------
@dataclass
class StrategyResult:
    """Result of one optimisation.

    Attributes
    ----------
    compounds : tuple of str
        Compound of each stint, in order.
    method : str
        "brute force", "secant" or "newton".
    pit_laps : tuple of int
        Lap(s) at the end of which the car pits.
    total_time : float
        Predicted race time [s].
    stint_lengths : tuple of int
    iterations : int
        Root-finder iterations (brute force: number of candidates tried).
    nfev : int
        Race-time evaluations (continuous + integer).
    continuous_root : float or None
        Stationary point of the relaxed race time (continuous methods).
    constraint_active : bool
        True if the stint limits moved the optimum away from the unconstrained one.
    note : str
    """

    compounds: tuple
    method: str
    pit_laps: tuple
    total_time: float
    stint_lengths: tuple
    iterations: int
    nfev: int
    continuous_root: float | None = None
    constraint_active: bool = False
    note: str = ""
    extra: dict = field(default_factory=dict)


def feasible_pit_laps(compound_1, compound_2, models, total_laps):
    """Integer pit laps for which both stints respect their limits (D63).

    Returns
    -------
    numpy.ndarray of int
        Possibly empty if no one-stop race is feasible.

    Example
    -------
    >>> class Zero:
    ...     def degradation(self, n):
    ...         return np.zeros(np.size(n))
    >>> models = {"C3": CompoundModel("C3", Zero(), 80.0, 40), "C4": CompoundModel("C4", Zero(), 80.0, 35)}
    >>> feasible_pit_laps("C3", "C4", models, 70).tolist()   # C3 <= 40 laps, C4 <= 35 laps
    [35, 36, 37, 38, 39, 40]
    """
    low = max(1, total_laps - models[compound_2].max_stint_laps)
    high = min(total_laps - 1, models[compound_1].max_stint_laps)
    return np.arange(low, high + 1)


def optimise_brute_force(compound_1, compound_2, models, total_laps, pit_loss, k_fuel=0.0,
                         add_fuel_effect=True):
    """Try every feasible integer pit lap; return the fastest (the reference method).

    Raises
    ------
    ValueError
        If no pit lap is feasible, or for invalid inputs (see :func:`race_time`).

    Example
    -------
    >>> optimise_brute_force("C3", "C4", models, 70, 20.9, 0.046)  # doctest: +SKIP
    """
    total_laps = _check_race_inputs(models, total_laps, pit_loss, k_fuel)
    _check_compounds((compound_1, compound_2), models)
    candidates = feasible_pit_laps(compound_1, compound_2, models, total_laps)
    if candidates.size == 0:
        raise ValueError(f"No feasible one-stop race {compound_1}->{compound_2} within the stint limits.")
    times = [race_time(int(lap), compound_1, compound_2, models, total_laps, pit_loss, k_fuel,
                       add_fuel_effect) for lap in candidates]
    best = int(np.argmin(times))
    pit_lap = int(candidates[best])
    return StrategyResult(
        compounds=(compound_1, compound_2), method="brute force", pit_laps=(pit_lap,),
        total_time=float(times[best]), stint_lengths=(pit_lap, total_laps - pit_lap),
        iterations=int(candidates.size), nfev=int(candidates.size),
        extra={"times": dict(zip(candidates.tolist(), times))},
    )


def optimise_continuous(compound_1, compound_2, models, total_laps, pit_loss, k_fuel=0.0,
                        add_fuel_effect=True, root_finder="secant", xtol=1e-6, ftol=0.0):
    """Continuous relaxation: solve dT/dL = 0, then round and check neighbours (D64).

    Steps:

    1. dT/dL is computed with my central difference of
       :func:`race_time_continuous`.
    2. Its root is found with my secant method (started at the two ends of
       the feasible window) or Newton's method (started at the window
       centre, with my central second difference as the derivative).
    3. Candidates floor(root) - 1 ... ceil(root) + 1 are clipped into the
       feasible window and evaluated with the exact integer
       :func:`race_time`; the fastest wins. If the root lies outside the
       window, the nearest window end wins and ``constraint_active`` is set.
       If the root finder fails (e.g. a flat or non-convex race time), both
       window ends are evaluated instead and a note is recorded.

    Parameters
    ----------
    compound_1, compound_2, models, total_laps, pit_loss, k_fuel, add_fuel_effect
        As for :func:`race_time`.
    root_finder : str, optional
        "secant" (default) or "newton".
    xtol, ftol : float, optional
        Root-finding tolerances (D64: 1e-6 laps, residual test off).

    Returns
    -------
    StrategyResult

    Raises
    ------
    ValueError
        For invalid inputs, an unknown root finder, or no feasible pit lap.
    TypeError
        For models without a closed-form integral (KNN).

    Example
    -------
    >>> optimise_continuous("C3", "C4", models, 70, 20.9, 0.046, root_finder="newton")  # doctest: +SKIP
    """
    if root_finder not in VALID_ROOT_FINDERS:
        raise ValueError(f"root_finder must be one of {VALID_ROOT_FINDERS}, got {root_finder!r}.")
    total_laps = _check_race_inputs(models, total_laps, pit_loss, k_fuel)
    _check_compounds((compound_1, compound_2), models)
    window = feasible_pit_laps(compound_1, compound_2, models, total_laps)
    if window.size == 0:
        raise ValueError(f"No feasible one-stop race {compound_1}->{compound_2} within the stint limits.")
    calls = {"continuous": 0, "integer": 0}

    def relaxed(pit_lap):
        calls["continuous"] += 1
        return race_time_continuous(pit_lap, compound_1, compound_2, models, total_laps, pit_loss,
                                    k_fuel, add_fuel_effect)

    def slope(pit_lap):
        return central_difference(relaxed, pit_lap)

    note, root, iterations = "", None, 0
    try:
        if root_finder == "secant":
            low, high = float(window[0]), float(window[-1])
            if low == high:
                low, high = max(0.5, low - 1.0), min(total_laps - 0.5, high + 1.0)
            result = secant(slope, low, high, xtol=xtol, ftol=ftol,
                            divergence_limit=float(total_laps))
        else:
            result = newton(slope, lambda x: central_second_difference(relaxed, x),
                            float(window[0] + window[-1]) / 2.0, xtol=xtol, ftol=ftol,
                            divergence_limit=float(total_laps))
        root, iterations = float(result.root), result.iterations
    except (ZeroDerivativeError, DivergenceError, NotConvergedError, ValueError) as error:
        note = f"root finding failed ({type(error).__name__}); window ends compared instead"

    if root is None or not 0 < root < total_laps:
        candidates = {int(window[0]), int(window[-1])}
    else:
        nearby = range(int(np.floor(root)) - 1, int(np.ceil(root)) + 2)
        candidates = {int(np.clip(lap, window[0], window[-1])) for lap in nearby}

    def exact(lap):
        calls["integer"] += 1
        return race_time(lap, compound_1, compound_2, models, total_laps, pit_loss, k_fuel,
                         add_fuel_effect)

    times = {lap: exact(lap) for lap in sorted(candidates)}
    pit_lap = min(times, key=times.get)
    constraint_active = root is not None and not window[0] - 0.5 <= root <= window[-1] + 0.5
    return StrategyResult(
        compounds=(compound_1, compound_2), method=root_finder, pit_laps=(pit_lap,),
        total_time=float(times[pit_lap]), stint_lengths=(pit_lap, total_laps - pit_lap),
        iterations=iterations, nfev=calls["continuous"] + calls["integer"],
        continuous_root=root, constraint_active=bool(constraint_active), note=note,
        extra={"nfev_continuous": calls["continuous"], "nfev_integer": calls["integer"]},
    )


def optimise_two_stop(compounds, models, total_laps, pit_loss, k_fuel=0.0, add_fuel_effect=True):
    """Brute force over every pair of pit laps for a three-stint sequence.

    Parameters
    ----------
    compounds : sequence of 3 str
        Compound of each stint; at least two different ones.
    models, total_laps, pit_loss, k_fuel, add_fuel_effect
        As for :func:`race_time`.

    Returns
    -------
    StrategyResult
        ``pit_laps`` = (first stop, second stop).

    Raises
    ------
    ValueError
        For invalid inputs or no feasible combination.

    Example
    -------
    >>> optimise_two_stop(("C3", "C4", "C3"), models, 70, 20.9, 0.046)  # doctest: +SKIP
    """
    if len(compounds) != 3:
        raise ValueError("A two-stop race has exactly three stints.")
    total_laps = _check_race_inputs(models, total_laps, pit_loss, k_fuel)
    _check_compounds(compounds, models)
    # Stint sums for every possible stint length, computed once per compound.
    sums = {c: [stint_time(models[c], n) for n in range(total_laps + 1)] for c in set(compounds)}
    limits = [models[c].max_stint_laps for c in compounds]
    best, evaluations = None, 0
    for first in range(1, min(limits[0], total_laps - 2) + 1):
        for second in range(1, min(limits[1], total_laps - first - 1) + 1):
            third = total_laps - first - second
            if third > limits[2]:
                continue
            evaluations += 1
            time = sums[compounds[0]][first] + sums[compounds[1]][second] + sums[compounds[2]][third]
            if best is None or time < best[0]:
                best = (time, first, second, third)
    if best is None:
        raise ValueError(f"No feasible two-stop race {'->'.join(compounds)} within the stint limits.")
    time, first, second, third = best
    time += 2 * pit_loss
    if add_fuel_effect:
        time -= fuel_effect_total(total_laps, k_fuel)
    return StrategyResult(
        compounds=tuple(compounds), method="brute force", pit_laps=(first, first + second),
        total_time=float(time), stint_lengths=(first, second, third), iterations=evaluations,
        nfev=evaluations,
    )


def compare_strategies(models, total_laps, pit_loss, k_fuel=0.0, add_fuel_effect=True,
                       include_two_stop=True, xtol=1e-6, ftol=0.0):
    """Optimise every one-stop compound order (all methods) and, optionally, two-stop sequences.

    Returns
    -------
    methods : pandas.DataFrame
        One row per (one-stop strategy, method): optimum, time, iterations, nfev.
    ranking : pandas.DataFrame
        One row per strategy (best result), sorted fastest first, with the
        gap to the fastest [s].

    Example
    -------
    >>> methods, ranking = compare_strategies(models, 70, 20.9, 0.046)  # doctest: +SKIP
    """
    rows = []
    compounds = sorted(models)
    for first, second in itertools.permutations(compounds, 2):
        results = [optimise_brute_force(first, second, models, total_laps, pit_loss, k_fuel, add_fuel_effect)]
        for finder in VALID_ROOT_FINDERS:
            try:
                results.append(optimise_continuous(first, second, models, total_laps, pit_loss, k_fuel,
                                                   add_fuel_effect, finder, xtol, ftol))
            except TypeError:
                pass  # no closed-form integral (KNN): brute force only
        rows += [_result_row(result, "1-stop") for result in results]
    if include_two_stop:
        for sequence in itertools.product(compounds, repeat=3):
            if len(set(sequence)) < 2:
                continue
            try:
                result = optimise_two_stop(sequence, models, total_laps, pit_loss, k_fuel, add_fuel_effect)
            except ValueError:
                continue  # no feasible combination within the stint limits
            rows.append(_result_row(result, "2-stop"))
    methods = pd.DataFrame(rows)
    ranking = methods.loc[methods.groupby("strategy")["total_time"].idxmin()]
    ranking = ranking.sort_values("total_time").reset_index(drop=True)
    ranking["gap_to_best_s"] = ranking["total_time"] - ranking["total_time"].iloc[0]
    ranking.insert(0, "rank", np.arange(1, len(ranking) + 1))
    return methods, ranking


def _result_row(result, kind):
    return {
        "strategy": " -> ".join(result.compounds), "stops": kind, "method": result.method,
        "pit_laps": " & ".join(str(lap) for lap in result.pit_laps),
        "stint_lengths": "+".join(str(n) for n in result.stint_lengths),
        "total_time": result.total_time, "iterations": result.iterations, "nfev": result.nfev,
        "continuous_root": result.continuous_root, "constraint_active": result.constraint_active,
        "note": result.note,
    }


# ---------------------------------------------------------------------------
# Building the strategy inputs from data (D60, D63)
# ---------------------------------------------------------------------------
def max_stint_from_data(tyre_age, min_laps):
    """Largest tyre age [laps] with at least ``min_laps`` clean laps (D63).

    Example
    -------
    >>> max_stint_from_data([1, 1, 2, 2, 3], min_laps=2)
    2
    """
    ages = np.asarray(tyre_age, dtype=float)
    _check_int(min_laps, "min_laps", 1)
    values, counts = np.unique(ages, return_counts=True)
    supported = values[counts >= min_laps]
    if supported.size == 0:
        raise ValueError(f"No tyre age has {min_laps} or more laps.")
    return int(np.floor(supported.max()))


def compound_pace_delta(offsets, reference, other):
    """Order-balanced pace difference other - reference for the same car [s] (D60).

    For each driver-race that used both compounds, the difference of their
    stint offsets is taken. These differences depend strongly on which
    compound ran FIRST (a later stint looks faster, CHALLENGES.md C2), so the
    median is taken separately for each order and the two medians are
    averaged: a common order effect e then cancels, since
    ((delta - e) + (delta + e)) / 2 = delta.

    Parameters
    ----------
    offsets : pandas.DataFrame
        Columns race, driver, stint (int), compound, offset [s] (one row per stint).
    reference, other : str
        The two compounds.

    Returns
    -------
    dict
        delta (order-balanced), median_other_first, median_reference_first,
        n_other_first, n_reference_first.

    Raises
    ------
    ValueError
        If either order has no driver-race.

    Example
    -------
    >>> df = pd.DataFrame({"race": ["r"] * 4, "driver": ["A", "A", "B", "B"], "stint": [1, 2, 1, 2],
    ...                    "compound": ["C4", "C3", "C3", "C4"], "offset": [80.3, 80.0, 80.4, 80.0]})
    >>> compound_pace_delta(df, "C3", "C4")["delta"]   # orders: +0.3 and -0.4 -> -0.05
    -0.05
    """
    differences = {"other_first": [], "reference_first": []}
    for _, group in offsets.groupby(["race", "driver"]):
        ref = group[group["compound"] == reference]
        oth = group[group["compound"] == other]
        if ref.empty or oth.empty:
            continue
        # The first stint of each compound represents it for this driver-race.
        ref_row = ref.sort_values("stint").iloc[0]
        oth_row = oth.sort_values("stint").iloc[0]
        key = "other_first" if oth_row["stint"] < ref_row["stint"] else "reference_first"
        differences[key].append(oth_row["offset"] - ref_row["offset"])
    if not differences["other_first"] or not differences["reference_first"]:
        raise ValueError("Both stint orders are needed for the order-balanced estimate.")
    first = float(np.median(differences["other_first"]))
    second = float(np.median(differences["reference_first"]))
    return {"delta": round((first + second) / 2.0, 12), "median_other_first": first,
            "median_reference_first": second, "n_other_first": len(differences["other_first"]),
            "n_reference_first": len(differences["reference_first"])}


# ---------------------------------------------------------------------------
# Assembling all strategy inputs from prepared data (used by Phases 6 and 7)
# ---------------------------------------------------------------------------
@dataclass
class StrategyInputs:
    """Everything needed to optimise a strategy, built from data.

    Attributes
    ----------
    models : dict
        {compound: CompoundModel}.
    total_laps : int
    pit_loss : float
        [s].
    pit_info : dict
        How the pit loss was obtained (median, quartiles, number of stops).
    deltas : dict
        {compound: output of :func:`compound_pace_delta`} for non-reference compounds.
    info : pandas.DataFrame
        One row per compound: model, laps, stints, stint limit, rate, base time.
    k_fuel : float
        Fuel coefficient used for the fuel correction [s per lap of fuel].
    """

    models: dict
    total_laps: int
    pit_loss: float
    pit_info: dict
    deltas: dict
    info: pd.DataFrame
    k_fuel: float


def _offsets_table(model, compound):
    """One row per stint: race, driver, stint number, compound, offset [s]."""
    rows = []
    for label, offset in model.stint_offsets().items():
        race, driver, stint = label.split("|")
        rows.append({"race": race, "driver": driver, "stint": int(stint), "compound": compound,
                     "offset": offset})
    return pd.DataFrame(rows)


def refuel(laps, k_fuel):
    """Copy of ``laps`` with FuelCorrectedTime recomputed for another fuel coefficient.

    Cleaning does not depend on k_fuel (the outlier rule uses raw times, D19),
    so only this column changes.

    Example
    -------
    >>> df = pd.DataFrame({"LapTime": [80.0], "LapNumber": [11.0], "TotalLaps": [70.0],
    ...                    "FuelCorrectedTime": [80.46]})
    >>> refuel(df, 0.1)["FuelCorrectedTime"].tolist()
    [81.0]
    """
    from tyredeg.fuel_correction import add_fuel_corrected_times

    return add_fuel_corrected_times(laps.drop(columns=["FuelCorrectedTime"]), k_fuel)


def build_strategy_inputs(all_laps, clean, config, model_names, k_fuel=None, min_laps_at_max_age=None,
                          pit_loss_override=None):
    """Fit the degradation models and assemble the strategy inputs (D56-D63).

    Parameters
    ----------
    all_laps, clean : pandas.DataFrame
        All laps and clean laps (with ``StintId``) of the strategy races,
        e.g. from :func:`tyredeg.preparation.prepare_laps`.
    config : Config
        Project configuration (strategy compounds, model settings, laps).
    model_names : dict
        {compound: candidate model name}, e.g. {"C3": "polynomial degree 1"}.
    k_fuel : float or None, optional
        Fuel coefficient; None = ``config.k_fuel``. A different value
        RECOMPUTES the fuel-corrected times and refits everything (Phase 7).
    min_laps_at_max_age : int or None, optional
        Stint-limit rule (D63); None = ``config.strategy.min_laps_at_max_age``.
    pit_loss_override : float or None, optional
        Use this pit loss [s] instead of estimating it.

    Returns
    -------
    StrategyInputs

    Raises
    ------
    ValueError
        For unknown model names, inconsistent race lengths or missing data.

    Example
    -------
    >>> inputs = build_strategy_inputs(prep.all_laps, prep.clean, config,
    ...                                {"C3": "polynomial degree 1", "C4": "polynomial degree 1"})  # doctest: +SKIP
    """
    from tyredeg.fuel_correction import estimate_pit_loss
    from tyredeg.validation import candidate_models, fit_on

    strategy = config.strategy
    k_fuel = config.k_fuel if k_fuel is None else float(k_fuel)
    min_laps = strategy.min_laps_at_max_age if min_laps_at_max_age is None else min_laps_at_max_age
    if k_fuel != config.k_fuel:
        all_laps, clean = refuel(all_laps, k_fuel), refuel(clean, k_fuel)

    fitted, offsets, limits, info = {}, [], {}, []
    for compound in strategy.compounds:
        laps = clean[clean["PirelliCompound"] == compound]
        specs = {spec.name: spec for spec in candidate_models(compound, config.models)}
        if model_names[compound] not in specs:
            raise ValueError(f"Unknown model {model_names[compound]!r} for {compound}.")
        fitted[compound] = fit_on(specs[model_names[compound]], laps)
        offsets.append(_offsets_table(fitted[compound], compound))
        limits[compound] = max_stint_from_data(laps["TyreLife"], min_laps)
        params = fitted[compound].params()
        rate = float(params["coefficients"][0]) if params["model"] == "polynomial" else np.nan
        info.append({"compound": compound, "model": model_names[compound], "n_laps": len(laps),
                     "n_stints": laps["StintId"].nunique(), "max_stint_laps": limits[compound],
                     "max_observed_age": float(laps["TyreLife"].max()), "rate_s_per_lap": rate})
    offsets = pd.concat(offsets, ignore_index=True)

    reference = strategy.compounds[0]
    bases, deltas = {reference: fitted[reference].base_time}, {}
    for compound in strategy.compounds[1:]:
        deltas[compound] = compound_pace_delta(offsets, reference, compound)
        bases[compound] = bases[reference] + deltas[compound]["delta"]

    if pit_loss_override is not None:
        pit_loss, pit_info = float(pit_loss_override), {"source": "override"}
    elif config.pit_loss_override is not None:
        pit_loss, pit_info = config.pit_loss_override, {"source": "config override"}
    else:
        estimate = estimate_pit_loss(all_laps, clean)
        pit_loss = estimate.median_s
        pit_info = {"source": "data (median)", "q25": estimate.q25_s, "q75": estimate.q75_s,
                    "n_stops": estimate.n_stops}

    lengths = clean.groupby("RaceId")["TotalLaps"].first().unique()
    if config.total_laps_override is not None:
        total_laps = config.total_laps_override
    elif lengths.size == 1:
        total_laps = int(lengths[0])
    else:
        raise ValueError(f"Races differ in length {lengths}; set race.total_laps_override.")

    models = {c: CompoundModel(c, fitted[c], bases[c], limits[c]) for c in strategy.compounds}
    info = pd.DataFrame(info).assign(base_time_s=[bases[c] for c in strategy.compounds])
    return StrategyInputs(models, total_laps, pit_loss, pit_info, deltas, info, k_fuel)
