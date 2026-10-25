"""Polynomial tyre-degradation model.

    lap_time = offset_of_its_stint + d(tyre_age),
    d(n) = c_1 n + c_2 n^2 + ... + c_p n^p          (so d(0) = 0)

The degradation coefficients are shared by all stints of one compound; each
stint has its own offset (base pace, DECISIONS.md D39). The fit uses my
least-squares module (normal equations + my Gaussian elimination, or QR) on
the within-stint transformed data (Frisch-Waugh-Lovell, see
:mod:`tyredeg.models.common`). Inputs are scaled to [-1, 1] before building
the powers (D35) and the coefficients are converted back to tyre-age units.

Candidate degrees are 1, 2, 3; Phase 5 cross-validation picks one (D40).
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
from tyredeg.numerics.least_squares import (
    VALID_METHODS,
    fit_linear_least_squares,
    fit_linear_least_squares_qr,
    polynomial_design_matrix,
    unscaling_matrix,
)
from tyredeg.numerics.linear_solvers import lu_factor, lu_solve

# Defaults; identical to the `models` section of config.yaml (D46).
DEFAULT_DEGREE = 1
DEFAULT_NEGATIVE_TOLERANCE_S = 0.01


class PolynomialDegradationModel:
    """Polynomial degradation d(n) = sum_{k=1..p} c_k n^k with per-stint offsets.

    Parameters
    ----------
    compound : str
        Pirelli compound code, e.g. "C3".
    degree : int, optional
        Polynomial degree p >= 1. Default 1 (linear wear).
    scale : bool, optional
        Scale tyre age to [-1, 1] before forming powers (D35). Default True.
    method : str, optional
        "normal" (normal equations + my Gaussian elimination, default) or "qr".
    negative_tolerance_s : float, optional
        Degradation below -tolerance [s] is flagged (D43). Default 0.01.

    Raises
    ------
    TypeError, ValueError
        For an unknown compound, degree < 1, unknown method or negative tolerance.

    Example
    -------
    >>> model = PolynomialDegradationModel("C3", degree=1)
    >>> model = model.fit([1, 2, 3, 1, 2, 3], [80.1, 80.2, 80.3, 81.1, 81.2, 81.3],
    ...                   stint_id=["a", "a", "a", "b", "b", "b"])
    >>> round(float(model.params()["coefficients"][0]), 6)   # c_1 [s/lap]
    0.1
    """

    def __init__(self, compound, degree=DEFAULT_DEGREE, scale=True, method="normal",
                 negative_tolerance_s=DEFAULT_NEGATIVE_TOLERANCE_S):
        # Validate the settings: Pirelli compound, degree >= 1, scale flag, solver and tolerance.
        self.compound = check_compound(compound)
        if isinstance(degree, bool) or not isinstance(degree, (int, np.integer)) or degree < 1:
            raise ValueError(f"degree must be an integer >= 1, got {degree!r}.")
        if not isinstance(scale, bool):
            raise TypeError("scale must be True or False.")
        if method not in VALID_METHODS:
            raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}.")
        if not negative_tolerance_s >= 0:
            raise ValueError("negative_tolerance_s must be >= 0.")
        # Store the settings; the model is not usable until fit() is called.
        self.degree = int(degree)
        self.scale = scale
        self.method = method
        self.negative_tolerance_s = float(negative_tolerance_s)
        self._fitted = False
        self.bootstrap_result = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------
    def _regressors(self, tyre_age):
        """Columns s^k - s0^k (k = 1..p), where s0 is the scaled age 0, so d(0) = 0."""
        # Polynomial columns of the scaled tyre age, and the same columns at age 0.
        powers = polynomial_design_matrix(tyre_age, self.degree, self._centre, self._half_range)
        at_zero = polynomial_design_matrix(np.zeros(1), self.degree, self._centre, self._half_range)
        # Column 0 (the constant) is dropped: the stint offsets play that role.
        return powers[:, 1:] - at_zero[:, 1:]

    def fit(self, tyre_age, lap_time, stint_id=None):
        """Fit the degradation coefficients and the stint offsets.

        Parameters
        ----------
        tyre_age : array_like
            Tyre age [laps] of each lap, >= 0.
        lap_time : array_like
            Fuel-corrected lap time [s] of each lap, > 0.
        stint_id : array_like or None, optional
            Stint identifier per lap; None = one stint.

        Returns
        -------
        PolynomialDegradationModel
            ``self``, fitted.

        Raises
        ------
        ValueError
            For invalid inputs, too few laps (no residual degrees of freedom)
            or fewer than ``degree + 1`` distinct tyre ages.
        SingularMatrixError
            If the regressors are linearly dependent after removing the
            stint means (e.g. every stint has a single tyre age).

        Example
        -------
        >>> PolynomialDegradationModel("C3").fit([1, 2, 3], [80.0, 80.1, 80.2]).params()["n_laps"]
        3
        """
        # Validate the data and make sure there are enough laps and distinct ages for the degree.
        data = prepare_stint_data(tyre_age, lap_time, stint_id)
        dof = check_degrees_of_freedom(data, self.degree)
        if np.unique(data.tyre_age).size < self.degree + 1:
            raise ValueError(f"A degree-{self.degree} model needs at least "
                             f"{self.degree + 1} distinct tyre ages.")
        # Scale tyre age to [-1, 1] over the training range to keep the least squares well
        # conditioned.
        low, high = float(data.tyre_age.min()), float(data.tyre_age.max())
        self._centre = (low + high) / 2.0 if self.scale else 0.0
        self._half_range = (high - low) / 2.0 if self.scale else 1.0

        # Regressors d(age) with d(0) = 0, one column per polynomial power.
        regressors = self._regressors(data.tyre_age)
        # Remove each stint's mean from x and y so the stint offsets drop out (Frisch-Waugh-
        # Lovell).
        within_x = np.column_stack([data.demean(column) for column in regressors.T])
        within_y = data.demean(data.lap_time)
        # Least squares on the demeaned data gives the degradation coefficients.
        if self.method == "normal":
            result = fit_linear_least_squares(within_x, within_y)
        else:
            result = fit_linear_least_squares_qr(within_x, within_y)

        # Keep what is needed later for prediction, offsets and reporting.
        self._data = data
        self._dof = dof
        self._scaled_coefficients = result.coefficients
        self._rss = result.residual_sum_of_squares
        self._condition = result.condition_estimate
        # Each stint's offset is its mean lap time after removing the fitted degradation.
        self._offsets = data.stint_means(data.lap_time - regressors @ result.coefficients)

        # Covariance of the scaled coefficients: sigma^2 (Zw^T Zw)^-1, with the
        # residual degrees of freedom corrected for the stint offsets.
        # Covariance of the coefficients: sigma^2 (X^T X)^-1 on the demeaned regressors.
        sigma_squared = self._rss / dof
        lu, permutation = lu_factor(within_x.T @ within_x)
        scaled_cov = sigma_squared * lu_solve(lu, permutation, np.eye(self.degree))
        # Convert to tyre-age units. Row/column 0 of T is the constant term,
        # which is identically 0 for d, so it is dropped.
        # Convert coefficients and covariance from the scaled age back to ordinary tyre age.
        transform = unscaling_matrix(self.degree, self._centre, self._half_range)[1:, 1:]
        self._coefficients = transform @ self._scaled_coefficients
        self._covariance = transform @ scaled_cov @ transform.T
        self._fitted = True
        self.bootstrap_result = None
        # Check that the fitted curve does not predict clearly negative degradation (tyres getting
        # faster).
        self._constraint = check_non_negative(self.degradation, high, self.negative_tolerance_s)
        return self

    def _require_fitted(self):
        # Shared guard: every method that needs the fitted parameters calls this first.
        if not self._fitted:
            raise NotFittedError("Call fit() before using the model.")

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def degradation(self, tyre_age):
        """Degradation d(n) [s] relative to a new tyre (d(0) = 0).

        Parameters
        ----------
        tyre_age : float or array_like
            Tyre age(s) [laps], >= 0.

        Returns
        -------
        numpy.ndarray

        Raises
        ------
        NotFittedError
            Before ``fit``.
        ValueError
            For invalid ages.

        Example
        -------
        >>> model = PolynomialDegradationModel("C3").fit([1, 2, 3], [80.0, 80.1, 80.2])
        >>> model.degradation([0.0, 10.0]).round(6).tolist()
        [0.0, 1.0]
        """
        # Evaluate d at the requested ages with the scaled-coefficient form used in the fit.
        self._require_fitted()
        age = check_tyre_age(tyre_age)
        return self._regressors(age) @ self._scaled_coefficients

    def predict(self, tyre_age, base_time=None):
        """Predicted lap time [s] = base_time + d(tyre_age).

        Parameters
        ----------
        tyre_age : float or array_like
            Tyre age(s) [laps], >= 0.
        base_time : float or None, optional
            Lap time of a new tyre [s]. Default: the median stint offset of
            the training data (a "typical" car).

        Returns
        -------
        numpy.ndarray
            Predicted fuel-corrected lap times [s], one per age.

        Raises
        ------
        NotFittedError
            Before ``fit``.
        ValueError
            For invalid ages or a non-positive ``base_time``.

        Example
        -------
        >>> model = PolynomialDegradationModel("C3").fit([1, 2, 3], [80.0, 80.1, 80.2])
        >>> model.predict([4.0], base_time=90.0).round(6).tolist()
        [90.4]
        """
        # Lap time = base pace (default: median stint offset) + degradation at that tyre age.
        self._require_fitted()
        base = self.base_time if base_time is None else float(base_time)
        if not np.isfinite(base) or base <= 0:
            raise ValueError(f"base_time must be a positive number of seconds, got {base_time!r}.")
        return base + self.degradation(tyre_age)

    @property
    def base_time(self):
        """float: median stint offset [s] (lap time of a new tyre for a typical car)."""
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
    def parameter_names(self):
        """Names of the degradation coefficients, e.g. ('c1 [s/lap]', 'c2 [s/lap^2]').

        Returns
        -------
        tuple of str
            One name (with unit) per coefficient c1 .. c_degree.

        Raises
        ------
        Nothing: the names depend only on the degree set in the constructor.

        Example
        -------
        >>> PolynomialDegradationModel("C3", degree=2).parameter_names()
        ('c1 [s/lap]', 'c2 [s/lap^2]')
        """
        # One name per coefficient, with units: c1 [s/lap], c2 [s/lap^2], ...
        names = ["c1 [s/lap]"]
        for k in range(2, self.degree + 1):
            names.append(f"c{k} [s/lap^{k}]")
        return tuple(names)

    def bootstrap(self, n_resamples, confidence_level=0.95, seed=42):
        """Stint-bootstrap uncertainty of the coefficients (D45); stored for summary().

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
        >>> result = model.bootstrap(200, seed=42)  # doctest: +SKIP
        """
        # Bootstrap only makes sense on a fitted model (it reuses the training data).
        self._require_fitted()

        # Refit a fresh model with the same settings on each resampled data set.
        def refit(ages, times, ids):
            clone = PolynomialDegradationModel(self.compound, self.degree, self.scale,
                                               self.method, self.negative_tolerance_s)
            return clone.fit(ages, times, ids)._coefficients

        # Resample whole stints and keep the result for summary().
        self.bootstrap_result = stint_bootstrap(self._data, refit, self.parameter_names(),
                                                n_resamples, confidence_level, seed)
        return self.bootstrap_result

    def params(self):
        """Fitted parameters and diagnostics as a dictionary.

        Returns
        -------
        dict
            Keys: compound, model, degree, coefficients (c_1..c_p in tyre-age
            units), standard_errors (analytic), bootstrap_standard_errors
            (None until :meth:`bootstrap`), base_time, n_laps, n_stints, rss,
            residual_std, condition_estimate, min_degradation,
            negative_degradation_flag.

        Raises
        ------
        NotFittedError
            Before ``fit``.

        Example
        -------
        >>> PolynomialDegradationModel("C3").fit([1, 2, 3], [80.0, 80.1, 80.2]).params()["degree"]
        1
        """
        # Collect the fitted values and diagnostics in one dictionary.
        self._require_fitted()
        return {
            "compound": self.compound,
            "model": "polynomial",
            "degree": self.degree,
            "coefficients": self._coefficients.copy(),
            "standard_errors": np.sqrt(np.diag(self._covariance)),
            "bootstrap_standard_errors": (None if self.bootstrap_result is None
                                          else self.bootstrap_result.standard_errors.copy()),
            "base_time": self.base_time,
            "n_laps": self._data.n_laps,
            "n_stints": self._data.n_stints,
            "rss": self._rss,
            "residual_std": float(np.sqrt(self._rss / self._dof)),
            "condition_estimate": self._condition,
            "min_degradation": self._constraint.min_degradation_s,
            "negative_degradation_flag": self._constraint.violated,
        }

    def summary(self):
        """Human-readable report of the fit (str).

        Returns
        -------
        str
            Lines with the data size, residual standard deviation, base time, each
            coefficient with its standard errors, and the non-negative check.

        Raises
        ------
        NotFittedError
            Before ``fit``.

        Example
        -------
        >>> ages = np.tile(np.arange(1.0, 11.0), 2)
        >>> model = PolynomialDegradationModel("C3").fit(ages, 80.0 + 0.06 * ages + 0.01 * np.cos(ages), [0] * 10 + [1] * 10)
        >>> print(model.summary().splitlines()[0])
        Polynomial degradation model, compound C3, degree 1
        """
        # Build a short text report from params().
        p = self.params()
        lines = [
            f"Polynomial degradation model, compound {p['compound']}, degree {p['degree']}",
            f"  {p['n_laps']} laps in {p['n_stints']} stints; residual std {p['residual_std']:.3f} s; "
            f"base time (median offset) {p['base_time']:.3f} s",
        ]
        lines += format_parameter_table(self.parameter_names(), p["coefficients"],
                                        p["standard_errors"], self.bootstrap_result)
        status = "VIOLATED" if p["negative_degradation_flag"] else "ok"
        lines.append(f"  non-negative degradation: {status} (min d = {p['min_degradation']:.4f} s)")
        return "\n".join(lines)
