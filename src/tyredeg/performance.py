"""Timing, memory, FLOP-counting and profiling helpers (Phase 8, DECISIONS.md D74-D81).

Timing (D74)
------------
:func:`time_function` runs the function once as a warm-up (not recorded:
the first call pays for imports, memory allocation and CPU caches), then
``repeats`` more times with ``time.perf_counter`` (the highest-resolution
wall clock). ``gc.collect()`` runs before the timed calls so a garbage
collection left over from earlier work does not land inside a measurement.
The mean, standard deviation and minimum are reported; the minimum is the
least disturbed by other processes on the machine. :func:`machine_info`
records the machine and library versions so results can be reproduced.

Memory: :func:`peak_memory` uses ``tracemalloc``, which sees allocations
made by Python and by NumPy (NumPy reports its array buffers to tracemalloc).
Memory allocated inside compiled extensions that do not report it (parts of
scikit-learn's tree code) is NOT seen, so peaks for those are lower bounds.

FLOP convention (D76)
---------------------
One FLOP = one floating-point addition, subtraction, multiplication or
division. A special function (exp, sqrt, a power) is ALSO counted as one
operation, although in hardware it costs roughly 10-50 simple FLOPs; this
keeps the counts simple and the convention is stated wherever they are used.
Comparisons, array indexing and Python overhead are not counted.

The ODE solvers are counted per step for a SCALAR state y, with the cost of
one evaluation of f given separately (for the wear ODE f = a + b y it is
2 FLOPs: one multiplication and one addition).
"""

from __future__ import annotations

import cProfile
import gc
import io
import math
import os
import platform
import pstats
import statistics
import sys
import time
import tracemalloc
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tyredeg.numerics import ode_solvers

# Default timing settings, identical to the `performance` section of config.yaml (D74).
DEFAULT_REPEATS = 7
DEFAULT_WARMUP = 1
DEFAULT_MIN_TIME_S = 0.01

# Cost of one evaluation of the wear-ODE right-hand side f(n, d) = a + b d:
# one multiplication (b * d) and one addition (a + ...) = 2 FLOPs.
WEAR_RHS_FLOPS = 2


# ---------------------------------------------------------------------------
# Machine and timing
# ---------------------------------------------------------------------------
def machine_info():
    """Machine, Python and library versions, for reproducible timings.

    Returns
    -------
    dict

    Example
    -------
    >>> "python" in machine_info()
    True
    """
    import scipy
    import sklearn

    return {
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "sklearn": sklearn.__version__,
    }


@dataclass(frozen=True)
class TimingResult:
    """Repeated wall-clock timings of one function, PER CALL [s].

    Attributes
    ----------
    mean, std, minimum : float
        Over the recorded repeats (std uses n - 1; 0 for a single repeat).
    repeats : int
    values : tuple of float
        Every recorded time per call.
    calls_per_repeat : int
        How many times the function ran inside each recorded repeat.
    """

    mean: float
    std: float
    minimum: float
    repeats: int
    values: tuple
    calls_per_repeat: int = 1


def time_function(func, repeats=DEFAULT_REPEATS, warmup=DEFAULT_WARMUP, min_time_s=None):
    """Time ``func()`` with warm-up runs and repeats (D74).

    Parameters
    ----------
    func : callable
        Called with no arguments; its return value is ignored.
    repeats : int, optional
        Recorded repeats, >= 1. Default 7.
    warmup : int, optional
        Unrecorded runs before timing, >= 0. Default 1 (at least one is
        done when ``min_time_s`` is given, to calibrate).
    min_time_s : float or None, optional
        If given, each recorded repeat runs ``func`` as many times as needed
        to last at least this long, and the time PER CALL is reported. This
        keeps very short functions above the timer and scheduling noise
        (C12; config: 0.01 s). None = one call per repeat.

    Returns
    -------
    TimingResult

    Raises
    ------
    TypeError
        If ``func`` is not callable.
    ValueError
        For repeats < 1, warmup < 0 or min_time_s <= 0.

    Example
    -------
    >>> result = time_function(lambda: sum(range(1000)), repeats=3, min_time_s=0.005)
    >>> result.repeats, result.minimum > 0, result.calls_per_repeat > 1
    (3, True, True)
    """
    if not callable(func):
        raise TypeError("func must be callable.")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError(f"repeats must be an integer >= 1, got {repeats!r}.")
    if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < 0:
        raise ValueError(f"warmup must be an integer >= 0, got {warmup!r}.")
    if min_time_s is not None and not min_time_s > 0:
        raise ValueError(f"min_time_s must be > 0, got {min_time_s!r}.")

    calls = 1
    single = None
    for _ in range(max(warmup, 1 if min_time_s is not None else 0)):
        start = time.perf_counter()
        func()
        single = time.perf_counter() - start
    if min_time_s is not None:
        # Enough calls that one repeat lasts at least min_time_s.
        calls = max(1, math.ceil(min_time_s / max(single, 1e-9)))
    gc.collect()
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(calls):
            func()
        values.append((time.perf_counter() - start) / calls)
    std = statistics.stdev(values) if repeats > 1 else 0.0
    return TimingResult(statistics.mean(values), std, min(values), repeats, tuple(values), calls)


def peak_memory(func):
    """Run ``func()`` once and return (its result, peak traced memory in bytes).

    Measures memory allocated DURING the call (tracemalloc starts fresh), as
    seen by tracemalloc; see the module docstring for what it cannot see.

    Raises
    ------
    TypeError
        If ``func`` is not callable.

    Example
    -------
    >>> _, peak = peak_memory(lambda: np.ones(1_000_000))   # 8 MB of float64
    >>> peak >= 8_000_000
    True
    """
    if not callable(func):
        raise TypeError("func must be callable.")
    gc.collect()
    tracemalloc.start()
    try:
        result = func()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, int(peak)


# ---------------------------------------------------------------------------
# FLOP counts of the ODE solvers (D76)
# ---------------------------------------------------------------------------
def euler_step_flops(f_flops):
    """FLOPs of one forward-Euler step for a scalar state.

    k1 = f(t, y)                 f_flops
    y_new = y + h * k1           1 multiplication + 1 addition = 2
    t_new = t + h                1 addition                    = 1
    total = f_flops + 3

    Example
    -------
    >>> euler_step_flops(WEAR_RHS_FLOPS)
    5
    """
    return f_flops + 3


def heun_step_flops(f_flops):
    """FLOPs of one Heun step for a scalar state.

    k1 = f(t, y)                       f_flops
    y_pred = y + h * k1                2
    t + h                              1
    k2 = f(t + h, y_pred)              f_flops
    y_new = y + h * (k1 + k2) / 2      k1 + k2 (1), h * (...) (1), / 2 (1), y + (1) = 4
    t_new = t + h                      (t + h reused)               0
    total = 2 f_flops + 7

    Example
    -------
    >>> heun_step_flops(WEAR_RHS_FLOPS)
    11
    """
    return 2 * f_flops + 7


def rk4_step_flops(f_flops):
    """FLOPs of one classical RK4 step for a scalar state.

    h / 2                              1   (computed once, reused)
    t + h / 2                          1   (reused for k2 and k3)
    t + h                              1   (reused for k4 and t_new)
    k1 = f(t, y)                       f_flops
    k2 = f(t + h/2, y + h/2 * k1)      f_flops + 2   (mul + add)
    k3 = f(t + h/2, y + h/2 * k2)      f_flops + 2
    k4 = f(t + h, y + h * k3)          f_flops + 2
    k1 + 2 k2 + 2 k3 + k4              2 multiplications + 3 additions = 5
    h / 6 * (...) and y + (...)        h / 6 (1), * (1), + (1)          = 3
    total = 4 f_flops + 3 + 6 + 5 + 3 = 4 f_flops + 17

    Example
    -------
    >>> rk4_step_flops(WEAR_RHS_FLOPS)
    25
    """
    return 4 * f_flops + 17


def _combination_flops(weights):
    """FLOPs of h * sum_j w_j k_j for the non-zero weights: m mults, m - 1 adds, 1 mult by h."""
    m = int(np.count_nonzero(weights))
    return m + (m - 1) + 1 if m else 0


def rk45_attempt_flops(f_flops):
    """FLOPs of one ATTEMPTED Dormand-Prince step (accepted or rejected), scalar state.

    Counted from the Butcher tableau in :mod:`tyredeg.numerics.ode_solvers`:

    - stages 2..7: each needs f (f_flops), its time t + c_i h (2: mul + add)
      and its input y + h * sum_j a_ij k_j over the non-zero a_ij
      (:func:`_combination_flops` + 1 for "y +"); stage 1 is reused (FSAL);
    - 5th-order solution y + h * sum b5_j k_j: combination + 1;
    - error estimate h * sum e_j k_j: combination;
    - error norm sqrt(mean((err / (atol + rtol * max(|y|, |y_new|)))^2)):
      2 abs + 1 max + 1 mul + 1 add + 1 div + 1 square + 1 mean + 1 sqrt = 9
      (abs, max, sqrt counted as one operation each, see the convention);
    - new step size h * clip(safety * err^(-1/5), ...): 1 power + 2 mul = 3.

    Worked count for the wear ODE (f_flops = 2). Stages with m non-zero
    a_ij cost 2 + 2 + 1 + (2m) = 2m + 5:
    m = 1..5 for stages 2-6 and m = 5 for stage 7 -> 7 + 9 + 11 + 13 + 15 + 15 = 70;
    b5 (5 non-zero): 10 + 1 = 11; error (6 non-zero): 12; norm + step: 12.
    Total 70 + 11 + 12 + 12 = 105.

    Example
    -------
    >>> rk45_attempt_flops(WEAR_RHS_FLOPS)
    105
    """
    total = 0
    for stage in range(1, 7):
        total += f_flops + 2 + _combination_flops(ode_solvers.DP_A[stage, :stage]) + 1
    total += _combination_flops(ode_solvers.DP_B5) + 1
    total += _combination_flops(ode_solvers.DP_E)
    total += 9 + 3
    return total


def solver_flops(method, n_steps, f_flops=WEAR_RHS_FLOPS, n_rejected=0):
    """Total FLOPs for a whole solve.

    Parameters
    ----------
    method : str
        "euler", "heun", "rk4" or "rk45".
    n_steps : int
        Steps taken (for rk45: accepted steps).
    f_flops : int, optional
        FLOPs of one f evaluation. Default 2 (wear ODE).
    n_rejected : int, optional
        rk45 only: rejected attempts, which cost as much as accepted ones.

    Returns
    -------
    int
        For rk45 one extra f evaluation (the very first slope) is added.

    Raises
    ------
    ValueError
        For an unknown method or negative counts.

    Example
    -------
    >>> solver_flops("rk4", 40)   # 40 steps x 25 FLOPs
    1000
    """
    if n_steps < 0 or n_rejected < 0:
        raise ValueError("Step counts must be >= 0.")
    per_step = {"euler": euler_step_flops, "heun": heun_step_flops, "rk4": rk4_step_flops}
    if method in per_step:
        return int(n_steps * per_step[method](f_flops))
    if method == "rk45":
        return int((n_steps + n_rejected) * rk45_attempt_flops(f_flops) + f_flops)
    raise ValueError(f"Unknown method {method!r}.")


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------
def profile_function(func, top=25):
    """Profile ``func()`` with cProfile; return (its result, table of top functions).

    Parameters
    ----------
    func : callable
    top : int, optional
        Number of functions to keep, sorted by cumulative time. Default 25.

    Returns
    -------
    result : object
        What ``func()`` returned.
    table : pandas.DataFrame
        Columns function, ncalls, tottime_s (time inside the function itself),
        cumtime_s (including everything it called), percall_cum_s.

    Example
    -------
    >>> _, table = profile_function(lambda: sorted(range(10000)), top=5)
    >>> list(table.columns)[:3]
    ['function', 'ncalls', 'tottime_s']
    """
    if not callable(func):
        raise TypeError("func must be callable.")
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        result = func()
    finally:
        profiler.disable()
    stats = pstats.Stats(profiler, stream=io.StringIO())
    rows = []
    for (filename, line, name), (_, ncalls, tottime, cumtime, _) in stats.stats.items():
        short = filename.replace("\\", "/").split("/site-packages/")[-1].split("/src/")[-1]
        rows.append({"function": f"{short}:{line}({name})", "ncalls": ncalls, "tottime_s": tottime,
                     "cumtime_s": cumtime, "percall_cum_s": cumtime / ncalls if ncalls else 0.0})
    table = pd.DataFrame(rows).sort_values("cumtime_s", ascending=False).head(top)
    return result, table.reset_index(drop=True)
