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
        self.compound = check_compound(compound)
        if isinstance(degree, bool) or not isinstance(degree, (int, np.integer)) or degree < 1:
            raise ValueError(f"degree must be an integer >= 1, got {degree!r}.")
        if not isinstance(scale, bool):
            raise TypeError("scale must be True or False.")
        if method not in VALID_METHODS:
            raise ValueError(f"method must be one of {VALID_METHODS}, got {method!r}.")
        if not negative_tolerance_s >= 0:
            raise ValueError("negative_tolerance_s must be >= 0.")
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
        data = prepare_stint_data(tyre_age, lap_time, stint_id)
        dof = check_degrees_of_freedom(data, self.degree)
        if np.unique(data.tyre_age).size < self.degree + 1:
            raise ValueError(f"A degree-{self.degree} model needs at least "
                             f"{self.degree + 1} distinct tyre ages.")
        low, high = float(data.tyre_age.min()), float(data.tyre_age.max())
        self._centre = (low + high) / 2.0 if self.scale else 0.0
        self._half_range = (high - low) / 2.0 if self.scale else 1.0

        regressors = self._regressors(data.tyre_age)
        within_x = np.column_stack([data.demean(column) for column in regressors.T])
        within_y = data.demean(data.lap_time)
        if self.method == "normal":
            result = fit_linear_least_squares(within_x, within_y)
        else:
            result = fit_linear_least_squares_qr(within_x, within_y)

        self._data = data
        self._dof = dof
        self._scaled_coefficients = result.coefficients
        self._rss = result.residual_sum_of_squares
        self._condition = result.condition_estimate
        self._offsets = data.stint_means(data.lap_time - regressors @ result.coefficients)

        # Covariance of the scaled coefficients: sigma^2 (Zw^T Zw)^-1, with the
        # residual degrees of freedom corrected for the stint offsets.
        sigma_squared = self._rss / dof
        lu, permutation = lu_factor(within_x.T @ within_x)
        scaled_cov = sigma_squared * lu_solve(lu, permutation, np.eye(self.degree))
        # Convert to tyre-age units. Row/column 0 of T is the constant term,
        # which is identically 0 for d, so it is dropped.
        transform = unscaling_matrix(self.degree, self._centre, self._half_range)[1:, 1:]
        self._coefficients = transform @ self._scaled_coefficients
        self._covariance = transform @ scaled_cov @ transform.T
        self._fitted = True
        self.bootstrap_result = None
        self._constraint = check_non_negative(self.degradation, high, self.negative_tolerance_s)
        return self

    def _require_fitted(self):
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

        Raises
        ------
        NotFittedError, ValueError

        Example
        -------
        >>> model = PolynomialDegradationModel("C3").fit([1, 2, 3], [80.0, 80.1, 80.2])
        >>> model.predict([4.0], base_time=90.0).round(6).tolist()
        [90.4]
        """
        self._require_fitted()
        base = self.base_time if base_time is None else float(base_time)
        if not np.isfinite(base) or base <= 0:
            raise ValueError(f"base_time must be a positive number of seconds, got {base_time!r}.")
        return base + self.degradation(tyre_age)

    @property
    def base_time(self):
        """float: median stint offset [s] (lap time of a new tyre for a typical car)."""
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
        self._require_fitted()
        return {label: float(value) for label, value in zip(self._data.stint_labels, self._offsets)}

    # ------------------------------------------------------------------
    # Uncertainty and reporting
    # ------------------------------------------------------------------
    def parameter_names(self):
        """Names of the degradation coefficients, e.g. ('c1 [s/lap]', 'c2 [s/lap^2]')."""
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
        NotFittedError, ValueError

        Example
        -------
        >>> result = model.bootstrap(200, seed=42)  # doctest: +SKIP
        """
        self._require_fitted()

        def refit(ages, times, ids):
            clone = PolynomialDegradationModel(self.compound, self.degree, self.scale,
                                               self.method, self.negative_tolerance_s)
            return clone.fit(ages, times, ids)._coefficients

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

        Example
        -------
        >>> PolynomialDegradationModel("C3").fit([1, 2, 3], [80.0, 80.1, 80.2]).params()["degree"]
        1
        """
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

        Example
        -------
        >>> print(model.summary())  # doctest: +SKIP
        """
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
