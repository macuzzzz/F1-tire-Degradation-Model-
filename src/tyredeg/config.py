"""Load and validate the project configuration (``config.yaml``).

The rest of the code never reads the YAML file directly. It calls
:func:`load_config`, which returns a :class:`Config` object whose values have
already been checked for type and range. This means a typo in ``config.yaml``
fails immediately with a clear message, instead of causing a confusing error
deep inside a numerical method later on.

Structure of this module
------------------------
1. Small ``_require_*`` helpers, each checking one kind of value.
2. Dataclasses that hold the validated values (:class:`RaceSpec`, :class:`Config`).
3. :func:`config_from_dict`, which validates a plain dictionary section by section.
4. :func:`load_config`, which reads the YAML file and calls ``config_from_dict``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

import yaml

# FastF1 lap-timing data is only available from the 2018 season onward
# (see DECISIONS.md, D12), so earlier years are rejected.
FIRST_SUPPORTED_YEAR = 2018

# The project only models races (D8). Sprint/practice sessions have different
# fuel loads and tyre rules, so they would not be comparable.
SUPPORTED_SESSIONS = ("R",)

# Compound names as they appear in FastF1's `Compound` column.
# SOFT/MEDIUM/HARD are *relative* names: which Pirelli compound (C1-C6) they
# refer to depends on the event (see DECISIONS.md, D4).
VALID_COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")

VALID_RACE_ROLES = ("train", "test")

# Where lap data comes from (D14): FastF1 (free mirror, 2021-2022) or the
# OpenF1 web API (free historical data from 2023 onward).
VALID_SOURCES = ("fastf1", "openf1")
OPENF1_FIRST_YEAR = 2023

# Pirelli compound codes: C0 (hardest, 2023-2024 only) to C6 (softest, 2025 only).
VALID_PIRELLI_COMPOUNDS = ("C0", "C1", "C2", "C3", "C4", "C5", "C6")


# ---------------------------------------------------------------------------
# 1. Validation helpers
# ---------------------------------------------------------------------------
def _require_int(value, name, minimum=None, maximum=None):
    """Return ``value`` if it is an int within [minimum, maximum], else raise.

    ``bool`` is rejected explicitly because in Python ``True`` is an ``int``
    (``True == 1``), so ``random_seed: true`` would otherwise be accepted.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"'{name}' must be an integer, got {value!r}.")
    if minimum is not None and value < minimum:
        raise ValueError(f"'{name}' must be >= {minimum}, got {value}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"'{name}' must be <= {maximum}, got {value}.")
    return value


def _require_float(value, name, minimum=None, strictly_positive=False):
    """Return ``value`` as a float if it is a real number in range, else raise.

    Integers are accepted (YAML reads ``90`` as an int) and converted to float.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"'{name}' must be a number, got {value!r}.")
    value = float(value)
    # NaN compares False with everything, so it would slip through the range
    # checks below; reject it explicitly.
    if value != value:
        raise ValueError(f"'{name}' must not be NaN.")
    if strictly_positive and value <= 0:
        raise ValueError(f"'{name}' must be > 0, got {value}.")
    if minimum is not None and value < minimum:
        raise ValueError(f"'{name}' must be >= {minimum}, got {value}.")
    return value


def _require_string(value, name):
    """Return ``value`` stripped of surrounding spaces if it is a non-empty string."""
    if not isinstance(value, str):
        raise TypeError(f"'{name}' must be a string, got {value!r}.")
    if value.strip() == "":
        raise ValueError(f"'{name}' must not be empty.")
    return value.strip()


def _require_string_list(value, name, allowed=None):
    """Return a tuple of strings, or ``None`` if ``value`` is ``None``.

    ``None`` means "no filter" (keep everything). An empty list is rejected
    because it would silently select nothing.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"'{name}' must be a list of strings or null, got {value!r}.")
    if len(value) == 0:
        raise ValueError(f"'{name}' must not be an empty list; use null for 'all'.")
    items = []
    for item in value:
        item = _require_string(item, f"{name} entry")
        if allowed is not None and item not in allowed:
            raise ValueError(
                f"Unknown value {item!r} in '{name}'. Allowed values: {allowed}."
            )
        items.append(item)
    return tuple(items)


def _require_section(raw, name):
    """Return the sub-dictionary ``raw[name]``, raising if it is missing or not a mapping."""
    if name not in raw:
        raise ValueError(f"Missing section '{name}' in the configuration.")
    section = raw[name]
    if not isinstance(section, dict):
        raise TypeError(f"Section '{name}' must be a mapping, got {section!r}.")
    return section


def _require_key(section, key, section_name):
    """Return ``section[key]``, raising a clear error if the key is absent.

    The key must be present even when its value is ``null``, so that a
    misspelt key name is caught rather than silently treated as "not set".
    """
    if key not in section:
        raise ValueError(f"Missing key '{key}' in section '{section_name}'.")
    return section[key]


# ---------------------------------------------------------------------------
# 2. Containers for validated values
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RaceSpec:
    """One race used in the project.

    ``frozen=True`` makes the object read-only, so no part of the code can
    accidentally change the configuration after it has been validated.

    Attributes
    ----------
    year : int
        Championship season, e.g. 2023.
    event : str
        Official FastF1 event name, e.g. ``"Bahrain Grand Prix"``.
    role : str
        ``"train"`` (used for fitting/model selection) or ``"test"`` (held out).
    source : str
        ``"fastf1"`` or ``"openf1"`` - where the lap data is downloaded from.
    """

    year: int
    event: str
    role: str
    source: str


@dataclass(frozen=True)
class OdeSettings:
    """Defaults for the ODE solvers (D25-D29). See ``numerics.ode`` in config.yaml."""

    rtol: float
    atol: float
    initial_step_fraction: float
    max_steps: int
    safety: float
    min_factor: float
    max_factor: float


@dataclass(frozen=True)
class RootFindingSettings:
    """Defaults for the root finders (D30, D31). See ``numerics.root_finding``."""

    xtol: float
    ftol: float
    max_iter: int
    divergence_limit: float


@dataclass(frozen=True)
class NumericsSettings:
    """All Phase 3 numerical defaults (``numerics`` section of config.yaml)."""

    ode: OdeSettings
    root_finding: RootFindingSettings
    forward_step_exponent: float
    central_step_exponent: float
    second_step_exponent: float
    condition_warning_threshold: float
    scale_polynomial_inputs: bool


@dataclass(frozen=True)
class VerificationSettings:
    """Tolerances the tests use to accept a numerical method (D37)."""

    ode_order_tolerance: float
    rk45_tolerance_factor: float
    rk45_max_nfev_ratio: float
    newton_order_tolerance: float
    secant_order_tolerance: float
    difference_order_tolerance: float
    linear_solver_rtol: float
    least_squares_rtol: float
    least_squares_se_multiple: float


@dataclass(frozen=True)
class ModelSettings:
    """Phase 4 degradation-model settings (``models`` section, D39-D46)."""

    candidate_degrees: tuple[int, ...]
    default_degree: int
    b_bracket: tuple[float, float]
    b_grid_points: int
    b_xtol: float
    b_ftol: float
    ode_solver: str
    rk4_step: float
    rk45_rtol: float
    rk45_atol: float
    candidate_k: tuple[int, ...]
    candidate_weights: tuple[str, ...]
    default_k: int
    default_weights: str
    negative_degradation_tolerance_s: float
    bootstrap_resamples: int
    confidence_level: float


@dataclass(frozen=True)
class Config:
    """Validated project configuration.

    See ``config.yaml`` for the meaning and units of each field. Fields that
    are ``None`` have not been decided yet and are filled in later phases.
    """

    random_seed: int
    session: str
    races: tuple[RaceSpec, ...]
    teams: tuple[str, ...] | None
    drivers: tuple[str, ...] | None
    pirelli_compounds: tuple[str, ...]
    allocation_file: Path
    fastf1_cache_dir: Path
    openf1_cache_dir: Path
    openf1_request_delay_s: float
    openf1_max_retries: int
    total_laps_override: int | None
    k_fuel: float | None
    k_fuel_range: tuple[float, float] | None
    pit_loss_override: float | None
    outlier_k: float | None
    min_stint_laps: int | None
    numerics: NumericsSettings
    verification: VerificationSettings
    models: ModelSettings

    @property
    def train_races(self):
        """tuple of RaceSpec: the races with role ``"train"``."""
        return tuple(race for race in self.races if race.role == "train")

    @property
    def test_races(self):
        """tuple of RaceSpec: the races with role ``"test"`` (held out)."""
        return tuple(race for race in self.races if race.role == "test")


# ---------------------------------------------------------------------------
# 3. Validate a dictionary
# ---------------------------------------------------------------------------
def _parse_race(entry, index, last_year):
    """Validate one entry of ``data.races`` and return a :class:`RaceSpec`."""
    name = f"data.races[{index}]"
    if not isinstance(entry, dict):
        raise TypeError(f"'{name}' must be a mapping with year/event/role, got {entry!r}.")
    year = _require_int(
        _require_key(entry, "year", name), f"{name}.year", FIRST_SUPPORTED_YEAR, last_year
    )
    event = _require_string(_require_key(entry, "event", name), f"{name}.event")
    role = _require_string(_require_key(entry, "role", name), f"{name}.role")
    if role not in VALID_RACE_ROLES:
        raise ValueError(f"'{name}.role' must be one of {VALID_RACE_ROLES}, got {role!r}.")
    source = _require_string(_require_key(entry, "source", name), f"{name}.source")
    if source not in VALID_SOURCES:
        raise ValueError(f"'{name}.source' must be one of {VALID_SOURCES}, got {source!r}.")
    if source == "openf1" and year < OPENF1_FIRST_YEAR:
        raise ValueError(
            f"'{name}': OpenF1 only has free data from {OPENF1_FIRST_YEAR} onward, got {year}."
        )
    return RaceSpec(year=year, event=event, role=role, source=source)


def _parse_races(raw_races):
    """Validate the whole ``data.races`` list.

    Checks that there is at least one training and one test race and that no
    race is listed twice. A duplicated race could end up in both the training
    and the test set, which would leak test information into model selection.
    """
    if not isinstance(raw_races, list) or len(raw_races) == 0:
        raise ValueError("'data.races' must be a non-empty list of races.")

    # A season cannot be later than the current calendar year.
    last_year = datetime.date.today().year
    races = []
    for index, entry in enumerate(raw_races):
        races.append(_parse_race(entry, index, last_year))

    seen = set()
    for race in races:
        key = (race.year, race.event.casefold())
        if key in seen:
            raise ValueError(f"Race {race.year} {race.event!r} is listed more than once.")
        seen.add(key)

    roles = {race.role for race in races}
    if "train" not in roles:
        raise ValueError("At least one race must have role 'train'.")
    if "test" not in roles:
        raise ValueError("At least one race must have role 'test'.")
    return tuple(races)


def _optional(value, check, *args, **kwargs):
    """Return ``None`` if ``value`` is ``None``, otherwise ``check(value, ...)``.

    Used for keys that are still ``null`` because they are decided in a later
    phase: the range is only checked once a value has been filled in.
    """
    if value is None:
        return None
    return check(value, *args, **kwargs)


def _parse_k_fuel_range(fuel, k_fuel):
    """Validate ``fuel.k_fuel_min`` / ``fuel.k_fuel_max`` (sensitivity range).

    Returns ``None`` if both are null, otherwise ``(min, max)``. The default
    ``k_fuel`` must lie inside the range, otherwise the sensitivity analysis
    would not bracket the value actually used.
    """
    low = _optional(_require_key(fuel, "k_fuel_min", "fuel"), _require_float, "fuel.k_fuel_min", 0.0)
    high = _optional(_require_key(fuel, "k_fuel_max", "fuel"), _require_float, "fuel.k_fuel_max", 0.0)
    if low is None and high is None:
        return None
    if low is None or high is None:
        raise ValueError("'fuel.k_fuel_min' and 'fuel.k_fuel_max' must both be set or both be null.")
    if low > high:
        raise ValueError(f"'fuel.k_fuel_min' ({low}) must be <= 'fuel.k_fuel_max' ({high}).")
    if k_fuel is not None and not low <= k_fuel <= high:
        raise ValueError(f"'fuel.k_fuel' ({k_fuel}) must lie within [{low}, {high}].")
    return (low, high)


def _positive_float(section, key, section_name):
    """Read ``section[key]`` and require a finite number > 0."""
    return _require_float(
        _require_key(section, key, section_name), f"{section_name}.{key}", strictly_positive=True
    )


def _parse_ode(section):
    """Validate ``numerics.ode``."""
    name = "numerics.ode"
    settings = OdeSettings(
        rtol=_positive_float(section, "rtol", name),
        atol=_positive_float(section, "atol", name),
        initial_step_fraction=_positive_float(section, "initial_step_fraction", name),
        max_steps=_require_int(_require_key(section, "max_steps", name), f"{name}.max_steps", 1),
        safety=_positive_float(section, "safety", name),
        min_factor=_positive_float(section, "min_factor", name),
        max_factor=_positive_float(section, "max_factor", name),
    )
    # A safety factor above 1 would aim for steps that are expected to fail.
    if settings.safety > 1:
        raise ValueError(f"'{name}.safety' must be <= 1, got {settings.safety}.")
    # The controller must be able to shrink (min < 1) and to grow (max > 1).
    if not settings.min_factor < 1 < settings.max_factor:
        raise ValueError(f"'{name}' needs min_factor < 1 < max_factor.")
    if settings.initial_step_fraction > 1:
        raise ValueError(f"'{name}.initial_step_fraction' must be <= 1.")
    return settings


def _parse_root_finding(section):
    """Validate ``numerics.root_finding``."""
    name = "numerics.root_finding"
    return RootFindingSettings(
        xtol=_positive_float(section, "xtol", name),
        ftol=_positive_float(section, "ftol", name),
        max_iter=_require_int(_require_key(section, "max_iter", name), f"{name}.max_iter", 1),
        divergence_limit=_positive_float(section, "divergence_limit", name),
    )


def _parse_numerics(raw):
    """Validate the ``numerics`` section (Phase 3 defaults)."""
    numerics = _require_section(raw, "numerics")
    differentiation = _require_section(numerics, "differentiation")
    exponents = {}
    for key in ("forward_step_exponent", "central_step_exponent", "second_step_exponent"):
        value = _positive_float(differentiation, key, "numerics.differentiation")
        # eps**exponent must be a small step, so the exponent lies in (0, 1).
        if value >= 1:
            raise ValueError(f"'numerics.differentiation.{key}' must be < 1, got {value}.")
        exponents[key] = value
    linear = _require_section(numerics, "linear")
    least_squares = _require_section(numerics, "least_squares")
    scale = _require_key(least_squares, "scale_polynomial_inputs", "numerics.least_squares")
    if not isinstance(scale, bool):
        raise TypeError(
            f"'numerics.least_squares.scale_polynomial_inputs' must be true/false, got {scale!r}."
        )
    return NumericsSettings(
        ode=_parse_ode(_require_section(numerics, "ode")),
        root_finding=_parse_root_finding(_require_section(numerics, "root_finding")),
        condition_warning_threshold=_positive_float(
            linear, "condition_warning_threshold", "numerics.linear"
        ),
        scale_polynomial_inputs=scale,
        **exponents,
    )


def _parse_verification(raw):
    """Validate the ``verification`` section (test acceptance tolerances)."""
    section = _require_section(raw, "verification")
    values = {}
    for key in VerificationSettings.__dataclass_fields__:
        values[key] = _positive_float(section, key, "verification")
    return VerificationSettings(**values)


VALID_ODE_SOLVERS = ("rk4", "rk45", "exact")
VALID_KNN_WEIGHTS = ("uniform", "distance")


def _int_list(value, name, minimum):
    """Validate a non-empty list of distinct integers >= minimum."""
    if not isinstance(value, list) or len(value) == 0:
        raise TypeError(f"'{name}' must be a non-empty list of integers, got {value!r}.")
    items = tuple(_require_int(item, f"{name} entry", minimum) for item in value)
    if len(set(items)) != len(items):
        raise ValueError(f"'{name}' contains duplicates: {list(items)}.")
    return items


def _parse_models(raw):
    """Validate the ``models`` section (Phase 4)."""
    models = _require_section(raw, "models")
    poly = _require_section(models, "polynomial")
    ode = _require_section(models, "wear_ode")
    knn = _require_section(models, "knn")

    degrees = _int_list(_require_key(poly, "candidate_degrees", "models.polynomial"),
                        "models.polynomial.candidate_degrees", 1)
    default_degree = _require_int(_require_key(poly, "default_degree", "models.polynomial"),
                                  "models.polynomial.default_degree", 1)
    if default_degree not in degrees:
        raise ValueError("'models.polynomial.default_degree' must be one of the candidate degrees.")

    bracket = _require_key(ode, "b_bracket", "models.wear_ode")
    if not isinstance(bracket, list) or len(bracket) != 2:
        raise TypeError("'models.wear_ode.b_bracket' must be a [low, high] list.")
    low = _require_float(bracket[0], "models.wear_ode.b_bracket[0]")
    high = _require_float(bracket[1], "models.wear_ode.b_bracket[1]")
    if not low < high:
        raise ValueError("'models.wear_ode.b_bracket' must satisfy low < high.")
    solver = _require_string(_require_key(ode, "solver", "models.wear_ode"), "models.wear_ode.solver")
    if solver not in VALID_ODE_SOLVERS:
        raise ValueError(f"'models.wear_ode.solver' must be one of {VALID_ODE_SOLVERS}, got {solver!r}.")
    b_xtol = _require_float(_require_key(ode, "b_xtol", "models.wear_ode"), "models.wear_ode.b_xtol", 0.0)
    b_ftol = _require_float(_require_key(ode, "b_ftol", "models.wear_ode"), "models.wear_ode.b_ftol", 0.0)
    if b_xtol == 0 and b_ftol == 0:
        raise ValueError("'models.wear_ode': b_xtol and b_ftol cannot both be 0.")

    candidate_k = _int_list(_require_key(knn, "candidate_k", "models.knn"), "models.knn.candidate_k", 1)
    weights = _require_string_list(_require_key(knn, "candidate_weights", "models.knn"),
                                   "models.knn.candidate_weights", VALID_KNN_WEIGHTS)
    if weights is None:
        raise ValueError("'models.knn.candidate_weights' must list at least one weighting.")
    default_k = _require_int(_require_key(knn, "default_k", "models.knn"), "models.knn.default_k", 1)
    default_weights = _require_string(_require_key(knn, "default_weights", "models.knn"),
                                      "models.knn.default_weights")
    if default_weights not in weights:
        raise ValueError("'models.knn.default_weights' must be one of the candidate weightings.")

    confidence = _positive_float(models, "confidence_level", "models")
    if confidence >= 1:
        raise ValueError(f"'models.confidence_level' must be < 1, got {confidence}.")

    return ModelSettings(
        candidate_degrees=degrees,
        default_degree=default_degree,
        b_bracket=(low, high),
        b_grid_points=_require_int(_require_key(ode, "b_grid_points", "models.wear_ode"),
                                   "models.wear_ode.b_grid_points", 3),
        b_xtol=b_xtol,
        b_ftol=b_ftol,
        ode_solver=solver,
        rk4_step=_positive_float(ode, "rk4_step", "models.wear_ode"),
        rk45_rtol=_positive_float(ode, "rk45_rtol", "models.wear_ode"),
        rk45_atol=_positive_float(ode, "rk45_atol", "models.wear_ode"),
        candidate_k=candidate_k,
        candidate_weights=weights,
        default_k=default_k,
        default_weights=default_weights,
        negative_degradation_tolerance_s=_require_float(
            _require_key(models, "negative_degradation_tolerance_s", "models"),
            "models.negative_degradation_tolerance_s", 0.0,
        ),
        bootstrap_resamples=_require_int(_require_key(models, "bootstrap_resamples", "models"),
                                         "models.bootstrap_resamples", 2),
        confidence_level=confidence,
    )


def config_from_dict(raw):
    """Build a validated :class:`Config` from a plain dictionary.

    Parameters
    ----------
    raw : dict
        Configuration with the same structure as ``config.yaml``.

    Returns
    -------
    Config
        The validated configuration.

    Raises
    ------
    TypeError
        If a value has the wrong type (e.g. a string where a number is needed).
    ValueError
        If a section or key is missing, or a value is out of its valid range.

    Example
    -------
    >>> import yaml
    >>> raw = yaml.safe_load(open("config.yaml"))
    >>> config = config_from_dict(raw)
    >>> config.session
    'R'
    """
    if not isinstance(raw, dict):
        raise TypeError(f"The configuration must be a mapping, got {type(raw).__name__}.")

    seed = _require_int(_require_key(raw, "random_seed", "top level"), "random_seed", 0)

    data = _require_section(raw, "data")
    session = _require_string(_require_key(data, "session", "data"), "data.session")
    if session not in SUPPORTED_SESSIONS:
        raise ValueError(f"'data.session' must be one of {SUPPORTED_SESSIONS}, got {session!r}.")
    races = _parse_races(_require_key(data, "races", "data"))
    teams = _require_string_list(_require_key(data, "teams", "data"), "data.teams")
    drivers = _require_string_list(_require_key(data, "drivers", "data"), "data.drivers")
    pirelli_compounds = _require_string_list(
        _require_key(data, "pirelli_compounds", "data"), "data.pirelli_compounds",
        VALID_PIRELLI_COMPOUNDS,
    )
    if pirelli_compounds is None:
        raise ValueError("'data.pirelli_compounds' must list at least one compound.")
    allocation_file = Path(
        _require_string(_require_key(data, "allocation_file", "data"), "data.allocation_file")
    )

    fastf1_section = _require_section(raw, "fastf1")
    fastf1_cache_dir = Path(
        _require_string(_require_key(fastf1_section, "cache_dir", "fastf1"), "fastf1.cache_dir")
    )

    openf1_section = _require_section(raw, "openf1")
    openf1_cache_dir = Path(
        _require_string(_require_key(openf1_section, "cache_dir", "openf1"), "openf1.cache_dir")
    )
    request_delay = _require_float(
        _require_key(openf1_section, "request_delay_s", "openf1"), "openf1.request_delay_s", 0.0
    )
    max_retries = _require_int(
        _require_key(openf1_section, "max_retries", "openf1"), "openf1.max_retries", 1
    )

    race = _require_section(raw, "race")
    # A race needs at least 2 laps so that a pit stop can happen between laps.
    total_laps = _optional(
        _require_key(race, "total_laps_override", "race"), _require_int,
        "race.total_laps_override", 2,
    )

    fuel = _require_section(raw, "fuel")
    # Carrying fuel can only make the car slower, so the coefficient is >= 0.
    k_fuel = _optional(_require_key(fuel, "k_fuel", "fuel"), _require_float, "fuel.k_fuel", 0.0)
    k_fuel_range = _parse_k_fuel_range(fuel, k_fuel)

    pit = _require_section(raw, "pit")
    pit_loss = _optional(
        _require_key(pit, "pit_loss_override", "pit"), _require_float,
        "pit.pit_loss_override", strictly_positive=True,
    )

    cleaning = _require_section(raw, "cleaning")
    outlier_k = _optional(
        _require_key(cleaning, "outlier_k", "cleaning"), _require_float,
        "cleaning.outlier_k", strictly_positive=True,
    )
    min_stint = _optional(
        _require_key(cleaning, "min_stint_laps", "cleaning"), _require_int,
        "cleaning.min_stint_laps", 1,
    )

    return Config(
        random_seed=seed,
        session=session,
        races=races,
        teams=teams,
        drivers=drivers,
        pirelli_compounds=pirelli_compounds,
        allocation_file=allocation_file,
        fastf1_cache_dir=fastf1_cache_dir,
        openf1_cache_dir=openf1_cache_dir,
        openf1_request_delay_s=request_delay,
        openf1_max_retries=max_retries,
        total_laps_override=total_laps,
        k_fuel=k_fuel,
        k_fuel_range=k_fuel_range,
        pit_loss_override=pit_loss,
        outlier_k=outlier_k,
        min_stint_laps=min_stint,
        numerics=_parse_numerics(raw),
        verification=_parse_verification(raw),
        models=_parse_models(raw),
    )


# ---------------------------------------------------------------------------
# 4. Read the YAML file
# ---------------------------------------------------------------------------
def load_config(path="config.yaml"):
    """Read ``config.yaml`` and return a validated :class:`Config`.

    Parameters
    ----------
    path : str or pathlib.Path, optional
        Path to the YAML configuration file. Default ``"config.yaml"``
        (relative to the current working directory).

    Returns
    -------
    Config
        The validated configuration.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the file is not valid YAML, or a value is missing/out of range.
    TypeError
        If a value has the wrong type.

    Example
    -------
    >>> config = load_config("config.yaml")
    >>> [race.year for race in config.test_races]
    [2025]
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")
    with path.open("r", encoding="utf-8") as file:
        try:
            # safe_load only builds plain Python types (dict, list, str, ...);
            # yaml.load could execute arbitrary code from a malicious file.
            raw = yaml.safe_load(file)
        except yaml.YAMLError as error:
            raise ValueError(f"{path} is not valid YAML: {error}") from error
    return config_from_dict(raw)
