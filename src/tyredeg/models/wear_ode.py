"""Wear-ODE tyre-degradation model.

    lap_time = offset_of_its_stint + d(n),   dd/dn = a + b d,   d(0) = 0

``a`` [s/lap] is the initial wear rate and ``b`` [1/lap] how the rate
changes as the tyre degrades: b > 0 accelerates towards a "cliff", b = 0 is
linear wear (d = a n), b < 0 levels off. Exact solution:

    d(n) = (a / b) (exp(b n) - 1)     (b != 0),      d(n) = a n   (b = 0)

How the fit works (DECISIONS.md D41, D42)
-----------------------------------------
1. Linearity in a: the ODE is linear, so d(n) = a * g_b(n) where the "unit
   response" g_b solves dg/dn = 1 + b g, g(0) = 0. g_b is computed ONCE per b
   with my RK4 (default, 1-lap steps), my RK45, or the exact formula.
2. For fixed b the model is linear in (stint offsets, a): a comes from my
   linear least squares on the within-stint transformed data (Frisch-Waugh-
   Lovell, see :mod:`tyredeg.models.common`). This gives the profile
   RSS(b) = min over (offsets, a) of the residual sum of squares.
3. b minimises RSS(b) on the bracket [-0.1, 0.1]: RSS is first evaluated on
   a 21-point grid to find the lowest point, then dRSS/db = 0 is solved
   between its grid neighbours by my root finder (bisection by default), with
   dRSS/db from my central difference. Because that derivative has round-off
   noise of about 1e-8, the root finder uses xtol = 1e-8 and no residual test.
4. Constraint (D43): for n > 0, g_b(n) > 0 for every b, so d >= 0 exactly
   when a >= 0. If least squares gives a < 0 for some b, the constrained
   optimum for that b is a = 0 (a one-variable quadratic), which is used and
   flagged.
"""

from __future__ import annotations

import numpy as np

from tyredeg.models.common import (
    NotFittedError,
    check_compound,
    check_degrees_of_freedom,
    check_non_negative,
    check_tyre_age,
    format_parameter_table,
    prepare_stint_data,
    stint_bootstrap,
)
from tyredeg.numerics.differentiation import central_difference, central_second_difference
from tyredeg.numerics.least_squares import fit_linear_least_squares
from tyredeg.numerics.linear_solvers import SingularMatrixError, lu_factor, lu_solve
from tyredeg.numerics.ode_solvers import rk4, rk45
from tyredeg.numerics.root_finding import NoSignChangeError, bisection, newton, secant

# Defaults; identical to `models.wear_ode` in config.yaml (D46).
DEFAULT_SOLVER = "rk4"
DEFAULT_B_BRACKET = (-0.1, 0.1)
DEFAULT_B_GRID_POINTS = 21
DEFAULT_B_XTOL = 1.0e-8
DEFAULT_B_FTOL = 0.0
DEFAULT_RK4_STEP = 1.0
DEFAULT_RK45_RTOL = 1.0e-10
DEFAULT_RK45_ATOL = 1.0e-12
DEFAULT_NEGATIVE_TOLERANCE_S = 0.01

VALID_SOLVERS = ("rk4", "rk45", "exact")
VALID_ROOT_FINDERS = ("bisection", "secant", "newton")


# ---------------------------------------------------------------------------
# The ODE and its solutions
# ---------------------------------------------------------------------------
def _check_b(b):
    # b must be a finite real number (a boolean would silently count as 0 or 1).
    if isinstance(b, bool) or not np.isfinite(np.asarray(b, dtype=float)).all():
        raise ValueError(f"b must be a finite number, got {b!r}.")
    return float(b)


def exact_unit_response(tyre_age, b):
    """Exact g_b(n) = (exp(b n) - 1) / b, with the limit g_0(n) = n.

    ``numpy.expm1(x)`` computes exp(x) - 1 accurately even for tiny x, where
    the textbook form loses digits to cancellation (exp(1e-12) - 1 keeps only
    ~4 correct digits). So the b -> 0 limit needs no special series: only
    b == 0 itself is handled separately, to avoid 0 / 0.

    Parameters
    ----------
    tyre_age : float or array_like
        Tyre age(s) n [laps], >= 0.
    b : float
        Wear-acceleration parameter [1/lap], finite.

    Returns
    -------
    numpy.ndarray
        g_b(n) [laps].

    Raises
    ------
    ValueError
        For negative/NaN ages or a non-finite b.

    Example
    -------
    >>> exact_unit_response([10.0], 0.0).tolist(), exact_unit_response([10.0], 1e-12).round(9).tolist()
    ([10.0], [10.0])
    """
    # Validate the ages and b.
    age = check_tyre_age(tyre_age)
    b = _check_b(b)
    # As b -> 0 the solution tends to g = n, so return that exactly (avoids dividing by zero).
    if b == 0.0:
        return age.copy()
    # g(n) = (e^(b n) - 1) / b; expm1 keeps full accuracy when b*n is tiny.
    return np.expm1(b * age) / b


def exact_degradation(tyre_age, a, b):
    """Exact d(n) = a * g_b(n) [s] for the wear ODE.

    Parameters
    ----------
    tyre_age : float or array_like
        Tyre age(s) [laps], >= 0.
    a : float
        Initial wear rate [s/lap].
    b : float
        Wear-acceleration parameter [1/lap].

    Returns
    -------
    numpy.ndarray

    Raises
    ------
    ValueError
        For invalid inputs.

    Example
    -------
    >>> exact_degradation([40.0], 0.05, 0.0).tolist()
    [2.0]
    """
    # d = a * g: the scale a must be a finite number.
    a = float(a)
    if not np.isfinite(a):
        raise ValueError(f"a must be finite, got {a!r}.")
    return a * exact_unit_response(tyre_age, b)


def unit_response(tyre_age, b, solver=DEFAULT_SOLVER, rk4_step=DEFAULT_RK4_STEP,
                  rk45_rtol=DEFAULT_RK45_RTOL, rk45_atol=DEFAULT_RK45_ATOL):
    """g_b(n) at the given tyre ages, from dg/dn = 1 + b g, g(0) = 0.

    Parameters
    ----------
    tyre_age : float or array_like
        Tyre ages [laps], >= 0. For "rk4" every age must be a multiple of
        ``rk4_step`` (whole laps with the default step of 1 lap).
    b : float
        Wear-acceleration parameter [1/lap].
    solver : str, optional
        "rk4" (default), "rk45" or "exact".
    rk4_step : float, optional
        RK4 step [laps], > 0. Default 1.0 (D42).
    rk45_rtol, rk45_atol : float, optional
        RK45 tolerances. Defaults 1e-10 / 1e-12 (tight, so RSS(b) is smooth
        enough for the central-difference derivative, D42).

    Returns
    -------
    numpy.ndarray
        g_b at each input age (same order).

    Raises
    ------
    ValueError
        For invalid ages/b/solver, or ages that are not on the RK4 grid.

    Example
    -------
    >>> unit_response([0.0, 1.0, 2.0], 0.0).round(12).tolist()
    [0.0, 1.0, 2.0]
    """
    # Validate the inputs; the exact solution needs no integration.
    age = check_tyre_age(tyre_age)
    b = _check_b(b)
    if solver not in VALID_SOLVERS:
        raise ValueError(f"solver must be one of {VALID_SOLVERS}, got {solver!r}.")
    if solver == "exact":
        return exact_unit_response(age, b)

    # Right-hand side of the unit ODE dg/dn = 1 + b g, with g(0) = 0.
    def rhs(n, g):
        return 1.0 + b * g

    # Integrate once up to the oldest age and read g at every distinct age.
    unique_ages = np.unique(age)
    values = np.zeros(unique_ages.size)
    max_age = unique_ages[-1]
    # Only new tyres requested: g(0) = 0 everywhere.
    if max_age == 0.0:
        return np.zeros_like(age)

    # RK4 with a fixed step: every requested age must fall on the step grid.
    if solver == "rk4":
        if not rk4_step > 0:
            raise ValueError(f"rk4_step must be > 0, got {rk4_step}.")
        positions = unique_ages / rk4_step
        if not np.allclose(positions, np.round(positions), atol=1e-9):
            raise ValueError("With solver 'rk4' every tyre age must be a multiple of rk4_step.")
        if max_age < rk4_step:
            raise ValueError("The largest tyre age is smaller than rk4_step.")
        # Integrate from 0 to the oldest age, then look up g at each grid point.
        times, g, _ = rk4(rhs, (0.0, max_age), 0.0, rk4_step)
        grid_index = np.round(times / rk4_step).astype(int)
        lookup = dict(zip(grid_index, g))
        values = np.array([lookup[int(round(p))] for p in positions])
    else:
        # My RK45 returns only its own accepted points, so integrate from one
        # required age to the next and keep the end value of each segment.
        # RK45: integrate piecewise from one requested age to the next, carrying g forward.
        current_age, current_g = 0.0, 0.0
        for i, target in enumerate(unique_ages):
            if target > current_age:
                _, g, _, _ = rk45(rhs, (current_age, target), current_g,
                                  rtol=rk45_rtol, atol=rk45_atol)
                current_age, current_g = target, float(g[-1])
            values[i] = current_g
    # Map the values for the distinct ages back to the original order (with repeats).
    return values[np.searchsorted(unique_ages, age)]


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------
class WearODEModel:
    """Wear-ODE degradation model d(n) = a g_b(n) with per-stint offsets.

    Parameters
    ----------
    compound : str
        Pirelli compound code, e.g. "C3".
    solver : str, optional
        ODE solver for g_b: "rk4" (default), "rk45" or "exact".
    b_bracket : tuple of float, optional
        Search interval for b [1/lap], low < high. Default (-0.1, 0.1).
    b_grid_points : int, optional
        Grid points for the initial RSS scan, >= 3. Default 21.
    b_xtol, b_ftol : float, optional
        Root-finding tolerances for dRSS/db = 0. Defaults 1e-8 and 0 (D41).
    root_finder : str, optional
        "bisection" (default), "secant" or "newton".
    rk4_step, rk45_rtol, rk45_atol : float, optional
        Solver settings (see :func:`unit_response`).
    negative_tolerance_s : float, optional
        Degradation below -tolerance [s] is flagged. Default 0.01.

    Raises
    ------
    TypeError, ValueError
        For invalid settings or an unknown compound.

    Example
    -------
    >>> ages = np.tile(np.arange(1.0, 31.0), 2)
    >>> times = 80.0 + exact_degradation(ages, 0.05, 0.03)
    >>> model = WearODEModel("C3").fit(ages, times, stint_id=[0] * 30 + [1] * 30)
    >>> p = model.params()
    >>> round(p["a"], 4), round(p["b"], 4)
    (0.05, 0.03)
    """

    def __init__(self, compound, solver=DEFAULT_SOLVER, b_bracket=DEFAULT_B_BRACKET,
                 b_grid_points=DEFAULT_B_GRID_POINTS, b_xtol=DEFAULT_B_XTOL,
                 b_ftol=DEFAULT_B_FTOL, root_finder="bisection", rk4_step=DEFAULT_RK4_STEP,
                 rk45_rtol=DEFAULT_RK45_RTOL, rk45_atol=DEFAULT_RK45_ATOL,
                 negative_tolerance_s=DEFAULT_NEGATIVE_TOLERANCE_S):
        # Validate the settings: compound, solver, root finder, b bracket, grid size and tolerance.
        self.compound = check_compound(compound)
        if solver not in VALID_SOLVERS:
            raise ValueError(f"solver must be one of {VALID_SOLVERS}, got {solver!r}.")
        if root_finder not in VALID_ROOT_FINDERS:
            raise ValueError(f"root_finder must be one of {VALID_ROOT_FINDERS}, got {root_finder!r}.")
        low, high = (float(value) for value in b_bracket)
        if not (np.isfinite(low) and np.isfinite(high) and low < high):
            raise ValueError(f"b_bracket must be finite with low < high, got {b_bracket!r}.")
        if isinstance(b_grid_points, bool) or not isinstance(b_grid_points, (int, np.integer)) \
                or b_grid_points < 3:
            raise ValueError(f"b_grid_points must be an integer >= 3, got {b_grid_points!r}.")
        if not negative_tolerance_s >= 0:
            raise ValueError("negative_tolerance_s must be >= 0.")
        # Store the settings; the model is not usable until fit() is called.
        self.solver = solver
        self.b_bracket = (low, high)
        self.b_grid_points = int(b_grid_points)
        self.b_xtol = b_xtol
        self.b_ftol = b_ftol
        self.root_finder = root_finder
        self.rk4_step = rk4_step
        self.rk45_rtol = rk45_rtol
        self.rk45_atol = rk45_atol
        self.negative_tolerance_s = float(negative_tolerance_s)
        self._fitted = False
        self.bootstrap_result = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------
    def _unit_response(self, tyre_age, b):
        # g(age) for the chosen solver and its settings.
        return unit_response(tyre_age, b, self.solver, self.rk4_step, self.rk45_rtol,
                             self.rk45_atol)

    def _profile(self, data, within_y, b):
        """Best a for fixed b and the resulting RSS: returns (rss, a, a_was_clamped)."""
        # For a fixed b the model is linear in a: demean g within stints, then fit a by least
        # squares.
        within_g = data.demean(self._unit_response(data.tyre_age, b))
        if not np.any(within_g != 0):
            raise ValueError("Tyre age does not vary within any stint; a and b cannot be fitted.")
        result = fit_linear_least_squares(within_g.reshape(-1, 1), within_y)
        a = float(result.coefficients[0])
        # A negative a would mean tyres get faster with age; clamp to 0 and flag it.
        if a < 0:
            # Constrained optimum for this b is a = 0: the model then predicts
            # only the stint means, so the residuals are within_y itself.
            return float(within_y @ within_y), 0.0, True
        return result.residual_sum_of_squares, a, False

    def _search_b(self, data, within_y):
        """Grid scan + root finding on dRSS/db; returns (b, info dict)."""
        # Residual sum of squares as a function of b (with the best a for that b).
        def rss_of(b):
            return self._profile(data, within_y, b)[0]

        # Coarse grid scan of RSS(b) over the bracket to find the region of the minimum.
        grid = np.linspace(self.b_bracket[0], self.b_bracket[1], self.b_grid_points)
        grid_rss = np.array([rss_of(b) for b in grid])
        best = int(np.argmin(grid_rss))
        info = {"grid": grid, "grid_rss": grid_rss, "boundary": False, "iterations": 0,
                "history": np.array([grid[best]]), "root_finder": self.root_finder}
        # Minimum on the bracket edge: no interior optimum, so report it and stop.
        if best in (0, grid.size - 1):
            # The lowest RSS is at an end of the bracket: no interior minimum.
            info["boundary"] = True
            return float(grid[best]), info

        # The minimum of RSS is where dRSS/db = 0; the derivative comes from a central difference.
        def derivative(b):
            return central_difference(rss_of, b)

        # Refine between the grid neighbours of the best point with the chosen root finder.
        left, right = float(grid[best - 1]), float(grid[best + 1])
        try:
            if self.root_finder == "bisection":
                root = bisection(derivative, left, right, xtol=self.b_xtol, ftol=self.b_ftol)
            elif self.root_finder == "secant":
                root = secant(derivative, left, right, xtol=self.b_xtol, ftol=self.b_ftol)
            else:
                root = newton(derivative, lambda b: central_second_difference(rss_of, b),
                              float(grid[best]), xtol=self.b_xtol, ftol=self.b_ftol)
        # No sign change between the neighbours: keep the grid minimum and record why.
        except NoSignChangeError:
            # RSS is flat between the neighbours (no measurable slope): the
            # grid point is the best available estimate.
            info["no_sign_change"] = True
            return float(grid[best]), info
        # Record the iterations and history for reporting and plots.
        info["iterations"] = root.iterations
        info["history"] = root.history
        # A root outside the bracket would be an extrapolation, so refuse it.
        if not self.b_bracket[0] <= root.root <= self.b_bracket[1]:
            raise ValueError(f"The {self.root_finder} search left the b bracket (b = {root.root}).")
        return float(root.root), info

    def fit(self, tyre_age, lap_time, stint_id=None):
        """Fit a, b and the stint offsets (see the module docstring).

        Parameters
        ----------
        tyre_age : array_like
            Tyre age [laps] of each lap, >= 0 (whole laps for solver "rk4").
        lap_time : array_like
            Fuel-corrected lap time [s] of each lap, > 0.
        stint_id : array_like or None, optional
            Stint identifier per lap; None = one stint.

        Returns
        -------
        WearODEModel
            ``self``, fitted.

        Raises
        ------
        ValueError
            For invalid inputs, too few laps, no tyre-age variation within
            stints, or a search that leaves the bracket.

        Example
        -------
        >>> WearODEModel("C3").fit([1, 2, 3, 4], [80.0, 80.1, 80.2, 80.3]).params()["n_laps"]
        4
        """
        # Validate the data and require at least one residual degree of freedom for a and b.
        data = prepare_stint_data(tyre_age, lap_time, stint_id)
        dof = check_degrees_of_freedom(data, 2)
        # Lap times with each stint's mean removed (the offsets drop out).
        within_y = data.demean(data.lap_time)

        # Find b by the search, then the matching a and the unit response g.
        b, search = self._search_b(data, within_y)
        rss, a, clamped = self._profile(data, within_y, b)
        g = self._unit_response(data.tyre_age, b)

        # Keep the fitted values and the search details for reporting.
        self._data = data
        self._dof = dof
        self._a, self._b = a, b
        self._rss = rss
        self._a_clamped = clamped
        self._search = search
        # Each stint's offset is its mean lap time after removing the fitted degradation a*g.
        self._offsets = data.stint_means(data.lap_time - a * g)
        self._standard_errors = self._analytic_standard_errors(data, within_y, a, b, rss, dof)
        # Verify the numerical solution against the exact one at the fitted b.
        # Check the numerical solver against the exact solution at every training age.
        self._ode_check = float(np.max(np.abs(a * (g - exact_unit_response(data.tyre_age, b)))))
        self._fitted = True
        self.bootstrap_result = None
        # Check that the fitted curve does not predict clearly negative degradation.
        self._constraint = check_non_negative(self.degradation, float(data.tyre_age.max()),
                                              self.negative_tolerance_s,
                                              ages=np.arange(0.0, data.tyre_age.max() + 1.0))
        return self

    def _analytic_standard_errors(self, data, within_y, a, b, rss, dof):
        """Gauss-Newton standard errors of (a, b): sqrt(diag(sigma^2 (J^T J)^-1)).

        J holds the derivatives of the within-transformed model a g_b(n) with
        respect to a (that is g_b) and b (a dg_b/db, by central difference).
        Undefined (NaN) when a was clamped to 0, because b then has no effect.
        """
        # With a = 0 the curve is flat and b is not identifiable, so no SE can be computed.
        if a == 0.0:
            return np.array([np.nan, np.nan])

        # Jacobian of the residuals with respect to (a, b); the b-column uses a central difference.
        def within_unit_response(bb):
            return data.demean(self._unit_response(data.tyre_age, float(bb)))

        jacobian = np.column_stack([within_unit_response(b),
                                    a * central_difference(within_unit_response, b)])
        # Linearised covariance sigma^2 (J^T J)^-1; a singular J^T J means SEs are undefined.
        try:
            lu, permutation = lu_factor(jacobian.T @ jacobian)
        except SingularMatrixError:
            return np.array([np.nan, np.nan])
        covariance = rss / dof * lu_solve(lu, permutation, np.eye(2))
        return np.sqrt(np.diag(covariance))

    def _require_fitted(self):
        # Shared guard: every method that needs the fitted parameters calls this first.
        if not self._fitted:
            raise NotFittedError("Call fit() before using the model.")

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def degradation(self, tyre_age):
        """Degradation d(n) = a g_b(n) [s], using the model's ODE solver.

        Parameters
        ----------
        tyre_age : float or array_like
            Tyre age(s) [laps], >= 0 (multiples of ``rk4_step`` for "rk4").

        Returns
        -------
        numpy.ndarray

        Raises
        ------
        NotFittedError
            Before ``fit``.
        ValueError
            For an invalid input (see Parameters).

        Example
        -------
        >>> model.degradation([0.0, 20.0])  # doctest: +SKIP
        """
        # d(age) = a * g(age; b).
        self._require_fitted()
        return self._a * self._unit_response(tyre_age, self._b)

    def predict(self, tyre_age, base_time=None):
        """Predicted lap time [s] = base_time + d(tyre_age).

        Parameters
        ----------
        tyre_age : float or array_like
            Tyre age(s) [laps], >= 0.
        base_time : float or None, optional
            Lap time of a new tyre [s]; default the median stint offset.

        Returns
        -------
        numpy.ndarray

        Raises
        ------
        NotFittedError
            Before ``fit``.
        ValueError
            For an invalid input (see Parameters).

        Example
        -------
        >>> model.predict([10.0], base_time=85.0)  # doctest: +SKIP
        """
        # Lap time = base pace (default: median stint offset) + degradation at that tyre age.
        self._require_fitted()
        base = self.base_time if base_time is None else float(base_time)
        if not np.isfinite(base) or base <= 0:
            raise ValueError(f"base_time must be a positive number of seconds, got {base_time!r}.")
        return base + self.degradation(tyre_age)

    @property
    def base_time(self):
        """float: median stint offset [s]."""
        # Base pace of a "typical" car: the median of all stint offsets.
        self._require_fitted()
        return float(np.median(self._offsets))

    def stint_offsets(self):
        """Fitted base lap time of every training stint [s] (new tyre, fuel-corrected).

        Returns
        -------
        dict
            Stint identifier -> offset [s].

        Raises
        ------
        NotFittedError
            Before ``fit``.

        Example
        -------
        >>> model.stint_offsets()["2023_hungarian_grand_prix|VER|2"]  # doctest: +SKIP
        84.1
        """
        # Pair each stint label with its fitted offset.
        self._require_fitted()
        return {label: float(value) for label, value in zip(self._data.stint_labels, self._offsets)}

    # ------------------------------------------------------------------
    # Uncertainty and reporting
    # ------------------------------------------------------------------
    PARAMETER_NAMES = ("a [s/lap]", "b [1/lap]")

    def bootstrap(self, n_resamples, confidence_level=0.95, seed=42):
        """Stint-bootstrap uncertainty of (a, b) (D45); stored for summary().

        Parameters
        ----------
        n_resamples : int
            Number of resamples >= 2 (config: 200).
        confidence_level : float, optional
            In (0, 1). Default 0.95.
        seed : int, optional
            Random seed (rule 11). Default 42.

        Returns
        -------
        BootstrapResult

        Raises
        ------
        NotFittedError
            Before ``fit``.
        ValueError
            For an invalid input (see Parameters).

        Example
        -------
        >>> model.bootstrap(200, seed=42)  # doctest: +SKIP
        """
        # Bootstrap only makes sense on a fitted model (it reuses the training data).
        self._require_fitted()

        # Refit a fresh model with the same settings on each resample and return (a, b).
        def refit(ages, times, ids):
            clone = WearODEModel(self.compound, self.solver, self.b_bracket, self.b_grid_points,
                                 self.b_xtol, self.b_ftol, self.root_finder, self.rk4_step,
                                 self.rk45_rtol, self.rk45_atol, self.negative_tolerance_s)
            clone.fit(ages, times, ids)
            return np.array([clone._a, clone._b])

        # Resample whole stints and keep the result for summary().
        self.bootstrap_result = stint_bootstrap(self._data, refit, self.PARAMETER_NAMES,
                                                n_resamples, confidence_level, seed)
        return self.bootstrap_result

    def params(self):
        """Fitted parameters and diagnostics as a dictionary.

        Returns
        -------
        dict
            Keys: compound, model, solver, a, b, standard_errors (analytic,
            for a and b), bootstrap_standard_errors, base_time, n_laps,
            n_stints, rss, residual_std, b_at_bracket_boundary,
            a_clamped_to_zero, search_iterations, root_finder,
            ode_check_max_error (max |d_numerical - d_exact| [s]),
            min_degradation, negative_degradation_flag.

        Raises
        ------
        NotFittedError
            Before ``fit``.

        Example
        -------
        >>> model.params()["b"]  # doctest: +SKIP
        """
        # Collect the fitted values and diagnostics in one dictionary.
        self._require_fitted()
        return {
            "compound": self.compound,
            "model": "wear_ode",
            "solver": self.solver,
            "a": self._a,
            "b": self._b,
            "standard_errors": self._standard_errors.copy(),
            "bootstrap_standard_errors": (None if self.bootstrap_result is None
                                          else self.bootstrap_result.standard_errors.copy()),
            "base_time": self.base_time,
            "n_laps": self._data.n_laps,
            "n_stints": self._data.n_stints,
            "rss": self._rss,
            "residual_std": float(np.sqrt(self._rss / self._dof)),
            "b_at_bracket_boundary": self._search["boundary"],
            "a_clamped_to_zero": self._a_clamped,
            "search_iterations": self._search["iterations"],
            "root_finder": self.root_finder,
            "ode_check_max_error": self._ode_check,
            "min_degradation": self._constraint.min_degradation_s,
            "negative_degradation_flag": self._constraint.violated or self._a_clamped,
        }

    def summary(self):
        """Human-readable report of the fit (str).

        Returns
        -------
        str
            Lines with the data size, base time, a and b with their standard
            errors, the b search, the ODE check and the non-negative check.

        Raises
        ------
        NotFittedError
            Before ``fit``.

        Example
        -------
        >>> ages = np.tile(np.arange(1.0, 21.0), 3)
        >>> model = WearODEModel("C3").fit(ages, 80.0 + 0.05 * ages + 0.01 * np.cos(ages), [0] * 20 + [1] * 20 + [2] * 20)
        >>> print(model.summary().splitlines()[0])
        Wear-ODE degradation model dd/dn = a + b d, compound C3, solver rk4
        """
        # Build a short text report from params().
        p = self.params()
        lines = [
            f"Wear-ODE degradation model dd/dn = a + b d, compound {p['compound']}, solver {p['solver']}",
            f"  {p['n_laps']} laps in {p['n_stints']} stints; residual std {p['residual_std']:.3f} s; "
            f"base time (median offset) {p['base_time']:.3f} s",
        ]
        lines += format_parameter_table(self.PARAMETER_NAMES, [p["a"], p["b"]],
                                        p["standard_errors"], self.bootstrap_result)
        lines.append(f"  b search: {p['root_finder']}, {p['search_iterations']} iterations"
                     + ("; WARNING: b at the bracket boundary" if p["b_at_bracket_boundary"] else ""))
        lines.append(f"  ODE check: max |d_{p['solver']} - d_exact| = {p['ode_check_max_error']:.2e} s")
        if p["a_clamped_to_zero"]:
            lines.append("  non-negative degradation: VIOLATED by the data; a was clamped to 0")
        else:
            status = "VIOLATED" if p["negative_degradation_flag"] else "ok"
            lines.append(f"  non-negative degradation: {status} (min d = {p['min_degradation']:.4f} s)")
        return "\n".join(lines)
