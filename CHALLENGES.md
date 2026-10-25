# Challenges and setbacks

Problems met while building the project, logged **as they happened**
(starting in Phase 6), including failed attempts. Earlier phases' problems
are recorded in DECISIONS.md and the phase summaries.

## C1: Compound base pace cannot be read from the per-compound models
- Phase / date: Phase 6 / 2026-10-24
- What happened: To compare a C3-first and a C4-first strategy, the race-time model needs the lap time of a NEW C3 and a NEW C4 tyre **for the same car**. Each compound's model has its own median stint offset (C3 85.02 s, C4 84.29 s), but those medians average over different mixes of cars, so their difference (−0.73 s) is not a compound effect.
- How it was detected: design review while writing `race_time`; the two medians differed by far more than any plausible compound difference.
- Root cause: D39 gives every stint its own offset, which absorbs car pace AND compound pace together. Fitting each compound separately never compares them on the same car.
- What was tried: (1) the two median offsets directly — rejected for the reason above.
  (2) Pairing: for each driver-race that used both compounds, the difference of its C4 and C3 stint offsets; median +0.114 s (C4 slower), n = 43.
- Resolution: in progress — see C2.
- Impact on results / lesson learned: per-stint offsets (D39) were right for estimating wear, but they hide between-compound pace; a strategy needs a separate, explicitly estimated compound delta.

## C2: Paired compound delta says the softer C4 is slower than the C3
- Phase / date: Phase 6 / 2026-10-24
- What happened: The paired estimate (C1, attempt 2) gives C4 − C3 = +0.114 s at equal tyre age (IQR −0.13 to +0.32 s; per race −0.03, −0.05, +0.30 s). A softer compound is normally faster, so the sign is suspicious.
- How it was detected: sanity check of the sign against tyre physics.
- Root cause: **stint order is confounded with compound.** 35 of the 43 driver-races ran C4 first. Splitting the pairs by order:

  | Order | Apparent C4 − C3 (median) | Driver-races |
  |---|---|---|
  | C4 first | +0.154 s | 35 |
  | C3 first | −0.315 s | 8 |

  In both orders the LATER stint looks faster, by about 0.23 s. Possible reasons are traffic in early stints (overtaking is hard at the Hungaroring), track evolution not fully captured by k_fuel, or drivers managing tyres early. The pooled median simply reflects that C4 usually came first.
- What was tried:
  1. Pooled paired median: +0.114 s. Rejected because it is order-biased.
  2. Same-compound check (two stints on one compound, later minus earlier): +0.090 s, n = 39. This points the OTHER way, so the order effect is not consistent and is partly selection (which drivers choose which order).
  3. **Order-balanced estimate:** the mean of the two order medians. A common order effect e cancels: (δ − e) and (δ + e) average to δ. Result: **C4 − C3 = −0.080 s (C4 faster).**
- Resolution: use the order-balanced δ = −0.080 s (D60). It is very uncertain: the plausible range is −0.32 to +0.15 s, the two order medians, which Phase 7 should vary.
- Impact on results / lesson learned: the compound pace delta is the least certain input of the strategy. It shifts the optimal pit lap by about δ / (a_C3 + a_C4) ≈ 0.7 laps per 0.08 s. Observational race data confounds compound with stint order; the order cannot be randomised, so it is balanced instead.

## C3: Docstring examples for strategy.py did not even load
- Phase / date: Phase 6 / 2026-10-24
- What happened: The doctest run of `strategy.py` stopped with "option directive on a line with no example".
- How it was detected: error message from `pytest --doctest-modules`.
- Root cause: I wrote placeholder examples as `>>> # call(...)   # doctest: +SKIP`. A line that is only a comment is not an example, so doctest rejects the directive. The examples that were placeholders needed real (skipped) calls.
- What was tried: replaced each placeholder with a real call marked `# doctest: +SKIP`.
- Resolution: resolved; 7 examples pass and 5 are skipped (they need fitted real-data models).
- Impact on results / lesson learned: none on results. Run the doctests straight after writing a module.

## C4: Strategy tests failed because the "unconstrained" fixture was constrained
- Phase / date: Phase 6 / 2026-10-24
- What happened: 5 of the 35 new strategy tests failed with "A 68-lap stint on C3 exceeds its limit of 60 laps", and the brute-force evaluation count was 51 instead of the expected 69.
- How it was detected: test failures (`pytest tests/test_strategy.py`).
- Root cause: a bug in the TEST, not the code. The analytic fixture gave both compounds a stint limit of 60 laps, but the tests evaluate pit laps 1 and 69 (stints of 69 laps) and expect all 69 pit laps to be feasible. The stint-limit check (D63) was correctly refusing them.
- What was tried: raised the fixture's default limit to N - 1 = 69 laps (truly unconstrained); the constraint tests still set their own, smaller limits.
- Resolution: resolved.
- Impact on results / lesson learned: none on results. It does confirm that the stint limit is enforced everywhere, including inside the two-stop enumeration.

## C5: The one-stop optimum is pinned to the stint limit (extrapolation boundary)
- Phase / date: Phase 6 / 2026-10-24
- What happened: For C3 -> C4, the unconstrained stationary point of the race time is at pit lap 32.89 (a 33-lap C3 stint, then 37 laps on C4). C4 is only supported by data up to 35 laps (D63), so the feasible window is pit laps 35–40, and the optimum sits exactly on its edge (35 + 35 laps).
- How it was detected: `constraint_active = True` from both continuous methods; the figure `phase6_race_time_vs_pit_lap.png` shows the root left of the feasible (blue) part.
- Root cause: the models would prefer a C4 stint slightly longer than the data covers. This is the extrapolation risk D63 was designed to block, and it does.
- What was tried: nothing to fix; the limit is working as intended. Checked that brute force, secant and Newton agree on lap 35 for both compound orders.
- Resolution: the reported one-stop optimum is constrained. Phase 7 should vary the stint limit and the compound delta (C2), since both move the optimum.
- Impact on results / lesson learned: the one-stop answer depends on D63 as much as on the models. Consequence for OI-6: the optimal C4 stint (35 laps) is above 25, so the planned KNN model-choice comparison is needed in Phase 7. Also, with stint limits the brute-force search has only 6 candidates, so the continuous relaxation is no cheaper here (9–18 race-time evaluations against 6).

## C6: Flat race-time curve and tied strategies
- Phase / date: Phase 6 / 2026-10-24
- What happened:
  1. The race time changes very little near the optimum. Its curvature is a_C3 + a_C4 ≈ 0.115 s/lap², so ±3 laps from the optimum costs only about 0.5 s.
  2. In the ranking, strategies that use the same set of stints in a different order tie EXACTLY (for example the three two-stops with stints {21 on C3, 24 on C4, 25 on C4}, all 5926.499 s).
  3. The best two-stop beats the best one-stop by only 4.3 s.
- How it was detected: the figure (shallow parabola) and the ranking table (identical times).
- Root cause:
  1. Linear degradation makes the race time a gentle parabola.
  2. The model contains nothing that depends on stint ORDER: every stint starts on new tyres, and the fuel effect is the same for all strategies. Reordering stints therefore cannot change the time.
- What was tried: verified the tie analytically (`test_compound_order_is_symmetric`).
- Resolution: unresolved by design. The ranking reports ties as ties; the order choice must rely on factors the model does not have (track position, traffic: see the factor review and C2).
- Impact on results / lesson learned: the optimal pit lap is weakly determined. Small input changes can shift it by several laps for very little time, and a 4.3 s one-vs-two-stop margin is smaller than the uncertainty in pit loss (IQR 19.8–22.3 s) times the number of stops. Phase 7 must quantify this before any recommendation is made.

## C7: The sensitivity run crashed: under a stricter stint-limit rule no one-stop race is feasible
- Phase / date: Phase 7 / 2026-10-24
- What happened: the first run of `scripts/sensitivity_analysis.py` stopped with "No feasible one-stop race C3->C4 within the stint limits" during the one-at-a-time loop.
- How it was detected: error message (traceback from `optimise_continuous`).
- Root cause: the variation "stint-limit rule >= 10 laps" (D63 alternative) gives C3 at most 36 laps and C4 at most 31 laps, only 67 laps together, fewer than the 70-lap race. The data then support no one-stop strategy at all. My `Scenario.evaluate` assumed a one-stop was always feasible. Also, it computed the UNCONSTRAINED optimum L* through `optimise_continuous`, which refuses to run without a feasible window, even though L* does not depend on the limits.
- What was tried: (fix below).
- Resolution: in `Scenario.evaluate`:
  1. L* is computed with the stint limits relaxed to N − 1, matching its definition as the unconstrained optimum.
  2. When no one-stop is feasible, the one-stop outputs are NaN and the best strategy is reported as "two stops (one stop infeasible)".
- Impact on results / lesson learned: a genuine finding, not just a bug. Whether a one-stop is possible at all depends on how strictly "enough data" is defined (D63). With >= 10 laps per tyre age, only multi-stop strategies stay within the data.

## C8: Derivatives with respect to k_fuel depend on the step size (non-smooth output)
- Phase / date: Phase 7 / 2026-10-24
- What happened: the race-time derivatives with respect to k_fuel changed with the perturbation:

  | Relative step | d(one-stop time)/dk | d(margin)/dk |
  |---|---|---|
  | 0.1 % | 1148.75 | 282.5 |
  | 1 % | 1158.16 | 273.1 |
  | 10 % | **745.0** | 301.7 |

  The derivatives with respect to pit loss and the wear rates agreed across all three steps, except at 10 %, where small differences appear.
- How it was detected: the step-size check (`reports/phase7_step_size_check.csv`), which runs every derivative with 0.1 %, 1 % and 10 % steps.
- Root cause: changing k_fuel REFITS everything (D56), and three inputs it feeds are medians:
  1. the pit-loss median (D58);
  2. the two order medians of the compound delta (D60);
  3. the medians themselves jump whenever two stints swap rank.

  So the output is only piecewise smooth in k. A 10 % step (±0.0046) also changes the integer optimum (stint lengths), a jump. In addition, the optimised times are only piecewise smooth by nature: they come from an integer argmin. Only the continuous L* is smooth, and its derivative agrees across steps (99.90 / 99.91 / 100.55).
- What was tried: the default 1 % step (D68), compared with 0.1 % and 10 %.
- Resolution: partly resolved. The k_fuel derivatives of the race times are reported as INDICATIVE only (about ±3 % between the 0.1 % and 1 % steps). For k_fuel the one-at-a-time range (0.015–0.070) is the primary result. For pit loss and the wear rates the 1 % derivatives are reliable, and they match exact values: d(one-stop)/d(C3 rate) = 630 = 35·36/2, the sum of tyre ages over the 35-lap stint; d(margin)/d(pit loss) = −1.
- Impact on results / lesson learned: central differences need a smooth function; medians and integer optimisation are not smooth. The step-size check was essential: without it the 10 % value (745) could have been reported.

## C9: The integer pit lap barely responds to any input (pinned by D63)
- Phase / date: Phase 7 / 2026-10-24
- What happened: the optimal integer pit lap (C3 first) stays at 35–36 laps in every variation except two. The ">= 3 laps" stint rule gives 33; the ">= 10 laps" rule makes any one-stop infeasible (C7). This holds even though the unconstrained optimum L* moves from 28.2 to 36.0 laps.
- How it was detected: the one-at-a-time table and the pit-lap tornado.
- Root cause: an earlier decision. The stint limit (C4 at most 35 laps, D63) puts the feasible window at pit laps 35–40, while L* is mostly below 35, so the constrained optimum is pinned at the window edge (as in C5). The integer output also cannot change by less than one lap (D69).
- What was tried: analysing L* (smooth, unconstrained) instead, as planned in D69.
- Resolution: by design. L* carries the sensitivity of WHERE the optimum would be; the integer pit lap mainly shows the stint limit.
- Impact on results / lesson learned: the recommended pit lap is determined more by the data-coverage rule than by the degradation physics. That should be said clearly in the report.

## C10: Tornado plot title cut off
- Phase / date: Phase 7 / 2026-10-24
- What happened: the title of `phase7_tornado_margin.png` ran past the right edge ("... two stops fast").
- How it was detected: visual check of the figure.
- Root cause: the output description was too long for one line at that figure width.
- What was tried:
  1. A `sed` substitution to insert "\n". It wrote a REAL line break into the f-string, and the script then failed with a syntax error (exit code 1; the old figures remained).
  2. A proper edit using string concatenation with "\n".
- Resolution: resolved by attempt 2; figures regenerated (the numbers are unchanged, since the run is deterministic).
- Impact on results / lesson learned: none on results. Look at the figures, and do not edit code with shell substitutions that interpret escape sequences.

## C11: My hand count of the RK45 FLOPs was off by one
- Phase / date: Phase 8 / 2026-10-24
- What happened: the docstring example of `rk45_attempt_flops` expected 104 FLOPs per attempted Dormand-Prince step, but the function returned 105.
- How it was detected: doctest failure.
- Root cause: my mental count, not the code. Recounting from the Butcher tableau gives 105:

  | Item | FLOPs |
  |---|---|
  | Stages (2m + 5 each, m = 1, 2, 3, 4, 5, 5) | 70 |
  | 5th-order solution | 11 |
  | Error estimate | 12 |
  | Error norm and step update | 12 |
  | **Total** | **105** |

  I had miscounted a stage. The function counts the non-zero coefficients directly from the tableau, so it cannot make this mistake.
- What was tried: recounted by hand (table above).
- Resolution: the example now shows 105, and the worked count is written into the docstring.
- Impact on results / lesson learned: none on results (the function was right). Never type an expected value that was not computed or carefully derived.

## C12: Timings of very short functions were dominated by noise
- Phase / date: Phase 8 / 2026-10-24
- What happened: in the first ODE benchmark run, functions taking well under a millisecond had a standard deviation comparable to their mean. For example, Euler with 4 steps had mean 44 µs and std 40 µs.

  | Run length | Std ÷ mean, median | Worst |
  |---|---|---|
  | under 0.1 ms | **67 %** | **141 %** |
  | 0.1–1 ms | 15 % | 45 % |
  | 1–10 ms | 3 % | 25 % |
  | over 10 ms | 3 % | 9 % |

- How it was detected: sanity check of `time_std_s / time_mean_s` in `reports/phase8_ode.csv`.
- Root cause: timing ONE call of a 20–100 µs function is at the scale of operating-system scheduling jitter, cache effects and the time.perf_counter call overhead. One interruption changes the measurement by more than the function's own run time.
- What was tried: the original D74 method (1 warm-up, 7 repeats, one call per repeat). Reporting the minimum helps, but the mean and std stay unreliable.
- Resolution: `time_function` now CALIBRATES the number of calls per repeat. The warm-up run measures one call; each recorded repeat then runs the function enough times to last at least `min_time_s` (config: 0.01 s = 10 ms), and the time per call is total ÷ calls (the approach of Python's `timeit`). See the re-run result in C13.
- Impact on results / lesson learned: never trust the timing of one very short call. The first-run ODE and KNN timings are superseded by the re-run.

## C13: Result of the timing fix, and the noise that remains
- Phase / date: Phase 8 / 2026-10-24
- What happened: re-running the ODE and KNN benchmarks with calibrated calls per repeat (C12) reduced the noise a lot, but not to zero:

  | Run length | Std ÷ mean before | Std ÷ mean after |
  |---|---|---|
  | under 0.1 ms | median 67 % (worst 141 %) | median **2.8 %** (worst 9 %) |
  | longer runs | median 3–15 % | median 5–6 % |

  One longer run still had a 32 % spread. The fitted KNN scaling exponents moved between the two runs: brute force 1.007 → 1.069, kd-tree 0.17 → 0.23.
- How it was detected: comparing `time_std_s / time_mean_s` and the exponents in the two runs of `phase8_ode.csv` / `phase8_knn.csv`.
- Root cause: other programs on the laptop (Windows background processes, the IDE) occasionally take CPU time during a measurement. A single fitted exponent from 6 noisy points also moves with that noise.
- What was tried: calibration (C12). Closing other programs or pinning the process to one CPU core was not done (not reproducible for a reader).
- Resolution: partly resolved. Tables report mean, std AND minimum; figures use the minimum, which is least affected by interruptions. Scaling exponents are stated to one decimal place only (about 1.0 for brute force, about 0.2 for the kd-tree), and machine details are recorded in `phase8_machine.json`.
- Impact on results / lesson learned: timing on a shared laptop is reproducible to a few percent at best. Conclusions are drawn only from large differences (factors of 2 or more), never from small ones.

## C14: The profiler overstated how much the optimisation would gain
- Phase / date: Phase 8 / 2026-10-24
- What happened: under cProfile, `predict_held_out` took 67 % of the compute pipeline (2.36 of 3.53 s), so vectorising it promised a large gain:

  | | Under cProfile | Without the profiler (7 repeats) |
  |---|---|---|
  | Before | 3.59 s | 2.16 ± 0.04 s |
  | After | 2.25 s | **1.75 ± 0.02 s** |
  | Speed-up | 1.6× | **1.23×** |

- How it was detected: comparing the profiled times with the plain repeated timings in `reports/phase8_optimisation.csv`.
- Root cause: cProfile adds a fixed overhead to EVERY Python function call. The old stint-by-stint version made far more small calls (pandas constructors, per-stint model calls), so the profiler inflated its share. Also, vectorising removed per-call overhead but not the real work: KNN still computes every query-to-training distance (now 0.88 s in the "after" profile, the new top item), and the wear-ODE fits (0.66 s) were untouched.
- What was tried: nothing more. The brief asks for ONE improvement, and its before/after numbers are reported as measured.
- Resolution: the reported speed-up is the honest 1.23× (wall clock, no profiler). Results are identical: max |difference| in CV metrics 5.6e-16 and in strategy times 0.0, within the stated 1e-12 s tolerance (test `test_vectorised_prediction_equals_original_loop`).
- Impact on results / lesson learned: a profile shows WHERE time goes, but its percentages are biased towards code with many small calls. Always confirm a speed-up with plain timings.

## C15: Data-preparation time depends on the operating system's file cache
- Phase / date: Phase 8 / 2026-10-24
- What happened: my first measurement of loading and preparing the data from the FastF1/OpenF1 caches was 5.56 s for two calls (about 2.8 s each). Later runs, even the FIRST call in a fresh Python process, took 0.82–0.85 s.
- How it was detected: comparing the probe output with `phase8_optimisation.csv` and a dedicated fresh-process check (two processes × 3 calls: 0.81–0.85 s).
- Root cause: the cached files (FastF1 pickles, a requests-cache SQLite database, OpenF1 JSON) are read from disk the first time after they were last touched; afterwards the operating system keeps them in memory, so later reads are much faster. Network time is not involved: all data was cached.
- What was tried: timing repeated calls (warm). A truly cold measurement would require clearing the OS file cache, which is not practical or reproducible here.
- Resolution: unresolved by design. Report the warm time (0.85 ± 0.03 s per preparation) and state that a cold first read took about 2.8 s. Data preparation is excluded from the optimisation (D79).
- Impact on results / lesson learned: I/O timings are dominated by caching outside the program's control; they cannot be compared with compute timings unless the cache state is stated.

## C16: My verification run overwrote the frozen model selection (test-firewall gap)
- Phase / date: Phase 8 / 2026-10-24
- What happened: to confirm that the Phase 8 optimisation did not change the Phase 5 results on real data, I re-ran `compare_models.py --stage cv`. That run rewrote `reports/model_selection.json` with a new timestamp (12:42:37 instead of 11:40:30) and a commit made AFTER the test evaluation, which would have destroyed the evidence that the selection was fixed before the 2025 test (D55). It also rewrote `phase5_cv_folds.csv` and `phase5_cv_summary.csv`.
- How it was detected: `git status` listed the three Phase 5 files as modified; `git diff` showed the new timestamp and commit.
- Root cause: a gap in D55. The test stage refused to repeat, but nothing stopped the CV stage from overwriting the selection once the test had been run. My own action exposed it.
- What was tried:
  1. Compared the overwritten files with the committed ones: the selection was the same, and the numbers differed by at most 6.1e-16. This was a useful side result, confirming D80's equivalence on real data.
  2. `git checkout` of the three files to restore the committed versions (verified: timestamp 11:40:30, commit 7f7d6eb).
  3. Added `guard_cv_rerun`: the CV stage now REFUSES when test results exist, unless `--force` is given. Checked: the stage now stops with a FirewallError and leaves the files untouched.
- Resolution: resolved; files restored, guard added, test `test_cv_rerun_refused_after_the_test_unless_forced`.
- Impact on results / lesson learned: no results changed (restored from git). Firewalls must protect every artifact, not only the test step. And never "just re-run" a stage whose outputs are frozen evidence; check first whether it writes them.

## C17: Local file paths (with my user name) leaked into committed profile reports
- Phase / date: Phase 9 / 2026-10-24
- What happened: `reports/phase8_profile_before.csv` and `phase8_profile_after.csv`, committed in Phase 8 (c01bd56), contained absolute paths such as `C:/Users/<me>/Documents/.../scripts/benchmark.py`, exposing the local user name and folder layout. The first `reports/pipeline.log` also contained them (FastF1 cache path).
- How it was detected: an automated security review of the Phase 8 commit flagged `profile_function` in `performance.py`; a search of `reports/` then found the paths in both profile CSVs and in the new pipeline log.
- Root cause: `profile_function` shortened paths only for installed libraries (`site-packages/`) and `src/`; files elsewhere (the benchmark script itself) kept their absolute path. The logger writes absolute cache paths, which is harmless on screen but not in a committed file.
- What was tried / resolution:
  1. Added `short_path`: paths relative to the repository root, relative to `site-packages`, or else the file name only (doctested).
  2. Cleaned the `function` column of both existing CSVs in place, WITHOUT re-running the benchmark, so the timings cited in D80 stay valid.
  3. Added `reports/pipeline.log` to `.gitignore` (run-specific).

  Verified: no local paths remain in `reports/`.
- Impact on results / lesson learned: no numerical results changed. **The old paths remain in the git history of commit c01bd56**; removing them would require rewriting history, which is destructive and is left to my decision (the repository has not been pushed anywhere). Check generated artefacts for machine-specific information before committing them.

## C18: Pipeline output differed from the committed Phase 5 CSVs in the last digit
- Phase / date: Phase 9 / 2026-10-24
- What happened: the first end-to-end pipeline run rewrote `reports/phase5_cv_folds.csv` and `phase5_cv_summary.csv` with slightly different numbers than the committed (Phase 5) versions.
- How it was detected: `git status` after the first pipeline run, then a numeric comparison: max |difference| 6.1e-16 (folds) and 2.2e-16 (summary). All acceptance, selection and text columns are identical.
- Root cause: the committed files were produced by the original stint-by-stint `predict_held_out_loop`; the pipeline uses the Phase 8 vectorised version, which sums the anchor laps with `numpy.bincount` in a different order. That changes the last binary digit of some means. It is the same effect D80 measured.
- What was tried: (1) a second pipeline run: its own reproducibility check found **all 40 result files byte-identical** to the first run, so run-to-run reproducibility holds; (2) checked that the frozen `model_selection.json` was only VERIFIED, not rewritten (unchanged: 11:40:30 UTC, commit 7f7d6eb).
- Resolution: the regenerated Phase 5 CSVs are committed in Phase 9, so the repository matches what the current code produces. The frozen selection and the test results are unchanged.
- Impact on results / lesson learned: no conclusion changes (differences around 1e-16). Byte-identical reproducibility holds for the same code; a faster implementation can change round-off, so "the same results" must always come with a tolerance.

## C19: The generated documentation published my local path too
- Phase / date: Phase 9 / 2026-10-24
- What happened: right after fixing C17, the first pdoc build of the HTML docs contained my absolute path in `docs/tyredeg/performance.html` and `docs/search.js`.
- How it was detected: searching the generated `docs/` folder for the user name after the build (a check added because of C17).
- Root cause: my C17 fix itself. It introduced a public module constant `REPO_ROOT = Path(__file__).resolve().parents[2]`, and pdoc documents the VALUE of public module variables, which here is an absolute local path.
- What was tried: renamed it `_REPO_ROOT` (pdoc does not document private names); rebuilt the docs; re-ran the doctests.
- Resolution: resolved; no local paths in `docs/` or `reports/`.
- Impact on results / lesson learned: none on results. A fix can create the same leak elsewhere: re-check every generated artefact (reports AND docs) after the change.

## C20: The HTML test report contained my local path in every skipped doctest
- Phase / date: Phase 9 / 2026-10-25
- What happened: the first `reports/test_report.html` (807 passed, 42 skipped) contained my absolute path 42 times.
- How it was detected: searching the generated report and the coverage HTML for the user name (the check introduced after C17/C19).
- Root cause: the 42 skips are doctest examples marked `+SKIP` (they need downloaded race data). pytest stores the location of each skip as an absolute path, here to `_pytest/doctest.py` inside `.venv`, and pytest-html writes it into the log of each skipped row. The coverage HTML was clean (it uses paths relative to the repository).
- What was tried: a root `conftest.py` with a `pytest_runtest_makereport` hook that shortens the skip location to the part after `site-packages/` before the report is written.
- Resolution: resolved; 0 occurrences in `reports/test_report.html` and `reports/coverage/` after the re-run. The coverage HTML (3 MB, regenerable) and the `.coverage` data file are gitignored; the test report is committed.
- Impact on results / lesson learned: none on results (test outcomes unchanged). Third leak of the same kind (C17, C19, C20): every tool that writes a file (profiler, pdoc, pytest-html) can embed absolute paths, so the search for the user name must be run on every new generated artefact before committing.

## C21: The first pipeline cleaning report showed 0 laps in its "input" row
- Phase / date: Phase 9 / 2026-10-25
- What happened: `reports/pipeline_cleaning_report.csv` from my first `run_pipeline.py` listed `input, 0, 0, 0, 0`, so the table did not show how many laps each race started with. The function also prepared every race twice.
- How it was detected: reading the CSV while writing the D82 entry.
- Root cause: my code took the `removed` column of the cleaning report for every row, and the `input` row has `removed = 0` by definition (its `remaining` column holds the lap count).
- What was tried: `stage_data` now builds each race's column as laps loaded (`remaining` of the `input` row), then laps removed per rule, then clean laps kept. Each race is prepared once.
- Resolution: resolved. The rows now balance, e.g. 2022: 1383 loaded − 371 removed = 1012 kept. The pipeline's hash check flagged the changed file as designed (D83).
- Impact on results / lesson learned: none on the model results; only the report format changed. Check that a summary table adds up before writing about it.

## C22: Hard rule 5 (complete NumPy docstrings) was not met for 126 public objects
- Phase / date: Phase 9 / 2026-10-25
- What happened: the review pass (D86) found that 126 of 214 public functions, methods and classes lack at least one required section (Raises 65, Example 63, Parameters 53, Returns 48, one with no docstring). 30 functions contain no input check; 18 of them (12 functions plus the six cleaning masks) are real gaps, where bad input gives an obscure error or a silently wrong result.
- How it was detected: `scripts/review_api.py`, written for the Phase 9 review.
- Root cause: from Phase 3 onward, short wrapper functions and small helpers (e.g. `heun`, `rk4`, the metric functions, the FLOP counters) were documented with a one-line summary pointing to the main function, and result classes got no Example. No automatic check enforced rule 5 while the code was being written.
- What was tried: the gaps are listed in `reports/phase9_api_review.csv` and classified in D86. They were not fixed in Phase 9, because the brief asked for a list. Filling about 230 missing sections, each Example with verified output, is a separate change that should be reviewed on its own.
- Resolution: **resolved (2026-10-25, D86 amendment).**
  - Every flagged docstring was completed. Example outputs were produced by running the code and confirmed by the doctests; none was typed by hand except the `True` of one example, which the doctest checked.
  - The 18 functions now validate their inputs, with 49 new tests in `tests/test_input_validation.py`.
  - `review_api.py`: 213 objects, 0 incomplete docstrings. The 2 functions without checks (`is_green_track_status`, `short_path`) accept any input by design, and their docstrings say so.
  - Full run: 935 passed, 32 skipped, coverage 95 %.
  - Pipeline: every model, validation, strategy and sensitivity result is byte-identical; only `phase9_api_review.csv` changed.
- Impact on results / lesson learned: none on results, since the functions are tested. A project rule that is not checked automatically drifts; the review script should have existed from Phase 1.

## C23: A docstring contradicted the strategy decision on which races set the pit loss
- Phase / date: final review / 2026-10-25
- What happened: `estimate_pit_loss` said "Pass only training races, so the test race does not influence the value used for strategy optimisation", but since D56/D58 the strategy deliberately estimates the pit loss on 2023–2025, including the 2025 test race.
- How it was detected: reading the function while writing the leakage audit (D90).
- Root cause: the docstring was written in Phase 2, before the test, and was not updated when D58 changed the data window after the test.
- What was tried: checked whether this is leakage. It is not: the strategy is never scored against the test race, and the test evaluation used no pit loss. Audit check B9 records this.
- Resolution: resolved; the docstring now states both cases and points to D56/D58.
- Impact on results / lesson learned: none on results. When a decision changes, search the code and docs for statements of the old rule, not only the config.
