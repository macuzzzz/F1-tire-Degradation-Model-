# F1 tyre degradation and pit-stop strategy

MMA3001 (Numerical Methods and Machine Learning) project: model Formula 1 tyre
degradation from race lap-timing data, validate the models on a withheld race,
and use the validated model to choose the pit-stop strategy that minimises
total race time.

## The engineering problem

A tyre gets slower as it wears, so lap time rises with tyre age. In raw lap
times this effect is mixed with others: the car gets lighter as fuel burns
(faster laps), safety cars and yellow flags slow laps down, and laps into and out
of the pits include the pit-lane time. The project:

1. removes the confounding effects (lap filtering, fuel correction, pit laps);
2. fits a degradation model per Pirelli compound (lap-time increase vs tyre age);
3. validates the models on laps they were not fitted to (leave-one-race-out
   cross-validation on 2022–2024, a single final test on 2025);
4. builds a race-time model and finds the pit lap(s) that minimise total race
   time, then tests how sensitive that answer is to the inputs.

Scope (decisions D4, D6, D52, D56 in [DECISIONS.md](DECISIONS.md)): Hungarian
Grand Prix, all teams, Pirelli compounds C3 and C4, seasons 2022–2025. Car
performance (downforce, top speed, set-up) is not modelled; a separate base
lap time per stint absorbs car and driver pace (D39).

All numerical methods (Euler, Heun, RK4, adaptive RK45, bisection, secant,
Newton–Raphson, finite differences, Gaussian elimination with partial
pivoting, linear least squares, KNN regression) are written from scratch with
NumPy in `src/tyredeg/numerics/` and `src/tyredeg/models/`. SciPy and
scikit-learn are used only in tests and benchmarks, to verify them.

## Inputs and outputs

### Inputs (all in `config.yaml`, validated by `src/tyredeg/config.py`)

| Input | Key in config.yaml | Unit | Valid range (checked) | Value used |
|---|---|---|---|---|
| Races (season, event, train/test role, source) | `data.races` | – | year 2018 to the current year; source `fastf1` or `openf1` (OpenF1: 2023 onward); ≥ 1 train and ≥ 1 test race; no duplicates | Hungarian GP 2022–2024 (train), 2025 (test) |
| Session | `data.session` | – | `"R"` (race) only | `R` |
| Pirelli compounds modelled | `data.pirelli_compounds` | – | C0–C6 | C3, C4 |
| Fuel-effect coefficient | `fuel.k_fuel` | s per lap of fuel burned | ≥ 0 and within `[k_fuel_min, k_fuel_max]` | 0.046 (range 0.015–0.070) |
| Pit-loss time | `pit.pit_loss_override` | s | > 0, or `null` = estimate from data | `null` (estimated: median 20.89 s) |
| Race length | `race.total_laps_override` | laps | ≥ 2, or `null` = from the data | `null` (70 laps) |
| Outlier threshold | `cleaning.outlier_k` | robust standard deviations | > 0 | 3.0 |
| Minimum stint length | `cleaning.min_stint_laps` | laps | ≥ 1 | 10 |
| Numerical tolerances, model settings, strategy, sensitivity, benchmark settings | `numerics`, `models`, `validation`, `strategy`, `sensitivity`, `performance` | see comments in config.yaml | see `config.py` | see config.yaml |
| Random seed | `random_seed` | – | integer ≥ 0 | 42 |

Race data come from FastF1 (2022) and the OpenF1 API (2023–2025); see
"Data and licensing" below.

### Outputs (written to `reports/` and `reports/figures/`)

| Output | Unit | File |
|---|---|---|
| Cleaning report: laps removed by each rule, per race | laps | `pipeline_cleaning_report.csv` |
| Cross-validation metrics per model, fold and compound (RMSE, MAE, max error, bias, R²) | s (bias in s/lap) | `phase5_cv_folds.csv`, `phase5_cv_summary.csv` |
| Selected model per compound (frozen before the test) | – | `model_selection.json` |
| Test metrics on the 2025 race | s | `phase5_test_results.csv` |
| Fitted degradation parameters with bootstrap standard errors | s/lap | `phase6_inputs.csv` (strategy refit), console output of `compare_models.py` |
| Optimal pit lap(s) and predicted total race time per strategy | lap number, s | `phase6_strategy_ranking.csv`, `phase6_methods.csv` |
| Sensitivity: one-at-a-time results, coefficients, break-even values | s, laps, dimensionless | `phase7_*.csv` |
| Performance benchmarks (machine-dependent, not part of the pipeline) | s, bytes, FLOPs | `phase8_*.csv`, `phase8_machine.json` |
| Run manifest: config hash, git commit, SHA-256 of every result file | – | `pipeline_manifest.json` |

Headline results (from the files above, current config):

- Selected model: a straight line in tyre age for both compounds. C3 wear rate
  0.0597 s/lap, C4 0.0551 s/lap (2023–2025 refit).
- Test on 2025: RMSE 0.94 s (C3) and 1.04 s (C4), lower than the no-degradation
  baseline, but with a positive bias (+0.28 and +0.54 s/lap) because 2025
  tyres degraded less than in the training years. The bias criterion of
  0.10 s/lap was not met (DECISIONS.md, Phase 5 test record).
- Strategy (70 laps): best two-stop (C3 → C4 → C4, pit laps 21 and 45)
  5926.50 s, best one-stop (pit lap 35) 5930.83 s, a gap of 4.33 s.
- The two-stop advantage disappears if the fuel coefficient is below
  0.0333 s/lap or the pit loss is above 25.22 s (`phase7_break_even.csv`).

## Installation

Requires Python 3.10 or newer (developed on 3.13, Windows 11).

```bash
py -3.13 -m venv .venv                       # or: python3 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS: .venv/bin/python
```

`requirements.txt` pins the direct dependencies (D11);
`requirements-lock.txt` freezes the whole environment.

## Running

All commands are run from the repository root.

```bash
# Whole workflow: load -> clean -> fuel-correct -> fit -> validate -> test -> optimise -> sensitivity
.venv/Scripts/python scripts/run_pipeline.py

# A subset of stages (always run in pipeline order), another config, more logging
.venv/Scripts/python scripts/run_pipeline.py --stages strategy sensitivity
.venv/Scripts/python scripts/run_pipeline.py --config my_config.yaml --log-level DEBUG
```

- The first run downloads the race data into `cache/` (needs internet; OpenF1
  refuses free requests while a live F1 session is running). Later runs use
  the cache: 15–30 s on the development laptop (three runs measured; the laptop was also running other programs).
- The test race is evaluated **once**. After that, the `validate` stage only
  verifies that the cross-validation still selects the frozen models, and the
  `test` stage is skipped unless `--force-test` is given (every test run is
  logged in `reports/test_runs.log`; D55).
- Every run writes `reports/pipeline_manifest.json` and reports whether any
  result file changed since the previous run with the same config
  (reproducibility check, D83).
- The log is written to the console and to `reports/pipeline.log`
  (git-ignored, because it contains local paths).

Individual phases can also be run on their own: `scripts/numerics_study.py`
(Phase 3 method study), `scripts/compare_models.py --stage cv|test` (Phase 5),
`scripts/optimise_strategy.py` (Phase 6), `scripts/sensitivity_analysis.py`
(Phase 7), `scripts/benchmark.py` (Phase 8) and `scripts/review_api.py`
(Phase 9 docstring review).

## Tests

```bash
# Unit tests only (fast, offline)
.venv/Scripts/python -m pytest

# Full report: unit tests + doctests, HTML test report and coverage
.venv/Scripts/python -m pytest tests src/tyredeg --doctest-modules --html=reports/test_report.html --self-contained-html --cov=tyredeg --cov-report=term --cov-report=html:reports/coverage
```

The tests never download data: they use small synthetic DataFrames. Doctest
examples that need real race data are marked `+SKIP`. The HTML coverage
report (`reports/coverage/`) is regenerated by the command and not committed.

## Documentation

API documentation (HTML, generated from the NumPy-style docstrings):

```bash
.venv/Scripts/python -m pdoc src/tyredeg -o docs --docformat numpy
```

Open `docs/index.html` in a browser.

## Repository structure

```
config.yaml            all numerical choices (validated by src/tyredeg/config.py)
src/tyredeg/
  config.py            load and validate the configuration
  data_loading.py      FastF1 loading (2022)
  openf1_loading.py    OpenF1 client with on-disk cache (2023-2025)
  loading_common.py    unified laps table shared by both sources
  race_control.py      green-flag lap detection from race-control messages
  tyre_allocation.py   SOFT/MEDIUM/HARD -> Pirelli C-number per race
  cleaning.py          the eight lap-filtering rules
  fuel_correction.py   fuel-effect removal, pit-loss estimation
  preparation.py       load + fuel-correct + clean for a list of races
  numerics/            ode_solvers, root_finding, differentiation, linear_solvers, least_squares
  models/              polynomial, wear_ode, knn (+ common: stint offsets, bootstrap)
  validation.py        metrics, leave-one-race-out CV, model selection, test firewall
  strategy.py          race-time model and pit-stop optimisation
  sensitivity.py       one-at-a-time sensitivity, coefficients, tornado plots
  performance.py       timing, memory, FLOP counts, profiling
scripts/               runnable entry points (run_pipeline.py and one per phase)
tests/                 pytest unit tests (offline)
reference/             Pirelli compound allocation per race, with source URLs
reports/               result tables, figures, test report
docs/                  pdoc HTML documentation
notebooks/             exploration only (currently empty; all logic is in src/)
```

## Data and licensing

- Lap timing data are downloaded on demand through the
  [FastF1](https://docs.fastf1.dev/) library (2022, from its free data mirror)
  and the [OpenF1](https://openf1.org/) API (2023–2025). Since about
  15 October 2026, F1's own timing archive needs an F1 TV login and FastF1's
  free mirror only has 2021–2022, so only these free sources are used (D14,
  OI-1).
- The raw data and both caches (`cache/fastf1/`, `cache/openf1/`) are
  **not** in this repository (`.gitignore`). Formula 1 timing data belong to
  their rights holders; FastF1 and OpenF1 are unofficial community projects.
  Check their documentation for the current terms of use before using the data.
- `reference/pirelli_allocation.csv` was compiled for this project from the
  Pirelli and Formula1.com articles listed in its `source_url` column.
- The result tables in `reports/` contain only derived statistics.

## Limitations

- **One circuit, two compounds.** The model is fitted to the Hungaroring only.
  Degradation depends on track surface, layout and temperature, so the
  parameters do not transfer to other circuits.
- **Year-to-year change is the largest error.** The 2025 test race degraded
  less than every training race. The models were biased on the test
  (+0.28 / +0.54 s/lap), and on 2025 the selected line has a negative test R²
  (−0.04 for C3, −0.47 for C4), so it explains less variance than a constant
  per stint. The strategy result can change with the year (Phase 7).
- **Fuel coefficient.** `k_fuel` is a single value for all races (0.046 s/lap,
  estimated from the training data and close to a rule of thumb, D22), and it
  also absorbs track evolution (D22 restatement). The fitted wear rate depends on it
  one-for-one (d rate / d k_fuel = 1), and the two-stop decision flips below
  0.0333 s/lap.
- **Not modelled:** track temperature, weather, car performance and set-up,
  driver style, traffic and dirty air, tyre warm-up, safety-car timing, tyre
  set availability, and used tyres at the start of a stint. Base pace per stint
  absorbs car and driver differences only as a constant.
- **Stint-length limits** come from the data (C3 ≤ 40, C4 ≤ 35 laps with at
  least 5 laps observed at that age), and they bind for the one-stop strategy.
- **Few races.** Three training races give only three cross-validation folds,
  and one test race gives a noisy test metric.
- **Docstrings.** `scripts/review_api.py` lists public functions whose
  docstrings still lack a NumPy section (`reports/phase9_api_review.csv`).

The full list of challenges met during the project is in
[CHALLENGES.md](CHALLENGES.md), and the lessons are summarised in
[LESSONS_SUMMARY.md](LESSONS_SUMMARY.md).

## Decisions, challenges and lessons

- [DECISIONS.md](DECISIONS.md): every technical decision, with the options
  considered, the justification, the evidence and how it is validated.
- [CHALLENGES.md](CHALLENGES.md): problems met during the project, how they were
  found and how they were resolved.
- [LESSONS_SUMMARY.md](LESSONS_SUMMARY.md): the most important challenges,
  lessons and limitations in one page.

## Use of AI

> **To be completed by the student.** Placeholders:
>
> - Tool(s) used: [tool name and version]
> - What the AI was used for: [e.g. proposing options for each decision, writing code and tests, drafting documentation]
> - What I decided and checked myself: [e.g. approved or changed each decision in DECISIONS.md, reviewed the code, ran the tests]
> - How the results were verified: [e.g. tests against SciPy/scikit-learn benchmarks, hold-out test, reproducibility check]
> - Limitations of the AI assistance I noticed: [e.g. examples in CHALLENGES.md]

## Licence

Code: MIT licence, see [LICENSE](LICENSE). The licence does not cover the
Formula 1 data, which are not distributed with this repository.
