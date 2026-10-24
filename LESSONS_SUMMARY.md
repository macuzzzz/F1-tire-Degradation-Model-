# Lessons summary

Facts only, taken from [DECISIONS.md](DECISIONS.md) (D-numbers, OI-numbers)
and [CHALLENGES.md](CHALLENGES.md) (C-numbers), which hold the full evidence.
Challenges from Phases 1–5 were recorded in DECISIONS.md, because
CHALLENGES.md was started in Phase 6.

## 1. The most important challenges

### Data

| # | What happened | Consequence | Reference |
|---|---|---|---|
| 1 | From about 15 Oct 2026, F1's timing archive returns HTTP 401 without an F1 TV login. FastF1 3.8.3's free mirror only has 2021–2022. | Data from 2023–2025 come from the OpenF1 API instead, merged with FastF1 (2022) into one laps table. OpenF1 also blocks free access during live sessions, so every response is cached on disk. | OI-1, D14, D15, D16 |
| 2 | SOFT/MEDIUM/HARD are labels, not compounds: Pirelli's C-number behind each label changes per race and year. Bahrain was abandoned: Red Bull ran no HARD laps in 2022 and no MEDIUM laps in 2023 or 2024. | Data are selected by Pirelli compound through a sourced allocation table. Scope changed from Bahrain/HARD/Red Bull to Hungary/C3+C4/all teams. | D4 amendments, D6 amendment, D52, OI-2 |
| 3 | FastF1 fuzzy-matches event names: `get_session(2023, "Atlantis Grand Prix", "R")` returned the Australian GP with only a log warning. | The loader checks the resolved event name and raises an error on a mismatch. | D7 |
| 4 | The fuel coefficient estimated from the data (0.046 s/lap) contains track evolution as well as fuel, because both grow linearly with lap number. | The correction removes both. The fitted wear rate changes one-for-one with `k_fuel`, so `k_fuel` is a key sensitivity input. | D22, D22 restatement, D72 |

### Numerical methods

| # | What happened | Consequence | Reference |
|---|---|---|---|
| 5 | The root-finder stopping rule "step AND residual small" never terminates when the closest floats to the root still leave \|f\| > ftol (bisection and Newton raised `NotConvergedError` on a steep test function). | A round-off safeguard was added: also stop when \|step\| ≤ 4·eps·\|x\|. | D30 amendment, OI-4 |
| 6 | PyYAML reads `1.0e10` as a string. | Large numbers are written `1.0e+10`; `config.py` rejects the string. | D38 |
| 7 | Central-difference sensitivities with respect to `k_fuel` change with the step size (derivative of the one-stop race time: 1149 / 1158 / 745 at steps of 0.1 % / 1 % / 10 %), because the output passes through medians and an integer optimisation. | `k_fuel` derivatives are reported as indicative only. The step-size check is what caught it. | C8, D68 |

### Modelling and validation

| # | What happened | Consequence | Reference |
|---|---|---|---|
| 8 | On the 2025 test race, both selected models were biased (+0.28 s/lap C3, +0.54 s/lap C4) and failed the 0.10 s/lap criterion. 2025 wear was lower than in every training year (C3: 0.045 s/lap against 0.063–0.075), and 2025 C3 stints reached tyre age 55 laps against a training maximum of 41. | The year-to-year change is the dominant uncertainty. The strategy models were refitted on 2023–2025, and the year effect was added to the sensitivity analysis, where it can flip the strategy. | Phase 5 test record, OI-7, D56, D67 |
| 9 | Compound pace cannot be read from per-compound models, because per-stint offsets absorb it. The paired estimate is confounded with stint order (35 of 43 driver-races ran C4 first). | An order-balanced delta was used (−0.080 s, plausible range −0.32 to +0.15 s). It is the least certain strategy input. | C1, C2, D60 |
| 10 | The one-stop optimum is pinned to the data-coverage stint limit (C4 ≤ 35 laps). With a stricter rule (≥ 10 laps per tyre age) no one-stop race is feasible at all. | The recommended pit lap is set more by the data-coverage rule than by the degradation physics. | C5, C7, C9, D63 |
| 11 | The race-time curve is flat: several strategies tie, and the 4.33 s two-stop advantage is smaller than the pit-loss uncertainty (IQR 19.8–22.3 s) times the number of stops. | The break-even values are reported: `k_fuel` 0.0333 s/lap (inside its range) and pit loss 25.22 s. | C6, D73 |

### Process and reproducibility

| # | What happened | Consequence | Reference |
|---|---|---|---|
| 12 | A verification re-run of the CV stage overwrote the frozen `model_selection.json` after the test had been run. | Restored from git. A guard now refuses that re-run unless forced, and the pipeline only verifies the frozen selection. | C16, D55 amendment, D82 |
| 13 | Absolute local paths containing the user name leaked three times: into profile CSVs (cProfile), the API docs (pdoc publishing a module constant) and the HTML test report (pytest-html skip locations). | Each output was fixed and re-checked. The paths remain in the git history of commit c01bd56. | C17, C19, C20 |
| 14 | Expected values in doctests were typed from mental arithmetic and were wrong (for example an RK45 FLOP count of 104 instead of 105). | Expected values are now copied from real output. | C3, C11 |
| 15 | Timings of 20–100 µs functions were dominated by operating-system noise, and cProfile overstated the gain of the optimisation. | Each repeat is calibrated to run for at least 10 ms; the minimum time is reported; the speed-up was confirmed without the profiler (1.23×, identical results). | C12, C13, C14 |
| 16 | The vectorised CV changed the last binary digit of some Phase 5 metrics (≤ 6.1e-16). | Results are reproducible byte for byte with the same code; across implementations they agree within a stated tolerance (1e-12 s). | C18, D80 |
| 17 | A review script found that 126 of 214 public objects broke the project's own docstring rule, and 18 functions accepted bad input silently. No check had enforced the rule while the code was written. | All gaps were fixed, with 49 new tests; the script now reports 0 incomplete docstrings. | C22, D86 amendment |

## 2. Lessons

1. **Check the data source before planning around it.** Data access (#1), compound
   labels (#2) and team coverage changed the scope three times in Phase 1.
2. **Select by the physical quantity, not the label.** Pirelli C-numbers, not
   SOFT/MEDIUM/HARD (#2); the resolved event name, not the requested one (#3).
3. **A test set must be protected by code, not by intention.** The firewall had
   a gap until it guarded every frozen artefact (#12).
4. **Cross-validation within past years does not measure year-to-year change.**
   The CV error (RMSE 0.63 / 0.85 s) understated the test error (0.94 / 1.04 s),
   because the test year differed from all training years (#8).
5. **Confounding cannot be fixed by more fitting.** Fuel and track evolution (#4),
   and compound and stint order (#9), are confounded in observational race data.
   They can only be balanced, bounded or put into the sensitivity analysis.
6. **Constraints and data-coverage rules can dominate an optimum** (#10). Report
   which constraint is active, together with the optimum.
7. **Numerical derivatives need smooth functions.** Always check the step size
   (#7). Stopping rules need a round-off safeguard (#5).
8. **Never type an expected value that was not computed** (#14), and always state
   a tolerance when claiming that two implementations give "the same result" (#16).
9. **Measure performance carefully.** Repeat short timings, report the minimum,
   and confirm profiler gains with plain timings (#15).
10. **Every generated file is a potential leak.** Search outputs for
    machine-specific information before committing (#13).
11. **A rule that is not checked automatically drifts.** The docstring rule
    held only after a script checked it (#17).

## 3. Limitations of the final result

- One circuit (Hungaroring) and two compounds (C3, C4). The parameters do not
  transfer to other circuits.
- Four races in total: three cross-validation folds and a single test race.
- On the test race the selected linear models have a positive bias and a
  negative test R² (−0.04 C3, −0.47 C4). They still beat the no-degradation
  baseline on RMSE.
- One fuel coefficient for all races, which also contains track evolution; the
  strategy decision flips below 0.0333 s/lap.
- Not modelled: track temperature, weather, car performance and set-up, driver,
  traffic and dirty air, tyre warm-up, safety cars, tyre-set availability,
  used tyres at the start of a stint.
- The one-stop optimum is set by the stint-limit rule. The two-stop advantage
  (4.33 s) is small compared with the uncertainty in pit loss, compound delta
  and year-to-year wear.
