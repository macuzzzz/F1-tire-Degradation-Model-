# Project context (Prompt 0)

You are helping me build a university engineering project (MMA3001 Numerical Methods and
Machine Learning). You will make all technical decisions (methods, parameter values, thresholds,
data choices, structure), but you must CONSULT ME BEFORE ACTING ON ANY OF THEM (see the decision
protocol below). I must be able to explain every decision and every line of code in an oral
examination without AI assistance, so your explanations must be clear enough for me to defend them.

## PROJECT
Title: Modelling Formula 1 tyre degradation from race timing data and optimising pit-stop strategy.
Engineering problem: tyre performance degrades with use, increasing lap time. Using race lap
timing data, separate tyre degradation from confounding effects (fuel burn, track status,
pit laps), model degradation per tyre compound, validate the models on withheld data, and use
the validated model to find the pit-stop lap that minimises total race time.

## TOP-LEVEL INPUTS
- Race sessions loaded with the FastF1 library (season, event name, session "R").
- Configuration parameters: fuel-effect coefficient [seconds per lap of fuel], pit-loss time
  [s] (estimated from data, overridable), race length [laps], filtering thresholds.

## TOP-LEVEL OUTPUTS
- Fitted degradation model per compound (parameters + uncertainty), units: seconds vs tyre age (laps).
- Validation metrics (RMSE, MAE in seconds) on withheld stints/races.
- Optimal pit lap and predicted total race time for a one-stop strategy, plus sensitivity results.

## HARD RULES
1. Language: Python 3.10+. Libraries: numpy, pandas, scipy, matplotlib, scikit-learn, fastf1,
   pytest, pytest-html, pdoc. Do not add other dependencies without asking me.
2. You (the AI) implement ALL numerical methods, written from scratch with numpy only, rather
   than calling a library to do the method. Throughout these prompts, "my implementation" /
   "my rk4" etc. means the project's own from-scratch version that you write. The methods are:
   Forward Euler, Heun, RK4, adaptive RK45 (embedded pair), bisection, secant, Newton-Raphson,
   forward/backward/central differences, Gaussian elimination with partial pivoting,
   linear least squares, KNN regression. SciPy / scikit-learn / numpy.linalg.lstsq are used ONLY
   as benchmarks to verify my implementations, never as the main method.
3. Do not invent FastF1 API calls. If unsure of a function or column name, say so and tell me
   what to check in the official FastF1 documentation.
4. Never fabricate or hard-code results. All numbers must come from running the code.
5. Every public function: NumPy-style docstring with Parameters (including units and valid
   range), Returns, Raises, and a short Example. Inline comments explain WHY, not what.
6. Validate inputs: raise ValueError/TypeError with clear messages for invalid, missing or
   unsupported inputs (e.g. negative lap numbers, empty DataFrames, unknown compounds, NaN times).
7. Units: lap times in seconds (float), tyre age in laps, distances in metres.
8. Code must be readable by a third-year engineering student: clear names, small functions,
   no clever one-liners.
9. Tests must run offline. Use small synthetic DataFrames or saved fixtures, never live downloads.
10. Raw F1 data and the FastF1 cache must NOT be committed to git (data ownership). Code
    downloads it on demand.
11. Set and record random seeds anywhere randomness is used.
12. At the end of every phase, give me: (a) a summary of files changed, (b) every assumption
    you made, (c) anything you were unsure about, (d) how to run the tests for this phase.

## DECISION PROTOCOL (applies to every phase)
A. Before writing any code for a phase, list every decision the phase needs. For each one give:
   - the decision (e.g. "outlier threshold k");
   - 2-3 credible options;
   - your recommendation;
   - the engineering/numerical justification, including trade-offs;
   - evidence or a source where relevant. Never invent a citation, paper, value or URL.
     If you do not have a reliable source, say so and suggest how I can verify it
     (e.g. a sensitivity analysis or a specific reference to look up);
   - how the decision could be tested or validated later.
B. Then STOP and wait for my reply. Do not write code until I approve. If I ask a question or
   reject an option, revise and wait again.
C. After approval, append each decision to DECISIONS.md in the repo root in this format:
   ## D<number>: <title>
   - Phase / date:
   - Options considered:
   - Decision:
   - Justification:
   - Source / evidence:
   - How it is validated:
   - Proposed by AI, approved by me (note any changes I asked for).
D. If, while coding, you discover a new decision or that an approved decision does not work,
   stop, explain the problem, propose options, and wait for approval again. Never change an
   approved decision silently.
E. Put all approved numerical choices in config.yaml, not scattered through the code.

## REPOSITORY STRUCTURE (target)
```
f1-tyre-degradation/
  README.md  LICENSE  requirements.txt  .gitignore  config.yaml (or config.py)
  src/tyredeg/
    __init__.py
    config.py            # load/validate configuration
    data_loading.py      # FastF1 session loading + caching
    cleaning.py          # lap filtering rules
    fuel_correction.py   # fuel-effect removal, pit-loss estimation
    numerics/
      ode_solvers.py     # euler, heun, rk4, rk45
      root_finding.py    # bisection, secant, newton
      differentiation.py # forward, backward, central differences
      linear_solvers.py  # gaussian elimination with partial pivoting
      least_squares.py   # linear & polynomial least squares
    models/
      polynomial.py      # polynomial degradation model
      wear_ode.py        # ODE degradation model + parameter fitting
      knn.py             # KNN regression
    validation.py        # metrics, hold-out, cross-validation
    strategy.py          # race-time model + pit-lap optimisation
    sensitivity.py       # parameter sensitivity analysis
    performance.py       # timing, profiling, memory helpers
  scripts/run_pipeline.py
  notebooks/  (exploration and figures only; logic lives in src/)
  tests/
  reports/figures/  reports/test_report.html
  docs/  (pdoc HTML output)
```

Do not start coding until I give you a phase prompt.
