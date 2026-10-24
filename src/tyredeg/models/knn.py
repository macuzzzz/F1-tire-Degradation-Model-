"""K-nearest-neighbours regression from scratch, and the KNN degradation model.

KNN regression predicts at a query point by averaging the targets of the k
training points closest to it. Nothing is "fitted": the training data is
stored and every prediction computes all distances (brute force), which costs
O(n_train x n_features) per query.

Design choices (DECISIONS.md D44)
---------------------------------
- Distance: Euclidean. With the single feature used here (tyre age), feature
  scaling cannot change which neighbours are nearest, so none is applied.
- Ties: tyre ages are whole laps, so many training points are exactly as far
  from a query as the k-th nearest one. ALL points tied with the k-th
  distance are included. The result is then independent of row order (a
  "take the first k" rule would depend on how the data happens to be sorted).
- Weights: "uniform" (plain average) or "distance" (weights 1/distance).
  With "distance", training points at distance 0 receive all the weight
  (equally), the same rule as scikit-learn.

The degradation model (KNNDegradationModel) removes each stint's base pace
first, using the offsets of the linear per-stint model (D44), and then lets
KNN learn the shape of d(tyre_age) without assuming any formula. It cannot
extrapolate: beyond the oldest training tyre age it returns the average of
the oldest ages.
"""

from __future__ import annotations

import numpy as np

from tyredeg.models.common import (
    NotFittedError,
    check_compound,
    check_degrees_of_freedom,
    check_non_negative,
    check_tyre_age,
    prepare_stint_data,
)
from tyredeg.models.polynomial import PolynomialDegradationModel

VALID_WEIGHTS = ("uniform", "distance")

# Defaults; identical to `models.knn` in config.yaml (D46).
DEFAULT_K = 50
DEFAULT_WEIGHTS = "uniform"
DEFAULT_NEGATIVE_TOLERANCE_S = 0.01

# Queries are processed in blocks so the distance matrix stays small in memory.
QUERY_BLOCK_SIZE = 512


def _as_feature_matrix(X, name):
    """Return X as a 2-D float array (n_samples, n_features); 1-D means one feature."""
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    if X.ndim != 2 or X.shape[0] == 0:
        raise ValueError(f"{name} must be a non-empty 1-D or 2-D array.")
    if not np.all(np.isfinite(X)):
        raise ValueError(f"{name} must not contain NaN or infinite values.")
    return X


class KNNRegressor:
    """Brute-force k-nearest-neighbours regression (from scratch).

    Parameters
    ----------
    k : int, optional
        Number of neighbours, >= 1. Default 5.
    weights : str, optional
        "uniform" (default) or "distance".

    Raises
    ------
    TypeError, ValueError
        For invalid k or weights.

    Example
    -------
    >>> knn = KNNRegressor(k=2).fit([[0.0], [1.0], [3.0]], [0.0, 1.0, 3.0])
    >>> knn.predict([[0.4]]).tolist()
    [0.5]
    """

    def __init__(self, k=5, weights="uniform"):
        if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 1:
            raise ValueError(f"k must be an integer >= 1, got {k!r}.")
        if weights not in VALID_WEIGHTS:
            raise ValueError(f"weights must be one of {VALID_WEIGHTS}, got {weights!r}.")
        self.k = int(k)
        self.weights = weights
        self._X = None

    def fit(self, X, y):
        """Store the training data.

        Parameters
        ----------
        X : array_like
            Features, shape (n,) or (n, n_features), finite.
        y : array_like
            Targets, shape (n,), finite.

        Returns
        -------
        KNNRegressor
            ``self``.

        Raises
        ------
        ValueError
            For empty/mismatched/non-finite inputs, or k larger than n.
        """
        X = _as_feature_matrix(X, "X")
        y = np.asarray(y, dtype=float).reshape(-1)
        if y.size != X.shape[0]:
            raise ValueError(f"X has {X.shape[0]} rows but y has {y.size} values.")
        if not np.all(np.isfinite(y)):
            raise ValueError("y must not contain NaN or infinite values.")
        if self.k > y.size:
            raise ValueError(f"k = {self.k} is larger than the number of training points ({y.size}).")
        self._X, self._y = X, y
        return self

    def _predict_block(self, queries):
        # Distance from every query (rows) to every training point (columns).
        differences = queries[:, None, :] - self._X[None, :, :]
        distances = np.sqrt(np.sum(differences**2, axis=2))
        # k-th smallest distance per query; np.partition finds it without a full sort.
        kth = np.partition(distances, self.k - 1, axis=1)[:, self.k - 1]
        # Every point at or inside the k-th distance is a neighbour (ties included).
        neighbours = distances <= kth[:, None]
        if self.weights == "uniform":
            weight = neighbours.astype(float)
        else:
            with np.errstate(divide="ignore"):
                weight = np.where(neighbours, 1.0 / distances, 0.0)
            exact = neighbours & (distances == 0.0)
            has_exact = np.any(exact, axis=1)
            # Exact matches get all the weight (1/0 would be infinite).
            weight[has_exact] = exact[has_exact].astype(float)
        return (weight @ self._y) / np.sum(weight, axis=1)

    def predict(self, X):
        """Predict targets for the query points.

        Parameters
        ----------
        X : array_like
            Queries, shape (m,) or (m, n_features); same number of features
            as the training data.

        Returns
        -------
        numpy.ndarray
            Shape (m,).

        Raises
        ------
        NotFittedError
            Before ``fit``.
        ValueError
            For invalid queries or a feature-count mismatch.
        """
        if self._X is None:
            raise NotFittedError("Call fit() before predict().")
        queries = _as_feature_matrix(X, "X")
        if queries.shape[1] != self._X.shape[1]:
            raise ValueError(f"X has {queries.shape[1]} features; the model was fitted "
                             f"with {self._X.shape[1]}.")
        blocks = []
        for start in range(0, queries.shape[0], QUERY_BLOCK_SIZE):
            blocks.append(self._predict_block(queries[start:start + QUERY_BLOCK_SIZE]))
        return np.concatenate(blocks)


class KNNDegradationModel:
    """Non-parametric degradation d(tyre_age) learned by KNN, with per-stint offsets.

    Steps of ``fit``: (1) fit the linear per-stint model to get each stint's
    offset (its new-tyre lap time); (2) subtract the offsets, leaving
    degradation + noise; (3) store these for KNN on tyre age.

    Parameters
    ----------
    compound : str
        Pirelli compound code, e.g. "C3".
    k : int, optional
        Number of neighbours, >= 1 (candidates 10-400, chosen in Phase 5).
        Default 50.
    weights : str, optional
        "uniform" (default) or "distance".
    negative_tolerance_s : float, optional
        Degradation below -tolerance [s] is flagged. Default 0.01.

    Raises
    ------
    TypeError, ValueError
        For an unknown compound or invalid k/weights.

    Example
    -------
    >>> ages = np.tile(np.arange(1.0, 21.0), 3)
    >>> times = 80.0 + 0.1 * ages
    >>> model = KNNDegradationModel("C3", k=3).fit(ages, times, [0] * 20 + [1] * 20 + [2] * 20)
    >>> model.degradation([10.0]).round(6).tolist()
    [1.0]
    """

    def __init__(self, compound, k=DEFAULT_K, weights=DEFAULT_WEIGHTS,
                 negative_tolerance_s=DEFAULT_NEGATIVE_TOLERANCE_S):
        self.compound = check_compound(compound)
        self._knn = KNNRegressor(k, weights)
        if not negative_tolerance_s >= 0:
            raise ValueError("negative_tolerance_s must be >= 0.")
        self.k = self._knn.k
        self.weights = weights
        self.negative_tolerance_s = float(negative_tolerance_s)
        self._fitted = False

    def fit(self, tyre_age, lap_time, stint_id=None):
        """Remove stint offsets (linear per-stint model), then store the data for KNN.

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
        KNNDegradationModel
            ``self``, fitted.

        Raises
        ------
        ValueError
            For invalid inputs, too few laps, or k > number of laps.
        """
        data = prepare_stint_data(tyre_age, lap_time, stint_id)
        check_degrees_of_freedom(data, 1)
        linear = PolynomialDegradationModel(self.compound, degree=1).fit(
            data.tyre_age, data.lap_time, data.stint_labels[data.stint_index])
        self._offsets = linear._offsets
        adjusted = data.lap_time - self._offsets[data.stint_index]
        self._knn.fit(data.tyre_age, adjusted)
        self._data = data
        self._fitted = True
        self._constraint = check_non_negative(self.degradation, float(data.tyre_age.max()),
                                              self.negative_tolerance_s)
        return self

    def _require_fitted(self):
        if not self._fitted:
            raise NotFittedError("Call fit() before using the model.")

    def degradation(self, tyre_age):
        """KNN estimate of d(tyre_age) [s] (relative to a new tyre).

        Parameters
        ----------
        tyre_age : float or array_like
            Tyre age(s) [laps], >= 0.

        Returns
        -------
        numpy.ndarray

        Raises
        ------
        NotFittedError, ValueError
        """
        self._require_fitted()
        return self._knn.predict(check_tyre_age(tyre_age))

    def predict(self, tyre_age, base_time=None):
        """Predicted lap time [s] = base_time + d(tyre_age); base default = median offset.

        Raises
        ------
        NotFittedError, ValueError
        """
        self._require_fitted()
        base = self.base_time if base_time is None else float(base_time)
        if not np.isfinite(base) or base <= 0:
            raise ValueError(f"base_time must be a positive number of seconds, got {base_time!r}.")
        return base + self.degradation(tyre_age)

    @property
    def base_time(self):
        """float: median stint offset [s]."""
        self._require_fitted()
        return float(np.median(self._offsets))

    def params(self):
        """Settings and diagnostics as a dictionary (KNN has no fitted parameters).

        Returns
        -------
        dict
            Keys: compound, model, k, weights, base_time, n_laps, n_stints,
            min_training_age, max_training_age, min_degradation,
            negative_degradation_flag.

        Raises
        ------
        NotFittedError
        """
        self._require_fitted()
        return {
            "compound": self.compound,
            "model": "knn",
            "k": self.k,
            "weights": self.weights,
            "base_time": self.base_time,
            "n_laps": self._data.n_laps,
            "n_stints": self._data.n_stints,
            "min_training_age": float(self._data.tyre_age.min()),
            "max_training_age": float(self._data.tyre_age.max()),
            "min_degradation": self._constraint.min_degradation_s,
            "negative_degradation_flag": self._constraint.violated,
        }

    def summary(self):
        """Human-readable report (str)."""
        p = self.params()
        status = "VIOLATED" if p["negative_degradation_flag"] else "ok"
        return "\n".join([
            f"KNN degradation model, compound {p['compound']}, k = {p['k']}, weights = {p['weights']}",
            f"  {p['n_laps']} laps in {p['n_stints']} stints; tyre age {p['min_training_age']:.0f}-"
            f"{p['max_training_age']:.0f} laps (no extrapolation beyond); base time {p['base_time']:.3f} s",
            f"  non-negative degradation: {status} (min d = {p['min_degradation']:.4f} s)",
        ])
