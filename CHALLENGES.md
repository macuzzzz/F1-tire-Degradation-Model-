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
