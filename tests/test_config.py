"""Offline tests for tyredeg.config (loading and validating config.yaml)."""

import copy
from pathlib import Path

import pytest
import yaml

from tyredeg.config import Config, config_from_dict, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_RAW = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))


def valid_raw_config():
    """A complete, valid configuration dictionary (same shape as config.yaml)."""
    return {
        "random_seed": 42,
        "data": {
            "session": "R",
            "races": [
                {"year": 2022, "event": "Hungarian Grand Prix", "role": "train", "source": "fastf1"},
                {"year": 2023, "event": "Hungarian Grand Prix", "role": "test", "source": "openf1"},
            ],
            "teams": ["Red Bull Racing"],
            "drivers": None,
            "pirelli_compounds": ["C3"],
            "allocation_file": "reference/pirelli_allocation.csv",
        },
        "fastf1": {"cache_dir": "cache/fastf1"},
        "openf1": {"cache_dir": "cache/openf1", "request_delay_s": 0.4, "max_retries": 5},
        "race": {"total_laps_override": None},
        "fuel": {"k_fuel": None, "k_fuel_min": None, "k_fuel_max": None},
        "pit": {"pit_loss_override": None},
        "cleaning": {"outlier_k": None, "min_stint_laps": None},
        # The Phase 3 sections are copied from the real config.yaml.
        "numerics": copy.deepcopy(PROJECT_RAW["numerics"]),
        "verification": copy.deepcopy(PROJECT_RAW["verification"]),
        "models": copy.deepcopy(PROJECT_RAW["models"]),
        "validation": copy.deepcopy(PROJECT_RAW["validation"]),
        "strategy": {**copy.deepcopy(PROJECT_RAW["strategy"]), "data_years": [2023]},
        "sensitivity": copy.deepcopy(PROJECT_RAW["sensitivity"]),
        "performance": copy.deepcopy(PROJECT_RAW["performance"]),
    }


def with_change(section, key, value):
    """Return a valid config with one value replaced (section=None for top level)."""
    raw = copy.deepcopy(valid_raw_config())
    if section is None:
        raw[key] = value
    else:
        raw[section][key] = value
    return raw


# ---------------------------------------------------------------------------
# Valid configurations
# ---------------------------------------------------------------------------
def test_project_config_file_is_valid():
    config = load_config(REPO_ROOT / "config.yaml")
    assert isinstance(config, Config)
    assert config.session == "R"
    assert config.pirelli_compounds == ("C3", "C4")  # D52 adds C4
    assert config.teams is None  # all teams (D6 amendment)
    assert (REPO_ROOT / config.allocation_file).is_file()
    # Phase 2 values (D19-D22)
    assert config.k_fuel == 0.046
    assert config.k_fuel_range == (0.015, 0.070)
    assert config.outlier_k == 3.0
    assert config.min_stint_laps == 10
    assert len(config.train_races) >= 1
    assert len(config.test_races) >= 1


def test_valid_dict_builds_config():
    config = config_from_dict(valid_raw_config())
    assert config.random_seed == 42
    assert config.fastf1_cache_dir == Path("cache/fastf1")
    assert config.openf1_cache_dir == Path("cache/openf1")
    assert config.openf1_request_delay_s == 0.4
    assert config.openf1_max_retries == 5
    assert [race.year for race in config.train_races] == [2022]
    assert [race.source for race in config.test_races] == ["openf1"]
    assert config.k_fuel is None  # null is allowed in the dictionary
    assert config.k_fuel_range is None


def test_filled_in_phase2_values_are_accepted_and_converted():
    raw = valid_raw_config()
    raw["fuel"]["k_fuel"] = 0  # YAML int is accepted and turned into a float
    raw["pit"]["pit_loss_override"] = 21.5
    raw["cleaning"]["outlier_k"] = 3
    raw["cleaning"]["min_stint_laps"] = 5
    config = config_from_dict(raw)
    assert config.k_fuel == 0.0 and isinstance(config.k_fuel, float)
    assert config.outlier_k == 3.0
    assert config.min_stint_laps == 5


def test_k_fuel_range_is_accepted():
    # A valid k_fuel range is read as a (min, max) pair.
    raw = valid_raw_config()
    raw["fuel"] = {"k_fuel": 0.046, "k_fuel_min": 0.015, "k_fuel_max": 0.07}
    assert config_from_dict(raw).k_fuel_range == (0.015, 0.07)


@pytest.mark.parametrize(
    "fuel, message",
    [
        ({"k_fuel": 0.046, "k_fuel_min": 0.015, "k_fuel_max": None}, "both"),
        ({"k_fuel": 0.046, "k_fuel_min": 0.07, "k_fuel_max": 0.015}, "<="),
        ({"k_fuel": 0.1, "k_fuel_min": 0.015, "k_fuel_max": 0.07}, "within"),
        ({"k_fuel": 0.046, "k_fuel_min": -0.01, "k_fuel_max": 0.07}, ">="),
    ],
)
def test_invalid_k_fuel_range_is_rejected(fuel, message):
    # Inconsistent k_fuel ranges are rejected with a message naming the problem.
    raw = valid_raw_config()
    raw["fuel"] = fuel
    with pytest.raises(ValueError, match=message):
        config_from_dict(raw)


@pytest.mark.parametrize(
    "path, value, error",
    [
        (("numerics", "ode", "rtol"), 0.0, ValueError),
        (("numerics", "ode", "safety"), 1.2, ValueError),
        (("numerics", "ode", "min_factor"), 1.5, ValueError),
        (("numerics", "ode", "max_factor"), 0.5, ValueError),
        (("numerics", "ode", "max_steps"), 10.5, TypeError),
        (("numerics", "root_finding", "xtol"), -1e-10, ValueError),
        (("numerics", "root_finding", "max_iter"), 0, ValueError),
        (("numerics", "differentiation", "central_step_exponent"), 1.0, ValueError),
        (("numerics", "linear", "condition_warning_threshold"), "1e12", TypeError),
        (("numerics", "least_squares", "scale_polynomial_inputs"), "yes", TypeError),
        (("verification", "ode_order_tolerance"), 0.0, ValueError),
    ],
)
def test_invalid_numerics_values_are_rejected(path, value, error):
    # Walk to the nested key, set the invalid value, and expect the error.
    raw = valid_raw_config()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(error):
        config_from_dict(raw)


def test_numerics_section_values():
    numerics = load_config(REPO_ROOT / "config.yaml").numerics
    assert (numerics.ode.rtol, numerics.ode.atol) == (1e-3, 1e-6)  # D29: SciPy defaults
    assert (numerics.ode.safety, numerics.ode.min_factor, numerics.ode.max_factor) == (0.9, 0.2, 10.0)
    assert numerics.condition_warning_threshold == 1e12
    assert numerics.scale_polynomial_inputs is True


def test_models_section_values():
    # The models section of the real config.yaml is read with the approved values.
    models = load_config(REPO_ROOT / "config.yaml").models
    assert models.candidate_degrees == (1, 2, 3)
    assert models.b_bracket == (-0.1, 0.1)
    assert (models.b_xtol, models.b_ftol) == (1e-8, 0.0)
    assert models.ode_solver == "rk4"
    assert models.candidate_k == (10, 25, 50, 100, 200, 400)
    assert models.candidate_weights == ("uniform", "distance")
    assert (models.bootstrap_resamples, models.confidence_level) == (200, 0.95)


@pytest.mark.parametrize(
    "path, value, error",
    [
        (("models", "polynomial", "candidate_degrees"), [], TypeError),
        (("models", "polynomial", "candidate_degrees"), [1, 1], ValueError),
        (("models", "polynomial", "default_degree"), 4, ValueError),
        (("models", "wear_ode", "b_bracket"), [0.1, -0.1], ValueError),
        (("models", "wear_ode", "b_bracket"), [0.1], TypeError),
        (("models", "wear_ode", "solver"), "euler", ValueError),
        (("models", "wear_ode", "b_grid_points"), 2, ValueError),
        (("models", "knn", "candidate_k"), [0, 5], ValueError),
        (("models", "knn", "candidate_weights"), ["gaussian"], ValueError),
        (("models", "knn", "default_weights"), "distance2", ValueError),
        (("models", "confidence_level"), 1.0, ValueError),
        (("models", "bootstrap_resamples"), 1, ValueError),
    ],
)
def test_invalid_models_values_are_rejected(path, value, error):
    # Walk to the nested key, set the invalid value, and expect the error.
    raw = valid_raw_config()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(error):
        config_from_dict(raw)


def test_validation_section_values():
    # The validation section of the real config.yaml is read with the approved values.
    validation = load_config(REPO_ROOT / "config.yaml").validation
    assert validation.anchor_laps == 3
    assert validation.max_abs_bias_s_per_lap == 0.10
    assert validation.monotonic_tolerance_s == 0.05
    assert validation.selection_file == Path("reports/model_selection.json")


@pytest.mark.parametrize(
    "key, value, error",
    [
        ("anchor_laps", 0, ValueError),
        ("anchor_laps", 2.5, TypeError),
        ("max_abs_bias_s_per_lap", 0.0, ValueError),
        ("monotonic_tolerance_s", -0.1, ValueError),
        ("selection_file", "", ValueError),
    ],
)
def test_invalid_validation_values_are_rejected(key, value, error):
    # Invalid validation settings are rejected.
    raw = valid_raw_config()
    raw["validation"][key] = value
    with pytest.raises(error):
        config_from_dict(raw)


def test_strategy_section_values():
    # The strategy section of the real config.yaml is read with the approved values.
    strategy = load_config(REPO_ROOT / "config.yaml").strategy
    assert strategy.data_years == (2023, 2024, 2025)
    assert strategy.compounds == ("C3", "C4")
    assert strategy.new_tyres and strategy.add_fuel_effect and strategy.include_two_stop
    assert strategy.min_laps_at_max_age == 5
    assert (strategy.root_xtol, strategy.root_ftol) == (1e-6, 0.0)


@pytest.mark.parametrize(
    "key, value, error",
    [
        ("data_years", [2030], ValueError),        # not among the configured races
        ("compounds", ["C3"], ValueError),         # a dry race needs two compounds
        ("compounds", ["C3", "SOFT"], ValueError),
        ("new_tyres", "yes", TypeError),
        ("min_laps_at_max_age", 0, ValueError),
        ("root_xtol", -1.0, ValueError),
    ],
)
def test_invalid_strategy_values_are_rejected(key, value, error):
    # Invalid strategy settings are rejected.
    raw = valid_raw_config()
    raw["strategy"][key] = value
    with pytest.raises(error):
        config_from_dict(raw)


def test_sensitivity_section_values():
    from tyredeg.sensitivity import DEFAULT_RELATIVE_STEP

    sensitivity = load_config(REPO_ROOT / "config.yaml").sensitivity
    assert sensitivity.rate_se_multiples == (-2, -1, 1, 2)
    assert sensitivity.relative_step == DEFAULT_RELATIVE_STEP == 0.01  # code default mirrors config
    assert sensitivity.delta_absolute_step == 0.01
    assert sensitivity.check_relative_steps == (0.001, 0.01, 0.1)
    assert sensitivity.alternative_min_laps == (3, 10)


@pytest.mark.parametrize(
    "key, value, error",
    [
        ("rate_se_multiples", [0, 1], ValueError),
        ("rate_se_multiples", [], TypeError),
        ("relative_step", 0.0, ValueError),
        ("check_relative_steps", [0.01, -0.1], ValueError),
        ("alternative_min_laps", [0], ValueError),
    ],
)
def test_invalid_sensitivity_values_are_rejected(key, value, error):
    # Invalid sensitivity settings are rejected.
    raw = valid_raw_config()
    raw["sensitivity"][key] = value
    with pytest.raises(error):
        config_from_dict(raw)


def test_performance_section_values():
    # The performance section matches the code defaults (both must stay in sync).
    from tyredeg.performance import DEFAULT_MIN_TIME_S, DEFAULT_REPEATS, DEFAULT_WARMUP

    performance = load_config(REPO_ROOT / "config.yaml").performance
    assert (performance.warmup, performance.repeats) == (DEFAULT_WARMUP, DEFAULT_REPEATS) == (1, 7)
    assert performance.min_time_per_repeat_s == DEFAULT_MIN_TIME_S == 0.01
    assert performance.ode_step_counts[0] == 4 and performance.ode_step_counts[-1] == 4096
    assert len(performance.rk45_rtols) == 11
    assert performance.knn_train_sizes == (500, 1000, 2000, 4000, 8000, 16000)
    assert performance.lsq_degrees == tuple(range(1, 13))


@pytest.mark.parametrize(
    "key, value, error",
    [
        ("repeats", 0, ValueError),
        ("warmup", -1, ValueError),
        ("min_time_per_repeat_s", 0.0, ValueError),
        ("rk45_rtols", [1e-3, -1e-6], ValueError),
        ("knn_k", 100000, ValueError),
        ("lsq_degrees", [0, 1], ValueError),
    ],
)
def test_invalid_performance_values_are_rejected(key, value, error):
    # Invalid performance settings are rejected.
    raw = valid_raw_config()
    raw["performance"][key] = value
    with pytest.raises(error):
        config_from_dict(raw)


def test_config_is_read_only():
    # The configuration is frozen: no part of the code can change it after validation.
    config = config_from_dict(valid_raw_config())
    with pytest.raises(AttributeError):
        config.random_seed = 1


# ---------------------------------------------------------------------------
# Invalid configurations
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "section, key, value, error",
    [
        (None, "random_seed", "42", TypeError),
        (None, "random_seed", True, TypeError),
        (None, "random_seed", -1, ValueError),
        ("data", "session", "Q", ValueError),
        ("data", "allocation_file", "", ValueError),
        ("fastf1", "cache_dir", "", ValueError),
        ("openf1", "request_delay_s", -0.1, ValueError),
        ("openf1", "max_retries", 0, ValueError),
        ("openf1", "max_retries", 2.5, TypeError),
        ("data", "teams", [], ValueError),
        ("data", "teams", "Red Bull Racing", TypeError),
        ("data", "pirelli_compounds", ["HARD"], ValueError),
        ("data", "pirelli_compounds", ["C7"], ValueError),
        ("data", "pirelli_compounds", None, ValueError),
        ("data", "races", [], ValueError),
        ("race", "total_laps_override", 1, ValueError),
        ("race", "total_laps_override", 57.5, TypeError),
        ("fuel", "k_fuel", -0.01, ValueError),
        ("fuel", "k_fuel", "0.03", TypeError),
        ("fuel", "k_fuel", float("nan"), ValueError),
        ("pit", "pit_loss_override", 0, ValueError),
        ("cleaning", "outlier_k", -3, ValueError),
        ("cleaning", "min_stint_laps", 0, ValueError),
    ],
)
def test_invalid_values_are_rejected(section, key, value, error):
    # Each invalid value is rejected with the expected error type.
    with pytest.raises(error):
        config_from_dict(with_change(section, key, value))


@pytest.mark.parametrize(
    "race, error",
    [
        ({"year": 2017, "event": "Bahrain Grand Prix", "role": "train", "source": "fastf1"}, ValueError),
        ({"year": 3000, "event": "Bahrain Grand Prix", "role": "train", "source": "openf1"}, ValueError),
        ({"year": "2023", "event": "Bahrain Grand Prix", "role": "train", "source": "openf1"}, TypeError),
        ({"year": 2022, "event": "", "role": "train", "source": "fastf1"}, ValueError),
        ({"year": 2022, "event": "Bahrain Grand Prix", "role": "validation", "source": "fastf1"}, ValueError),
        ({"year": 2022, "event": "Bahrain Grand Prix", "role": "train"}, ValueError),
        ({"year": 2022, "event": "Bahrain Grand Prix", "role": "train", "source": "ergast"}, ValueError),
        # OpenF1 has no free data before 2023
        ({"year": 2022, "event": "Bahrain Grand Prix", "role": "train", "source": "openf1"}, ValueError),
        ("2022 Bahrain", TypeError),
    ],
)
def test_invalid_race_entries_are_rejected(race, error):
    # Malformed race entries are rejected.
    raw = valid_raw_config()
    raw["data"]["races"].append(race)
    with pytest.raises(error):
        config_from_dict(raw)


def test_duplicate_race_is_rejected():
    # The same race listed twice (even in different case) could leak into training and test.
    raw = valid_raw_config()
    raw["data"]["races"].append(
        {"year": 2022, "event": "hungarian grand prix", "role": "test", "source": "fastf1"}
    )
    with pytest.raises(ValueError, match="more than once"):
        config_from_dict(raw)


@pytest.mark.parametrize("missing_role", ["train", "test"])
def test_needs_both_train_and_test_races(missing_role):
    # Both a training race and a test race are required.
    raw = valid_raw_config()
    raw["data"]["races"] = [r for r in raw["data"]["races"] if r["role"] != missing_role]
    with pytest.raises(ValueError, match=missing_role):
        config_from_dict(raw)


def test_missing_section_is_rejected():
    # A missing section is reported by name.
    raw = valid_raw_config()
    del raw["fuel"]
    with pytest.raises(ValueError, match="fuel"):
        config_from_dict(raw)


def test_misspelt_key_is_rejected():
    # A misspelt key is caught (the required key is reported as missing).
    raw = valid_raw_config()
    raw["fuel"] = {"k_feul": None}
    with pytest.raises(ValueError, match="k_fuel"):
        config_from_dict(raw)


def test_load_config_missing_file(tmp_path):
    # A missing config file gives FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_invalid_yaml(tmp_path):
    # Broken YAML gives a clear error rather than a parser traceback.
    bad = tmp_path / "bad.yaml"
    bad.write_text("data: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_config(bad)
