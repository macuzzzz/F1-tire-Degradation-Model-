# Decision log

Every technical decision in this project is recorded here. The AI proposed each
one; it was used only after my approval. "Open issues" at the bottom are
problems found during implementation that still need a decision.

---

## D1: Repository root and version control
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) use the existing project folder as the repo root; (b) create a nested `f1-tyre-degradation/` folder.
- Decision: (a). `git init` run immediately (branch `main`).
- Justification: The folder was empty; nesting adds path length with no benefit. Starting git in Phase 1 gives a meaningful history from the first commit.
- Source / evidence: n/a (project organisation).
- How it is validated: `git status` shows no cache/data files after real data is downloaded (see D9).
- Proposed by AI, approved by me (I asked for `git init` to be run now).

## D2: Python version
- Phase / date: Phase 1 / 2026-10-24
- Options considered: Python 3.13 (installed default); 3.14 (newest installed); 3.10 (minimum allowed).
- Decision: Virtual environment `.venv` on Python 3.13.
- Justification: Mature release with wheels for all pinned packages; 3.14 may lack wheels for some pins. All pins in D11 also support 3.10, so the "Python 3.10+" rule is still met.
- Source / evidence: `requires_python` metadata on PyPI for each pin (checked 2026-10-24): all are `>=3.10` or lower.
- How it is validated: `pip install -r requirements.txt` succeeded in a fresh 3.13 venv (2026-10-24).
- Proposed by AI, approved by me.

## D3: Seasons
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) 2022–2025; (b) 2019–2021; (c) include 2026.
- Decision: 2022–2025.
- Justification: One set of technical regulations (ground-effect cars) and 18-inch tyres throughout. 2021 and earlier used 13-inch tyres; 2026 introduced a new regulation set. Mixing eras would mix different tyres and cars.
- Source / evidence: General knowledge of the FIA technical regulations; primary source is the FIA Technical Regulations of each year. See also Open issue OI-2 (the HARD compound changed after 2022).
- How it is validated: Phase 5 checks whether fitted degradation rates differ strongly between years.
- Proposed by AI, approved by me.

## D4: Circuit and compound
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) one circuit over several seasons; (b) two circuits; (c) many circuits in one season.
- Decision: Bahrain Grand Prix only. **Only the HARD compound is modelled throughout the project** (my change).
- Justification: SOFT/MEDIUM/HARD are relative labels whose underlying Pirelli compound changes per event, so pooling circuits mixes different rubber. One circuit removes track-severity differences and gives a concrete race for strategy optimisation. Bahrain is a dry night race with an abrasive, high-degradation surface and 57 laps.
- Source / evidence (compound check requested by me): Pirelli nominated C1 = HARD, C2 = MEDIUM, C3 = SOFT at Bahrain in every year 2022–2025:
  - 2022: [F1.com tyre article](https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2022-bahrain-grand-prix.5nQGRrYUMcq8Y2BQeHBTeK)
  - 2023: [Pirelli preview](https://press.pirelli.com/2023-bahrain-grand-prix---preview/) — "The brand new C1 compound fills the gap between the hardest C0 (used as the C1 in 2022) and the C2."
  - 2024: [F1.com tyre article](https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-bahrain-grand-prix.6XY3WMWfBQV97jQz2NkVFw)
  - 2025: [F1.com tyre article](https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-bahrain-grand-prix.7gnHbNpm0OJQIjPqsWoyof) — "While the C1 is pretty similar to its predecessor, the C2 and C3 are softer."
  - Dry race: the 2022 data loaded contains only SOFT/MEDIUM/HARD (no INTERMEDIATE/WET). 2023–2025 still to be checked once data access works (OI-1).
- How it is validated: `Compound` values checked in the loaded data; per-year degradation compared in Phase 5.
- Proposed by AI, approved by me with changes (Bahrain only; HARD only).
- **Amendment (2026-10-24, my decision): compound changed from HARD to MEDIUM** (Pirelli C2 at Bahrain in all four years).
  - Reason: Red Bull ran no HARD laps at Bahrain 2022 (OI-2). They did run MEDIUM: PER stint 2 (laps 16–33, 18 laps) and VER stint 3 (laps 31–43, 13 laps). That is 31 raw laps, or 27 after removing in/out-laps. The 27 laps are all green-flag and all flagged `IsAccurate`. (This filtering is only indicative; the real cleaning rules are decided in Phase 2.)
  - Compound continuity: Pirelli's 2023 preview says the C2 was unchanged from 2022. The 2025 F1.com article says the 2025 C2 is softer. Whether the 2024 C2 is unchanged has not been verified.
  - Note: the HARD-specific concern in OI-2 (the 2022 C1 being a different compound) no longer applies.
- **Amendment 2 (2026-10-24, my decision): circuit = Hungarian Grand Prix (Hungaroring), compound = Pirelli C3.** The selection is by the actual Pirelli compound, not by the SOFT/MEDIUM/HARD label. This replaces Bahrain/MEDIUM.
  - Reason: Bahrain had no Red Bull MEDIUM laps in 2023 or 2024. Survey of every 2022–2025 race (Red Bull stints mapped to Pirelli compounds): C3 has the most data of any compound (4,221 Red Bull laps over 24 circuits), and Hungary has the most C3 laps (299 raw, 11 stints, data in all four years). Exploratory check: 269 usable laps (train 192, test 77). Typical within-stint noise is about 0.4 s. The per-stint trend is only about 2× its standard error, so the signal is weak and fuel-coefficient sensitivity will be important (Phase 7).
  - Allocation at Hungary (C3's label changes):

    | Year | Allocation | C3 is labelled |
    |---|---|---|
    | 2022 | C2–C4 | MEDIUM |
    | 2023–2025 | C3–C5 | HARD |

    Sources:
    - [Pirelli 2022 preview](https://press.pirelli.com/2022-hungarian-grand-prix---preview/)
    - [Pirelli 2023 nominations](https://press.pirelli.com/tyre-news-and-nominations-for-hungary-and-belgium/)
    - [F1.com 2024](https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-hungarian-grand-prix.6zgvwbJiWKVLFACHPftc1j)
    - [F1.com 2025](https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-hungarian-grand-prix.FZNZbRnpwYyLoRBrpOSwL)
  - Known caveats for the report:
    - The 2025 C3 was made softer than earlier C3s (F1.com 2025 Bahrain article).
    - 2023 Hungary used Pirelli's Alternative Tyre Allocation trial (fewer sets per weekend), which may change the tyre age at the start of a stint.
  - A second compound for the Phase 6 one-stop strategy (e.g. C4, which also has data in all four years) will be decided in Phase 6.

## D5: Training vs test races
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) train 2022/2023/2024, test 2025; (b) train 2022/2023, test 2024+2025; (c) random race split.
- Decision: (a). Leave-one-race-out cross-validation over the training races for model selection; 2025 evaluated once at the end.
- Justification: A forward-in-time split matches real use (predict the next race from past races). Trade-off: one test race gives a noisy test metric, and three training races give only 3 CV folds.
- Source / evidence: n/a (standard hold-out practice).
- How it is validated: Phase 5 test asserting no race appears in both train and test. `config.py` rejects duplicate races and requires at least one race of each role.
- Proposed by AI, approved by me ("your call").

## D6: Drivers
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) all drivers, data-driven exclusions only; (b) top-N finishers; (c) a chosen subset.
- Decision: **Only Red Bull Racing drivers** (my change). Implemented as a team filter `teams: ["Red Bull Racing"]` rather than a driver list, so it automatically follows driver changes between seasons. `drivers: null` stays available for an extra filter.
- Justification: Using one team keeps the car constant, which largely removes the car-to-car pace difference that would otherwise confound degradation.
- Source / evidence: Team name `"Red Bull Racing"` confirmed in FastF1 2022 data (drivers VER, PER). 2023–2025 names to be confirmed once data access works (OI-1).
- How it is validated: `select_laps` raises an error if the team filter matches no laps, so a renamed team cannot silently produce an empty data set.
- Proposed by AI, approved by me with changes (Red Bull only). See OI-3 on data volume.
- **Amendment (2026-10-24, my decision): all teams; car performance (downforce, top speed, balance, ...) is not modelled.** `teams: null`.
  - Reason: Red Bull alone gives only two cars per race. Including all teams gives roughly ten times as many stints.
  - Consequence for Phase 4: raw pace differs between cars. How that is handled statistically, without modelling car performance (e.g. a separate base lap time per stint), will be proposed in Phase 4.

## D7: Race identification
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) round number; (b) event name as resolved by FastF1; (c) event name plus an exact-match check.
- Decision: (c). The loader compares the requested name with `session.event["EventName"]` (case-insensitive) and raises `RaceNotFoundError` on a mismatch.
- Justification: Round numbers change between seasons (Bahrain was round 1 in 2022–2024, round 4 in 2025). FastF1 fuzzy-matches names.
- Source / evidence: Observed with FastF1 3.8.3 on 2026-10-24: `get_session(2023, "Atlantis Grand Prix", "R")` silently returned the **Australian Grand Prix** (only a log warning). Round numbers confirmed from FastF1 event data.
- How it is validated: `test_fuzzy_matched_event_is_refused` in `tests/test_data_loading.py`.
- Proposed by AI, approved by me.

## D8: What `Session.load()` downloads
- Phase / date: Phase 1 / 2026-10-24
- Options considered: download everything (FastF1 default) vs only what is used.
- Decision: `load(laps=True, telemetry=False, weather=False, messages=True)`; only session `"R"` supported.
- Justification: Telemetry is large and unused until the optional Phase 10; weather is unused. Race-control messages are kept because FastF1 uses them to flag deleted laps (`Deleted` column).
- Source / evidence: `Session.load` signature confirmed in FastF1 3.8.3: `load(*, laps=True, telemetry=True, weather=True, messages=True, livedata=None)`.
- How it is validated: `test_load_race_laps_requests_only_lap_data`.
- Proposed by AI, approved by me.

## D9: FastF1 cache location
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) project-local `cache/fastf1/`, git-ignored; (b) FastF1's per-user default folder.
- Decision: (a), configurable via `data.cache_dir` in `config.yaml`.
- Justification: Visible, easy to delete, and provably excluded from git (rule 10: F1 data is not redistributed).
- Source / evidence: `.gitignore` contains `cache/`.
- How it is validated: `git status` after a real download shows no cache files (checked 2026-10-24).
- Proposed by AI, approved by me.
- **Note (Phase 9 consistency review, D87 M1):** the key is now `fastf1.cache_dir`; it moved out of `data:` when the `openf1:` section (with `openf1.cache_dir`) was added in D15. The location is unchanged.

## D10: Configuration format
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) YAML via PyYAML (new dependency); (b) TOML via `tomllib` (Python 3.11+ only); (c) JSON (no comments); (d) plain `config.py`.
- Decision: (a) `config.yaml` read with `yaml.safe_load`. **PyYAML added as a dependency** (approved).
- Justification: The project brief asks for config.yaml, and YAML comments document units next to each value. `safe_load` is used because `yaml.load` can execute code from a malicious file.
- Source / evidence: n/a.
- How it is validated: `tests/test_config.py` (valid file loads; invalid types/ranges/missing keys raise).
- Proposed by AI, approved by me.

## D11: Version pins
- Phase / date: Phase 1 / 2026-10-24
- Options considered: (a) latest versions of everything; (b) a mutually compatible set that supports Python 3.10–3.13 with the latest FastF1.
- Decision: (b): fastf1 3.8.3, pandas 2.3.3, numpy 2.2.6, scipy 1.15.3, matplotlib 3.10.8, scikit-learn 1.7.2, pytest 8.4.2, pytest-html 4.1.1, pdoc 15.0.4, PyYAML 6.0.3. Full environment frozen in `requirements-lock.txt`.
- Justification: FastF1 depends on F1's servers, so the latest release is safest. fastf1 3.8.3 requires `pandas<3.0.0`, so pandas 2.3.3 is the newest allowed. numpy 2.2 is the last series supporting Python 3.10.
- Source / evidence: All versions confirmed to exist on PyPI (`pip index versions`, 2026-10-24); fastf1 3.8.3 dependency metadata from PyPI; installed together without conflicts.
- How it is validated: Clean install in a fresh venv; test suite passes. **Verify the pins yourself on pypi.org.** May change depending on OI-1.
- Proposed by AI, approved by me.

## D12: Configuration values for later phases, seed and year range
- Phase / date: Phase 1 / 2026-10-24
- Options considered: choose Phase 2 values now vs leave them `null` until Phase 2.
- Decision: `k_fuel`, `pit_loss_override`, `outlier_k`, `min_stint_laps`, `total_laps_override` are `null` until approved in their phase; `config.py` checks only physical sign limits when they are set (k_fuel ≥ 0, pit loss > 0, outlier_k > 0, min_stint_laps ≥ 1, total laps ≥ 2). `random_seed: 42`. Valid years: 2018 to the current year.
- Justification: Avoids choosing numbers before their own decision step. The seed value is arbitrary; recording it is what matters (rule 11).
- Source / evidence: The 2018 lower limit comes from my understanding that FastF1 lap timing starts in 2018; **not yet verified** — check the FastF1 documentation ("data availability").
- How it is validated: `tests/test_config.py`.
- Proposed by AI, approved by me.
- **Note (Phase 9 consistency review, D87 M2):** `outlier_k`, `min_stint_laps` and `k_fuel` were set in Phase 2 (D19, D20, D22); `pit_loss_override` and `total_laps_override` are still `null` by decision (D24, D23, D58). The 2018 lower year limit has still not been verified against the FastF1 documentation.

## D13: Output format of the loader
- Phase / date: Phase 1 / 2026-10-24
- Options considered: keep FastF1's `Laps` object and timedeltas vs a plain DataFrame in float seconds.
- Decision: Plain `pandas.DataFrame`; `LapTime`, `PitInTime`, `PitOutTime` converted to float seconds; missing times kept as NaN (not dropped, so cleaning can count them); added `Year`, `EventName`, `RaceId`, `TotalLaps`; custom exceptions `RaceNotFoundError(ValueError)` and `RaceDataUnavailableError(RuntimeError)`. If `session.total_laps` is unavailable, `TotalLaps` is NaN (no guessed value) and `race.total_laps_override` is used later.
- Justification: All numerical methods work on floats; keeping FastF1 types out of later modules makes them testable offline.
- Source / evidence: Columns and dtypes checked on the real 2022 Bahrain race with FastF1 3.8.3: all of `Driver, DriverNumber, Team, LapNumber, LapTime, Stint, Compound, TyreLife, FreshTyre, PitInTime, PitOutTime, TrackStatus, IsAccurate, Deleted, FastF1Generated` exist; `session.total_laps` = 57. `fastf1.core.DataNotLoadedError` is deprecated in 3.8.3, so `fastf1.exceptions.DataNotLoadedError` is used.
- How it is validated: `tests/test_data_loading.py` (conversion, columns, error handling).
- Proposed by AI, approved by me.

## D14: Data source (free only)
- Phase / date: Phase 1 / 2026-10-24
- Options considered:
  - (a) F1 TV subscription with the FastF1 3.9.0a0 pre-release;
  - (b) free sources: FastF1 for 2022 (from its free mirror) and the OpenF1 REST API for 2023–2025;
  - (c) free 2021–2022 data only.
- Decision: (b).
- Justification: No subscription is needed, so anyone can reproduce the work. Option (c) breaks D3 and gives too little data.
- Source / evidence (checked 2026-10-24):
  - The FastF1 mirror has 2021–2022 only.
  - OpenF1 serves races, drivers, stints (compound, `tyre_age_at_start`) and laps (`lap_duration` in seconds, `is_pit_out_lap`) for 2023 onward.
  - **OpenF1 restricts all free access while a live F1 session is running.** This was observed on 2026-10-24 as HTTP 401: "Live F1 session in progress. Global API access (including past sessions) is restricted to authenticated users until the session ends."
- How it is validated:
  - Offline tests of both loaders.
  - The two sources are combined into one table format (proposal D16, pending).
  - Caching (proposal D15, pending) removes the dependence on OpenF1 after the first download.
- Proposed by AI, approved by me ("stick to the free version").

## D15: OpenF1 client (HTTP library, caching, politeness)
- Phase / date: Phase 1 / 2026-10-24
- Options considered:
  - HTTP library: `requests` (already installed as a FastF1 dependency) vs the standard library's `urllib`.
  - Caching: cache every response on disk vs download on every run.
- Decision:
  - `requests==2.34.2` added as a direct, pinned dependency.
  - Every OpenF1 response is cached as JSON in `cache/openf1/<endpoint>/<params>.json` (git-ignored) and downloaded only once.
  - The client waits 0.4 s after each real download.
  - On HTTP 429 it retries up to 5 times, waiting 2 s, 4 s, ... between attempts.
  - HTTP 404 is treated as "no results".
  - HTTP 401/403 raises `RaceDataUnavailableError`, with a message explaining the live-session restriction. Nothing is cached in that case.
  - The delay and retry count are set in `config.yaml` (`openf1:` section).
- Justification:
  - `requests` is far more readable than `urllib`.
  - Caching makes runs reproducible offline and avoids OpenF1's live-session block and rate limits.
  - Caching also keeps the data out of git (rule 10).
- Source / evidence: observed on 2026-10-24:
  - HTTP 429 when requests were sent too fast;
  - HTTP 404 for the cancelled 2023 Imola race;
  - HTTP 401 during a live session.
- How it is validated: `tests/test_openf1_loading.py` (cache hit, 404, 429 retry and back-off, give-up, 401 with no cache file, network failure).
- Proposed by AI, approved by me.

## D16: Unified laps table, Pirelli compounds and green-lap detection
- Phase / date: Phase 1 / 2026-10-24
- Options considered:
  - Keep each source's own columns vs convert both into one table format.
  - Select laps by relative label vs by Pirelli compound.
- Decision:
  - **One table format** for both loaders (documented in `src/tyredeg/loading_common.py`).
    - `PitInTime`/`PitOutTime` are replaced by the true/false columns `IsPitInLap`/`IsPitOutLap`.
    - A new true/false column `IsGreenLap`.
    - `Source` records `fastf1` or `openf1`.
  - **`PirelliCompound`** is added from the committed table `reference/pirelli_allocation.csv`. It has 92 races from 2022–2025 with a source URL per row; 23 rows (including all 4 Hungary rows) are independently cross-checked. `config.yaml` selects `pirelli_compounds: ["C3"]`.
  - **`IsGreenLap`:**
    - FastF1: the lap's `TrackStatus` contains only code `"1"`.
    - OpenF1: the lap's time window `[date_start, date_start + lap_duration]` overlaps no time window with a yellow flag (any sector), safety car, VSC (including "VSC ending") or red flag. Those windows are rebuilt from race-control messages (`src/tyredeg/race_control.py`).
    - A lap with a missing start time or lap time counts as not green.
  - **`TyreLife`** means laps completed on the set by the end of the lap. OpenF1: `tyre_age_at_start + (lap − lap_start) + 1`. This matches FastF1, where the out-lap of a new set has `TyreLife = 1`.
- Justification: Later phases see one data format regardless of source. Selecting by Pirelli compound keeps the same rubber across years even though its label changes.
- Source / evidence:
  - FastF1 track-status codes seen in real 2022 data: `1` all clear, `2` yellow, `4` SC, `6` VSC deployed, `7` VSC ending.
  - **Validation of the message-based green-lap rule against FastF1's own `TrackStatus` (2022 races, same official feed):**

    | Race | Timed laps | Agreement |
    |---|---|---|
    | Hungary | 1,382 | 100.0% |
    | Bahrain | 1,118 | 99.8% (2 laps at the edge of a yellow window) |

    In this check, lap start times were converted to UTC using the VSC-deployment time seen in both feeds, because FastF1's `LapStartDate` is empty in the mirror data.
  - OpenF1 field names are from https://openf1.org/docs (checked 2026-10-24).
- How it is validated:
  - Tests: `tests/test_race_control.py`, `tests/test_tyre_allocation.py`, `tests/test_openf1_loading.py`, `tests/test_data_loading.py`.
  - The loader logs a warning when an in-lap is not followed by an out-lap.
  - **Pending:** a real-data check of the OpenF1 path. Before it, OpenF1 was blocked by a live session (2026-10-24).
- Proposed by AI, approved by me.

## D11 amendment: `requests==2.34.2` added (see D15).

---

# Phase 2: cleaning, fuel correction, pit loss

All evidence below was computed on the **training races only** (Hungary 2022–2024); the 2025 test race was not looked at.

## D17: Order of processing and cleaning report
- Phase / date: Phase 2 / 2026-10-24
- Options considered: report removals per rule independently (counts overlap) vs sequentially (each lap counted once).
- Decision:
  - **Processing order:** fill race length (D23) → fuel-correct every lap (D21) → clean → select C3.
  - **Cleaning rules, in this order:** missing lap time → first lap → in/out-laps → not green → inaccurate → missing stint information → outliers → short stints.
  - **Report:** each lap is counted under the first rule that removes it, so the counts add up exactly to the total removed.
  - "Missing stint information" was added because a few OpenF1 laps have no stint record.
- Justification: Sequential counting makes the report add up exactly and is easy to explain. Cleaning runs on all compounds, because the pit-loss estimate needs every driver's clean laps.
- Source / evidence: training races, 3,994 laps → 3,143 clean laps (all compounds), of which 1,991 are C3 laps in 87 stints (tyre age 2–41 laps).

  | Rule | Laps removed |
  |---|---|
  | missing lap time | 6 |
  | first lap | 59 |
  | in/out-laps | 236 |
  | not green | 184 |
  | inaccurate | 0 |
  | missing stint information | 0 |
  | outliers | 255 |
  | short stints | 111 |

- How it is validated: `test_clean_laps_report_counts_are_exact` (synthetic race with a known number of laps for each rule) and `test_clean_laps_report_order_and_consistency`.
- Proposed by AI, approved by me.

## D18: Green-flag laps, inaccurate laps, deleted laps
- Phase / date: Phase 2 / 2026-10-24
- Options considered:
  - Green-flag laps: (a) only fully green laps; (b) as (a) plus 1–2 laps after each restart; (c) accept single-sector yellows.
  - Deleted laps: keep vs remove.
- Decision:
  - **(a) only fully green laps (`IsGreenLap`, D16).**
    - FastF1: the lap's track status is code `1` only.
    - Codes that exclude a lap: `2` yellow, `4` SC, `5` red, `6` VSC deployed, `7` VSC ending.
    - OpenF1: the equivalent windows are rebuilt from race-control messages.
  - **`IsAccurate`:** remove a lap only if it is flagged exactly `False`. Unknown values (all OpenF1 laps) are kept.
  - **Laps deleted for track limits are kept.**
- Justification:
  - 96.7–99.9% of laps in 2023–2025 are green, so a post-restart rule adds a tuning value for almost no effect. Slow restart laps are caught by the outlier rule.
  - A deleted lap's time was really driven, and OpenF1 has no such flag, so removing those laps would clean the two sources differently.
- Source / evidence:
  - Status codes as observed in the 2022 data.
  - The inaccurate rule removes 0 laps in practice: all 180 laps FastF1 flagged inaccurate were already removed by earlier rules.
- How it is validated: `test_simple_rule_masks`, `test_inaccurate_mask_treats_unknown_as_accurate`; the D16 agreement check.
- Proposed by AI, approved by me (P1: a, P2: a).

## D19: Outlier rule and threshold
- Phase / date: Phase 2 / 2026-10-24
- Options considered (exploratory comparison on 2,147 C3 training laps; percentage removed at k = 2.5 / 3.0 / 3.5):

  | Rule | k = 2.5 | k = 3.0 | k = 3.5 | Flags on first/last 3 laps of long stints (k = 3) |
  |---|---|---|---|---|
  | (a) distance from the stint median | 8.8% | 6.3% | 4.6% | 55 |
  | (b) distance from a 5-lap rolling median | 17.1% | 14.2% | 12.2% | 83 |
  | (c) distance from a robust Theil–Sen line | 9.0% | 6.8% | 5.0% | 43 |

- Decision: **(c), `outlier_k = 3.0`.**
  1. Within each stint, fit a Theil–Sen line of lap time against tyre age. The slope is the median of all pairwise slopes; the intercept is the median of `y − slope·x`.
  2. Take the residuals from that line.
  3. Robust spread = 1.4826 × MAD of the residuals.
  4. Remove laps whose |residual − median residual| > 3 × the robust spread.
  - The rule is not applied to stints with fewer than 3 laps, or when the spread is 0.
  - It runs on **raw** lap times.
- Justification:
  - Lap times rise by about 0.9 s over a typical stint, while the noise is about 0.4 s. A flat median (a) therefore flags genuine laps at the start and end of a stint, which carry the degradation signal.
  - The rolling median (b) is too noisy.
  - k = 3 is conservative, so real degradation laps aren't thrown away.
  - Using raw times means the cleaning doesn't change when the fuel coefficient is varied in Phase 7.
- Source / evidence:
  - Leys et al. (2013), *J. Exp. Soc. Psychol.* 49(4): MAD-based outlier detection; recommends 2.5 by default and 3 as conservative. **To verify.**
  - Theil (1950); Sen (1968), *JASA*: the Theil–Sen estimator. **To verify.**
  - Real-data result: removes 255 laps (7.3% of the laps still remaining at that step, all compounds).
- How it is validated:
  - `test_theil_sen_matches_scipy_benchmark` (`scipy.stats.theilslopes`, method "joint");
  - planted-outlier tests;
  - `test_outlier_rule_does_not_flag_ends_of_a_degrading_stint`;
  - Phase 7 compares k = 2.5 and 3.5.
- Proposed by AI, approved by me (P3: c).

## D20: Minimum stint length
- Phase / date: Phase 2 / 2026-10-24
- Options considered: 5, 10 or 15 clean laps. Each keeps 99.9%, 99.5% and 98.2% of C3 laps (exploratory).
- Decision: `min_stint_laps = 10`.
- Justification: Each stint needs enough laps to estimate its own base time and trend. With about 0.4 s noise, a 10-lap stint gives a slope uncertainty of about 0.04 s/lap. This setting costs only two real C3 stints.
- Source / evidence: the exploratory distribution of C3 stint lengths (median 25 laps; 90% have at least 17). Removes 111 laps (all compounds) on the training races.
- How it is validated: `test_short_stints_mask_boundary` (exactly 10 kept, 9 dropped).
- Proposed by AI, approved by me.

## D21: Fuel-load model
- Phase / date: Phase 2 / 2026-10-24
- Options considered: (a) linear, referenced to the end of the race; (b) linear, referenced to the race start; (c) fuel burn that varies between laps.
- Decision: **(b) `corrected = lap time + k_fuel · (lap number − 1)`**, i.e. the time the lap would have taken carrying the full lap-1 fuel load. Fuel load is assumed to fall linearly with lap number. `total_laps` is used only to reject lap numbers beyond the end of the race.
- Justification:
  - (a) and (b) differ only by a constant `k_fuel·(N − 1)` for each race, so every degradation slope is identical.
  - (b) doesn't need the race length in the formula.
  - (c) needs per-lap fuel data, which isn't available.
- Source / evidence: n/a (modelling assumption). Laps behind a safety car burn less fuel, but those laps are removed by D18.
- How it is validated: `test_pure_fuel_effect_is_removed_exactly` (a car whose times fall exactly by `k_fuel` per lap becomes constant after correction).
- Proposed by AI (recommended (a)); **I chose (b)**.

## D22: Fuel coefficient
- Phase / date: Phase 2 / 2026-10-24
- Options considered: the rule-of-thumb value vs the value estimated from the training data.
- Decision: `k_fuel = 0.046` s per lap of fuel; sensitivity range 0.015–0.070 (`k_fuel_min`, `k_fuel_max`).
- Justification: two independent routes give almost the same value.

  | Route | k_fuel [s per lap of fuel] |
  |---|---|
  | Rule of thumb: 0.03 s/kg × 110 kg / 70 laps | 0.047 |
  | Training data, joint fit | 0.0456 (SE 0.0006) |
  | Training data, per race | 0.039 / 0.050 / 0.049 |

  - The joint fit: lap time ≈ a separate constant for each driver in each race + a tyre-age slope for each compound + `k_fuel` × laps of fuel remaining. It was fitted with numpy `lstsq` on 3,036 dry laps.
  - The range covers the published 0.01–0.045 s/kg spread.
- Source / evidence:
  - The 0.03 s/kg figure has **no primary source**; it appears only in secondary sources: Medium "Fuel correction"; Las Motorsport (0.030–0.035); F1 Briefing (0.03–0.04); Autosport forum (0.01–0.045).
  - The 110 kg race-fuel limit is from the FIA F1 Technical Regulations. **Verify the article.**
  - Caveat: the data estimate assumes linear degradation; any curvature leaks into `k_fuel`.
- How it is validated: re-estimate with my own least squares (Phase 3/4); Phase 7 sensitivity across the range. `config.py` checks `min ≤ k_fuel ≤ max`.
- Proposed by AI, approved by me.

## D23: Race length when the source does not report it
- Phase / date: Phase 2 / 2026-10-24
- Options considered: (a) the highest lap number completed in the race; (b) require `total_laps_override`.
- Decision: **(a)**, with a log message. FastF1's official value is kept where present, and `total_laps_override` (if set) wins for every race.
- Justification: The highest lap number is 70 in every Hungary race, equal to FastF1's official 70 for 2022. This would be wrong only for a race stopped early (none here).
- Source / evidence: real-data run: `TotalLaps` = 70 for 2022, 2023 and 2024.
- How it is validated: `test_fill_total_laps_uses_highest_lap_only_when_missing`, `test_fill_total_laps_override_wins`.
- Proposed by AI, approved by me.

## D24: Pit-loss estimation
- Phase / date: Phase 2 / 2026-10-24
- Options considered: (a) median and IQR over all qualifying stops; (b) mean ± standard deviation; (c) a separate value for each race.
- Decision: **(a)**.
  - Loss = (in-lap + out-lap) − 2 × the driver's median clean lap in that race, all **fuel-corrected**.
  - Only stops where the in-lap and the following out-lap are both green.
  - Training races only.
  - IQR = the 25th to 75th percentile, i.e. the spread of the middle 50% of stops (numpy linear interpolation).
  - `pit_loss_override` stays null.
- Justification:
  - The median and IQR are not distorted by a few badly delayed stops (up to 34 s here).
  - Fuel correction stops an early stop being compared with laps run on a much lighter car.
  - Stops under a safety car are cheaper, so they are excluded.
- Source / evidence: real-data run (fuel-corrected, k_fuel = 0.046).
  - **Pooled: median 21.51 s, IQR 20.04–23.05 s (n = 107 stops).**
  - Per race (median): 2022 23.47 s (n = 31), 2023 21.48 s (n = 36), 2024 20.29 s (n = 40).
  - No stop in the training races was a drive-through without a tyre change.
- How it is validated: `test_pit_loss_exact_values` (synthetic losses 20/22/24 → median 22, IQR 21–23), `test_pit_loss_compares_within_the_same_race`; Phase 7 varies the pit loss across the IQR.
- Proposed by AI, approved by me (I asked what IQR means; definition added above).

---

# Phase 3: numerical methods

Evidence comes from `scripts/numerics_study.py`. It writes tables to `reports/phase3_*.csv` and figures to `reports/figures/phase3_*.png`, and contains no randomness. The test problem is the wear ODE dd/dn = 0.05 + 0.03 d, d(0) = 0, over 40 laps, unless stated otherwise.

## D25: Embedded Runge–Kutta pair for RK45
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) Dormand–Prince 5(4); (b) Fehlberg RKF45; (c) Bogacki–Shampine 3(2).
- Decision: **(a) Dormand–Prince 5(4)**. It advances with the 5th-order solution (local extrapolation). The 7th stage is reused as the next step's 1st stage (FSAL), so each step costs 6 new function evaluations.
- Justification: Its coefficients are tuned to make the 5th-order error small. It is also the pair SciPy's `RK45` uses, so the benchmark compares the same method.
- Source / evidence:
  - Dormand & Prince (1980), *J. Comput. Appl. Math.* 6(1), 19–26; Hairer, Nørsett & Wanner, *Solving ODEs I*, 2nd ed., Table 5.2 (**verify the coefficients against the book**).
  - SciPy's source confirms that its `RK45` is Dormand–Prince.
- How it is validated: `test_dormand_prince_coefficients_match_scipy` (identical to 1e-15); the nfev identity 1 + 6 × (steps attempted); agreement with `solve_ivp`.
- Proposed by AI, approved by me.

## D26: Error norm
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) RMS norm; (b) max norm.
- Decision: **(a)** the RMS of `err_i / (atol + rtol·max(|y_old|, |y_new|))`; accept the step if it is ≤ 1.
- Justification: The mixed absolute/relative scale works when y ≈ 0 (d(0) = 0) and when y is large. It is Hairer's and SciPy's choice (SciPy `common.norm` checked).
- Source / evidence: as D25.
- How it is validated: RK45 tests against SciPy.
- Proposed by AI, approved by me.

## D27: Step-size controller
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) safety 0.9, min_factor 0.2, max_factor 10 (SciPy); (b) 0.8 / 0.2 / 5.
- Decision: **(a)**. `h_new = h · clip(0.9 · err^(−1/5), 0.2, 10)`; no growth on the retry after a rejected step.
  - **All three settings are function arguments**, so they can be adjusted for more accuracy, as I asked.
- Justification: identical settings to SciPy make any disagreement with it diagnostic of a bug.
- Source / evidence:
  - SciPy constants read from its source: `SAFETY = 0.9`, `MIN_FACTOR = 0.2`, `MAX_FACTOR = 10`, exponent −1/(4 + 1).
  - Study (`phase3_rk45.csv`), from rtol = 1e-2 down to 1e-12:
    - All three controllers reach the same accuracy at tight tolerances.
    - A smaller max_factor (2) is more accurate at loose tolerances but costs more evaluations (43 vs 25 at rtol = 1e-3).
    - The approved controller needs **fewer** evaluations than SciPy at every tolerance (e.g. 49 vs 74 at rtol = 1e-6), with the same error.
- How it is validated: `test_rk45_against_exact_and_scipy`, `test_rk45_rejects_a_too_large_first_step`, `test_rk45_controller_settings_are_adjustable`.
- Proposed by AI, approved by me ("be flexible to adjust the step size for more accuracy": settings exposed, and the study plots error against cost).

## D28: RK45 initial step, minimum step, step limit
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) `h0 = 0.01 × interval`; (b) Hairer's automatic starting-step algorithm.
- Decision: **(a)**, which can be overridden with `h0`.
  - Raise an error if h < 10·eps·max(1, |t|).
  - `max_steps = 10000` step attempts.
- Justification: Simple to explain; the controller corrects a poor first guess within 1–2 rejected steps.
- Source / evidence: The study shows fewer evaluations than SciPy, whose automatic initial step is apparently more cautious on this problem.
- How it is validated: `test_rk45_max_steps_exceeded`, `test_rk45_rejects_a_too_large_first_step`.
- Proposed by AI, approved by me.

## D29: Default ODE tolerances
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) `rtol = 1e-3, atol = 1e-6` (SciPy's defaults); (b) `1e-6 / 1e-9`; (c) `1e-10 / 1e-12`.
- Decision: **(a) 1e-3 / 1e-6.**
- Justification: My concern was that rtol = 1e-3 might allow errors around the 1 ms timing resolution. The study shows it doesn't on the wear ODE: **the error at lap 40 is 3.2e-5 s (0.03 ms), with 25 function evaluations.** Tighter tolerances remain available per call.
- Source / evidence: `reports/phase3_rk45.csv`.
- How it is validated: `test_rk45_against_exact_and_scipy` at 1e-3/1e-6, 1e-6/1e-9 and 1e-10/1e-12.
- Proposed by AI (recommended (b)); **I chose (a)**.

## D30: Fixed-step interface and root-finder stopping rule
- Phase / date: Phase 3 / 2026-10-24
- Options considered:
  - Fixed-step solvers: shorten the final step vs require h to divide the interval.
  - Root finders: stop on (a) a small step; (b) a small residual; (c) either.
- Decision:
  - **Fixed-step solvers:** `euler/heun/rk4(f, t_span, y0, h) → (t, y, nfev)`, with the last step shortened to land exactly on `t_end`. `rk45` returns `(t, y, nfev, stats)`.
  - **Root finders:** **(c)** stop on `|step| ≤ xtol = 1e-10` **or** `|f| ≤ ftol = 1e-12`, with `max_iter = 100`. They return `RootResult(root, iterations, history)`.
- Justification: Landing exactly on the end lap avoids overshooting. Rule (c) protects against both flat and steep functions in terms of iteration count.
- Source / evidence: the study's stopping-rule comparison (`phase3_root_finding_stopping_rules.csv`):
  - **simple and steep roots:** all three rules give errors ≤ 1e-10;
  - **flat triple root (x − 1)³:** the residual test stops early, so "either" gives an error of about **1e-4**, whereas "step only" reaches about **1e-10** (but needs 34–74 iterations instead of 12–29).
  - **See open issue OI-4.**
- How it is validated: `test_either_tolerance_alone_can_stop_the_iteration`, `test_residual_test_stops_early_on_a_flat_function`, `test_last_step_is_shortened_to_hit_t_end`.
- Proposed by AI, approved by me ("experiment with other methods": done, see OI-4).

## D30 amendment: root-finder stopping rule ("both" + round-off safeguard)
- Phase / date: Phase 3 / 2026-10-24 (resolves OI-4)
- Options considered:
  - (a) keep "either";
  - (b) step only;
  - (c) "both": stop only when the step AND the residual are small;
  - (c′) "both", plus a round-off safeguard.
- Decision: **(c′)**. Stop when `|step| ≤ xtol` **and** `|f| ≤ ftol`, **or** when the step has shrunk to round-off level, `|step| ≤ 4·eps·|x|`. A tolerance of 0 switches that test off: `ftol = 0` means step only, `xtol = 0` means residual only.
- Justification:
  - Each single test can stop too early: the residual test on flat functions, the step test on steep ones. Requiring both takes the stricter result.
  - **Strict (c) does not work in general.** When the closest floats to the root leave |f| > ftol, it never stops.
  - The safeguard stops once x can no longer change, returning the best root available in floating point.
- Source / evidence:
  - **Strict (c) failure** (before the safeguard), on f = 10⁴·(e^(x/10) − 30), root ≈ 34.01: bisection and Newton raised `NotConvergedError`; secant raised a misleading `ZeroDerivativeError`. "Step only" converged in 5–37 iterations.
  - **Study with (c′)** (`reports/phase3_root_finding_stopping_rules.csv`): in all 12 method/problem cases, the error is equal to the better of "step only" and "residual only".

    | Problem | (c′) | Step only | Residual only |
    |---|---|---|---|
    | Flat root (x − 1)³ | 2.3e-11 to 2.5e-10 | same | 7.8e-5 to 9.8e-5 |
    | Steep roots, bisection | 7e-15 to 2e-14 | 2.6e-11 to 8.9e-11 | same as (c′) |

  - **Cost:** more iterations only on the flat root (bisection 34 vs 12). x² − 2 now takes 38 bisection and 7 secant iterations (previously 34 and 6).
  - The factor 4 in the safeguard is a machine-precision constant in the code (like the pivot tolerance), not a tuning value.
- How it is validated: `test_both_tests_must_pass_by_default`, `test_a_zero_tolerance_switches_that_test_off`, `test_both_rule_is_accurate_on_a_flat_function`, `test_roundoff_safeguard_on_a_steep_function` (all three methods).
- Proposed by AI. I first chose (c); the AI then found it can fail to terminate, stopped, and proposed (c′), which I approved.

## D31: Root-finder failure detection
- Phase / date: Phase 3 / 2026-10-24
- Options considered: divergence = (a) a non-finite iterate or |x| > 1e10; (b) also |f| increasing for 3 iterations in a row.
- Decision: **(a)**. Errors are subclasses of `ValueError`:
  - `NoSignChangeError`;
  - `ZeroDerivativeError` (f′ = 0, or a horizontal secant line);
  - `DivergenceError` (also raised when f returns a non-finite value);
  - `NotConvergedError`.
  - Newton takes `fprime` from the caller.
- Justification: Option (b) can falsely flag Newton's normal early overshoot.
- Source / evidence: Newton on arctan from x0 = 1.5 diverges (1.5, −1.69, 2.32, −5.11, …), the classic example.
- How it is validated: the failure-case tests in `tests/test_root_finding.py`.
- Proposed by AI, approved by me.

## D32: Default finite-difference step
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) a fixed h = 1e-5; (b) the per-formula optimum eps^(1/(p+m)) × max(1, |x|); (c) the user must always supply h.
- Decision: **(b)**:

  | Formula | Default h |
  |---|---|
  | Forward / backward | eps^(1/2) ≈ 1.5e-8 |
  | Central, 1st derivative | eps^(1/3) ≈ 6.1e-6 |
  | Central, 2nd derivative | eps^(1/4) ≈ 1.2e-4 |

  Each value is multiplied by max(1, |x|), and every function accepts an `h` override.
- Justification: Balancing the truncation error C·hᵖ against the round-off error eps/hᵐ gives these optimum steps.
- Source / evidence:
  - Nocedal & Wright, 2nd ed., §8.1 (**to verify**).
  - Study, sin at x = 1: the empirical optimum (V-curve minimum, smoothed with a 9-point running median) is **0.6–0.74 × the theoretical step**, and the error at the default is within 2.7× of the minimum.
  - At x = 10, the empirical optimum is 0.1–0.3 × the default: the |x| scaling over-sizes h for sin. Errors stay ≤ 7e-8. See OI-5.
- How it is validated: order tests (1, 1, 2, 2 within ±0.1); `test_default_step_is_near_the_empirical_optimum` (reruns at the study's optimum: within 10× of it, and error within 10× of the minimum).
- Proposed by AI, approved by me (I asked for a graph to find the optimal step and to rerun the tests with it).

## D33: Derivatives of sampled arrays
- Phase / date: Phase 3 / 2026-10-24
- Options considered: end points with (a) second-order one-sided formulas; (b) first-order one-sided formulas; (c) NaN.
- Decision: **(a)**. Uniform spacing is required. Central first and second derivatives are O(h²) at every point; forward and backward versions return n − 1 values.
- Justification: Gives one accuracy everywhere. Lap data is uniformly spaced.
- Source / evidence: identical to `numpy.gradient(…, edge_order=2)` to 1e-12.
- How it is validated: `test_sample_formulas_are_second_order_including_ends`, `test_central_samples_match_numpy_gradient`.
- Proposed by AI, approved by me.

## D34: Singular and near-singular matrices
- Phase / date: Phase 3 / 2026-10-24
- Options considered:
  - Estimate: (a) the 1-norm estimate with my own LU; (b) `numpy.linalg.cond`; (c) the Hager–Higham estimator.
  - Threshold: 6.7e7, 1e12 or 4.5e15.
- Decision:
  - **Estimate (a):** κ₁ = ‖A‖₁‖A⁻¹‖₁, with A⁻¹ from n LU solves.
  - **Warning threshold: 1e12** (`NearSingularWarning`).
  - **Singular:** `SingularMatrixError` if |pivot| ≤ n·eps·max|A|.
- Justification: Relative error ≈ κ·eps, so κ = 1e12 leaves about 4 good digits.
- Source / evidence:
  - Higham (2002) (**to verify**).
  - The estimate equals `numpy.linalg.cond(A, 1)` to 1e-10 on a random matrix.
  - Hilbert(10) (κ₁ ≈ 3.5e13) warns; Hilbert(6) (κ₁ ≈ 2.9e7) does not.
- How it is validated: `tests/test_linear_solvers.py`.
- Proposed by AI, approved by me (I chose the 1e12 threshold when asked to clarify).

## D35: Least squares — comparison method and polynomial scaling
- Phase / date: Phase 3 / 2026-10-24
- Options considered:
  - Comparison method: (a) numpy QR plus my back substitution; (b) SVD via `numpy.linalg.lstsq`.
  - Scaling: on or off by default.
- Decision:
  - **Main method:** the normal equations with my Gaussian elimination.
  - **Comparison:** (a) QR. SVD/`lstsq` is used in tests and the study only.
  - **Polynomial scaling to [−1, 1] is on by default.** Results include standard errors, `predict` and `unscaled_coefficients()`.
- Justification: cond(XᵀX) = cond(X)², so the normal equations lose twice as many digits; QR does not form XᵀX.
- Source / evidence: Golub & Van Loan, 4th ed., §5.3 (**to verify**). Study (`phase3_least_squares.csv`, noise-free data with tyre ages 1–41, exact reference coefficients):

  | Degree | Normal equations, unscaled | QR, unscaled | SVD (`lstsq`), unscaled | All methods, scaled |
  |---|---|---|---|---|
  | 4 | 3.3e-13 (warns) | 1.8e-15 | 5.1e-15 | ≤ 1.4e-14 |
  | 6 | 3.6e-9 (warns) | 5.1e-13 | 1.7e-10 | ≤ 2.3e-13 |

  QR is the most accurate in every unscaled case. For the scaled, low-degree fits the project will use, all methods are accurate to about 1e-14.
- How it is validated: `tests/test_least_squares.py`, including `test_qr_more_accurate_than_normal_on_ill_conditioned_fit` and `test_normal_equations_warn_for_unscaled_quartic_but_qr_does_not`.
- Proposed by AI, approved by me ("try both methods and see which is better; start with the recommended one").

## D36: Fixed-step accuracy at the study's optimal steps
- Phase / date: Phase 3 / 2026-10-24
- Options considered: n/a. This records results I asked for (find the optimal step and rerun the tests with it).
- Decision: The tests also check accuracy at the smallest-error step found in the study.

  | Method | Optimal h [laps] | Error at that h | Largest h with error ≤ 1 ms |
  |---|---|---|---|
  | RK4 | 40/4096 ≈ 0.0098 | 8.9e-16 | 10 laps (the largest tested) |
  | Heun | 40/65536 | 3.7e-10 | 0.625 |
  | Euler | 40/65536 | 6.1e-5 | 0.0098 |

  RK4 with 1-lap steps is accurate to better than 1e-6 s.
- Justification: Below RK4's optimal step, round-off grows (visible in `phase3_ode_fixed_step.png`).
- Source / evidence: `reports/phase3_ode_fixed_step.csv`.
- How it is validated: `test_error_at_study_optimal_step`, `test_rk4_meets_1ms_with_one_lap_steps`.
- Proposed by AI, approved by me.

## D37: Test acceptance tolerances
- Phase / date: Phase 3 / 2026-10-24
- Options considered: as proposed (N13).
- Decision (`verification:` in config.yaml):

  | Check | Acceptance |
  |---|---|
  | ODE order (Euler/Heun/RK4) | ±0.1, from the slope of log(error) against log(h) over h = T/40 … T/320 |
  | RK45 | error ≤ 10 × (atol + rtol·\|y\|) against the exact answer and against SciPy; nfev ≤ 1.5 × SciPy's |
  | Newton order | 2 ± 0.2 |
  | Secant order | 1.618 ± 0.25 |
  | Finite-difference order | ±0.1 |
  | Linear solver vs `numpy.linalg.solve` | relative difference ≤ 1e-12 |
  | Least squares vs `lstsq` | relative difference ≤ 1e-8 |
  | Recovered coefficients | within 3 standard errors of the truth (seed 42, noise σ = 0.4 s) |

- Justification: The exploratory run gave observed orders of 0.99–1.01, 1.98–2.01 and 3.98–4.02 for Euler, Heun and RK4; Newton 1.98–2.26; secant 1.50–2.03.
- Source / evidence: the exploratory run (Phase 3 proposal).
- How it is validated: all 451 tests pass (2026-10-24).
- Proposed by AI, approved by me.

## D38: Where numerical defaults live
- Phase / date: Phase 3 / 2026-10-24
- Options considered: (a) function defaults mirror `config.yaml` and a test checks they match; (b) read config.yaml on import; (c) no defaults.
- Decision: **(a)**. The `numerics:` and `verification:` sections are in config.yaml and validated by `config.py`.
- Justification: The methods stay independent of the working folder, and drift between code and config is caught automatically.
- Source / evidence: found while implementing: PyYAML reads `1.0e10` as text; it must be written `1.0e+10`. A note is in config.yaml, and `config.py` rejects the text value.
- How it is validated: `tests/test_numerics_defaults.py`.
- Proposed by AI, approved by me.

---

# Phase 4: degradation models

All evidence uses the **training races only**: Hungary 2022–2024, 1,991 clean C3 laps in 87 stints, fuel-corrected, tyre ages 2–41 laps.

## D39: Base pace — a separate offset per stint, degradation shared per compound
- Phase / date: Phase 4 / 2026-10-24
- Options considered: (a) pool everything (one base time per compound); (b) a separate base-time offset per stint, with the degradation parameters shared per compound; (c) one offset per race.
- Decision: **(b)**. `lap_time = offset_of_its_stint + d(tyre_age)`, with d(0) = 0.
  - Fitted with the within-stint transformation (Frisch–Waugh–Lovell): subtract each stint's mean, fit without an intercept, then recover the offsets as stint means. Residual degrees of freedom = n − stints − parameters.
  - Interface: `fit(tyre_age, lap_time, stint_id=None)`; `predict(tyre_age, base_time=None)` defaults to the median offset.
  - The lap time is `FuelCorrectedTime` and the tyre age is `TyreLife`.
- Justification: Separates car pace from tyre wear without modelling car performance (D6 amendment).

  | | Pooled (a) | Per-stint offsets (b) |
  |---|---|---|
  | Slope | 0.0730 s/lap | 0.0705 s/lap |
  | Residual std | 0.717 s | **0.450 s** |

  The offsets spread with a std of 0.59 s (83.8–86.3 s).
- Source / evidence: the exploratory run above; the FWL theorem (e.g. Greene, *Econometric Analysis*, partitioned regression — **to verify**).
- How it is validated: `test_polynomial_matches_full_dummy_variable_regression` (identical coefficients and standard errors to an explicit one-column-per-stint regression with numpy `lstsq`, for degrees 1–3).
- Proposed by AI, approved by me.

## D40: Candidate polynomial degrees
- Phase / date: Phase 4 / 2026-10-24
- Options considered: {1, 2}; {1, 2, 3}; {1 … 5}.
- Decision: **{1, 2, 3}**, default 1. Phase 5 cross-validation chooses. The polynomial has no constant term (the offsets carry it), and the inputs are scaled (D35).
- Justification: BIC (exploratory) is lowest for degree 1: −2601.6, against −2594.1 for degree 2 and −2590.3 for degree 3. Degrees 4–5 add nothing.
- Source / evidence: real-data fits.

  | Degree | Coefficients (± bootstrap SE) | 95% CI | Note |
  |---|---|---|---|
  | 1 | c1 = 0.0705 ± 0.0031 s/lap | 0.065–0.077 | |
  | 2 | c2 = 3.4e-5 ± 2.7e-4 | includes 0 | no curvature detected |
  | 3 | all three coefficients | all include 0 | |

- How it is validated: `test_polynomial_recovers_linear_rate`, `test_polynomial_recovers_quadratic`.
- Proposed by AI, approved by me.

## D41: Wear ODE — bracket for b, the b → 0 limit, and the search
- Phase / date: Phase 4 / 2026-10-24
- Options considered: bracket [0, 0.1], [−0.1, 0.1] or [−0.2, 0.2]; search method; root-finding tolerances.
- Decision:
  - **Unit response:** d = a·g_b, where dg/dn = 1 + b·g, g(0) = 0. For fixed b, a comes from my linear least squares (FWL).
  - **Bracket:** b ∈ **[−0.1, 0.1]**.
  - **Search:** a 21-point grid scan of RSS(b), then **bisection** on dRSS/db (my central difference) between the grid neighbours of the lowest point. Secant and Newton (second difference) are selectable.
  - **Tolerances for this search: `xtol = 1e-8`, `ftol = 0`.**
  - **Boundary:** an optimum at a bracket end is flagged.
  - **Exact solution:** g_b = `expm1(b·n)/b`, and exactly n at b = 0.
- Justification:
  - The best b is about 0, so a bracket starting at 0 would put the optimum on its edge.
  - |b| = 0.1 means a 60× rate change over 41 laps, which is generous.
  - dRSS/db has round-off noise of about 1e-8, so the residual test cannot reach 1e-12.
  - `expm1` avoids cancellation for tiny b·n.
- Source / evidence (real data):

  | Item | Result |
  |---|---|
  | Fit | **a = 0.06932 s/lap** (bootstrap SE 0.0102), **b = +0.00101 /lap** (bootstrap SE 0.0083; 95% CI −0.015 to +0.017, so no detectable cliff) |
  | Bisection | 21 iterations |
  | RK4, RK45, exact × bisection, secant, Newton | identical a and b (bisection 21, secant 5, Newton 3 iterations) |
  | **Benchmark** `scipy.optimize.least_squares` on the full 89-parameter problem | a = 0.069319, b = +0.001013, RSS 385.2655 — identical |

  The per-race best b values are −0.009, +0.010 and +0.002, all inside the bracket.
- How it is validated: `test_wear_ode_recovers_parameters` (b = 0.03, 0 and −0.03), `test_wear_ode_matches_scipy_least_squares_benchmark`, `test_wear_ode_solvers_and_root_finders_agree` (9 combinations), `test_wear_ode_flags_bracket_boundary`, `test_exact_solution_b_to_zero_limit` (Taylor series to 1e-12).
- Proposed by AI, approved by me.

## D42: ODE solver inside the fit
- Phase / date: Phase 4 / 2026-10-24
- Options considered: (a) RK4, h = 1 lap; (b) RK45, integrated segment by segment between consecutive tyre ages; (c) the exact solution.
- Decision: **(a) RK4, 1-lap steps (default)**. RK45 (rtol 1e-10, atol 1e-12) and the exact solution are selectable. The exact solution is used to verify the numerical one on every fit (`ode_check_max_error`).
- Justification: RK4 is smooth in b, so RSS(b) can be differentiated reliably. An adaptive solver changes its steps with b, so it needs tight tolerances.
- Source / evidence: on real data, the RK4 vs exact error is **2.7e-14 s**; RK45 gives the same b as RK4 to all printed digits.
- How it is validated: `test_rk4_unit_response_matches_exact` (b from −0.1 to 0.1, ages 0–55), `test_rk45_unit_response_matches_exact`.
- Proposed by AI, approved by me.

## D43: Non-negative degradation
- Phase / date: Phase 4 / 2026-10-24
- Options considered: (a) enforce a ≥ 0 for the ODE and only check and report for the polynomial and KNN; (b) report only, for every model; (c) reparametrise a = eᶿ.
- Decision: **(a)**.
  - **ODE:** for n > 0, g_b(n) > 0 for every b, so d ≥ 0 exactly when a ≥ 0. If least squares gives a < 0 for some b, the constrained optimum for that b is a = 0 (exact for a one-variable quadratic). It is flagged, and the analytic SEs become NaN.
  - **Polynomial and KNN:** d is checked on ages 0 … max; it is flagged if min d < −**0.01 s**.
- Justification: Forcing a shape onto the polynomial and KNN would hide what the data says.
- Source / evidence: real data: no violations. a = 0.069 > 0; min d = 0 for the polynomials; min d = 0.019 s for KNN.
- How it is validated: `test_wear_ode_clamps_negative_wear_rate`, `test_polynomial_flags_negative_degradation`, `test_knn_model_flags_negative_degradation`.
- Proposed by AI, approved by me.

## D44: KNN
- Phase / date: Phase 4 / 2026-10-24
- Options considered:
  - Base pace: (a) offsets from the linear per-stint model; (b) backfitting; (c) stint means.
  - Ties: (a) include every point tied with the k-th distance; (b) exactly k, broken by row order.
- Decision:
  - **Feature:** tyre age only, with no scaling (one feature).
  - **Base pace (a):** subtract the offsets from the linear per-stint model before KNN.
  - **Search:** brute-force Euclidean distances.
  - **Ties (a):** include all points tied with the k-th distance, so results don't depend on row order.
  - **Candidates:** k ∈ {10, 25, 50, 100, 200, 400}; weights uniform (default, k = 50) or inverse-distance (exact matches take all the weight, sklearn's rule).
  - KNN does not extrapolate beyond the oldest training age (41 laps).
- Justification: Degradation is nearly linear (D40, D41), so the linear offsets are accurate. One feature means scaling cannot change which neighbours are nearest.
- Source / evidence:
  - Identical to `sklearn.neighbors.KNeighborsRegressor` (to 1e-12) on tie-free data.
  - Real-data finding: **with whole-lap tyre ages, inverse-distance weighting uses only the laps at exactly the query age, whatever k is.** All six distance-weighted candidates give the same curve (d(5, 20, 35) = 0.35, 1.33, 2.48 s).
  - Large uniform k flattens the oldest ages: d(35) = 2.53 s at k = 10 but 1.94 s at k = 400.
  - Both effects are for Phase 5 cross-validation to judge.
- How it is validated: `test_knn_matches_sklearn_on_tie_free_data` (k = 1, 5, 15 × both weightings), `test_knn_includes_all_tied_neighbours`, `test_knn_distance_weighting_with_exact_match`, `test_knn_model_recovers_degradation_curve`.
- Proposed by AI, approved by me.

## D45: Parameter uncertainty
- Phase / date: Phase 4 / 2026-10-24
- Options considered: (a) analytic standard errors from the residuals; (b) a bootstrap resampling individual laps; (c) a bootstrap resampling whole stints.
- Decision: report **both** (a) and (c).
  - **(a) Analytic:** σ²(XᵀX)⁻¹ with stint-corrected degrees of freedom; for the ODE, Gauss–Newton with the b-derivative by central difference.
  - **(c) Stint bootstrap:** B = 200 resamples, seed 42, 95% percentile CI. A stint drawn twice counts as two stints.
  - **The bootstrap is the main uncertainty for Phase 7.**
- Justification: The lag-1 within-stint residual correlation is a median of 0.45 (IQR 0.24–0.64), so the analytic SEs, which assume independent laps, are too small.
- Source / evidence: real data, **bootstrap SE ÷ analytic SE = 2.4 (c1), 2.2 (ODE a), 2.2 (ODE b)**, larger than the 1.6 I estimated in the proposal. Bootstrap run times: 0.2 s (polynomial) and 16 s (ODE) for B = 200.
- How it is validated: `test_bootstrap_agrees_with_analytic_se_for_independent_noise` (ratio 0.7–1.4), `test_bootstrap_exceeds_analytic_se_for_correlated_noise` (AR(1) ρ = 0.6: ratio > 1.2), `test_bootstrap_is_reproducible_with_a_seed`.
- Proposed by AI, approved by me.

## D46: Model interface, compound check, defaults
- Phase / date: Phase 4 / 2026-10-24
- Options considered: n/a (interface).
- Decision:
  - **Constructor:** each model takes a Pirelli compound code (checked against C0–C6; "HARD" is rejected).
  - **Methods:** `fit`, `predict`, `degradation`, `params()` (dict), `summary()` (text) and, for the polynomial and ODE, `bootstrap()`.
  - **Defaults:** the `models:` section of config.yaml, mirrored in the code and checked by a test (as D38).
  - **Not fitted:** using a model before `fit` raises `NotFittedError`, a `ValueError`.
- Justification: One interface for Phase 5; `stint_id` added for D39.
- Source / evidence: n/a.
- How it is validated: the shared tests in `tests/test_models.py` (empty or mismatched inputs, NaN, negative age, unknown compound, use before fit); `test_model_defaults_match_config`.
- Proposed by AI, approved by me.

---

# Phase 5: validation and model comparison

**Statement for the report:** model selection used leave-one-race-out cross-validation on the training races only (Hungary 2022, 2023, 2024). The cross-validation stage never loads the 2025 test race; `scripts/compare_models.py --stage cv` asserts this. The selection was frozen in `reports/model_selection.json` (timestamp and git commit inside) **before** any test evaluation (D55).

All numbers below come from `reports/phase5_cv_summary.csv` and the other `reports/phase5_*.csv` files.

## D47: Metrics
- Phase / date: Phase 5 / 2026-10-24
- Options considered: RMSE or MAE as the primary metric.
- Decision: **RMSE is primary.** Also reported: MAE, max |error|, R² and bias (the mean of predicted − actual) [s/lap].
- Justification:
  - RMSE is what least squares minimises, so selection and fitting agree, and it penalises large misses.
  - Bias matters because strategy adds lap times together.
  - R² is inflated by the anchored base pace (even the baseline gets a large R²), so it is not used for selection.
- Source / evidence: n/a.
- How it is validated: `test_metrics_hand_computed` and `test_metrics_second_example` (worked by hand in the test comments).
- Proposed by AI, approved by me.

## D48: Cross-validation scheme and selection rule
- Phase / date: Phase 5 / 2026-10-24
- Options considered: (a) leave one race out; (b) grouped 5-fold by stint.
- Decision:
  - **Scheme (a):** leave one race out on the training races, 3 folds. Splits are by race, never by random lap; the reason is written as a comment in `validation.py`.
  - **Selection rule:**
    1. Best hyperparameter per family by mean CV RMSE.
    2. Among the family winners that pass D51, the **simplest within one standard error of the best** (Hastie, Tibshirani & Friedman, *ESL* §7.10 — **to verify**). Complexity: polynomial degree d → d; wear ODE → 2; KNN → 10.
  - Only accepted candidates (D51) are eligible. This combination was implied by the proposal and is recorded here explicitly.
  - **ODE solver tolerance is not tuned:** every solver gives the same b (D41).
- Justification: Leaving out a whole race mirrors the real use: predicting a race the models haven't seen.
- Source / evidence (CV):

  | | C3 | C4 |
  |---|---|---|
  | Selected | polynomial degree 1 | polynomial degree 1 |
  | Mean CV RMSE | 0.633 ± 0.091 s | 0.851 ± 0.155 s |
  | Other family winners | wear ODE 0.633; KNN k = 100 uniform 0.639 | KNN k = 100 uniform 0.851 (nominally best, but the polynomial is simpler and within 1 SE) |

- How it is validated: `test_leave_one_race_out_folds_are_disjoint_and_complete`, `test_cross_validation_never_trains_on_the_held_out_race`, `test_one_standard_error_rule_prefers_simpler_model`.
- Proposed by AI, approved by me.

## D49: Predicting a held-out stint
- Phase / date: Phase 5 / 2026-10-24
- Options considered: (a) anchor on the stint's first m laps; (b) the median training offset; (c) an offset from all the stint's laps (leaks).
- Decision: **(a) with m = 3.** Offset = mean(lap time − d(age)) over the first 3 clean laps; only the remaining laps are scored.
- Justification: m trades the anchor error (≈ 0.45/√m) against laps left to score. The minimum stint length of 10 (D20) leaves at least 7 laps. It also matches a real race.
- Source / evidence (exploratory, polynomial degree 1, C3): CV RMSE 0.723 s at m = 1, **0.633 s at m = 3**, 0.594 s at m = 5.
- How it is validated: `test_anchored_prediction_is_exact_for_noise_free_data`, `test_anchor_uses_only_the_first_laps`.
- Proposed by AI, approved by me.

## D50: Baseline
- Phase / date: Phase 5 / 2026-10-24
- Options considered: n/a.
- Decision: a **no-degradation, constant-pace model** (d = 0), anchored exactly like the others. Every candidate must beat it in every fold.
- Justification: It shows what modelling degradation is worth.
- Source / evidence: baseline CV RMSE **1.168 s (C3), 1.132 s (C4)**; bias −0.87 and −0.63 s/lap, because it misses the wear. Every real candidate beat it in every fold.
- How it is validated: `test_cross_validation_recovers_degradation_and_beats_baseline`.
- Proposed by AI, approved by me.

## D51: Acceptance criteria
- Phase / date: Phase 5 / 2026-10-24
- Options considered: n/a.
- Decision: a candidate is **accepted** if all of these hold:
  1. it beats the baseline in every fold;
  2. **|mean CV bias| ≤ 0.10 s/lap**;
  3. it passes both physical checks (D53).
- Justification: 0.10 s/lap over a 35-lap stint is 3.5 s, about the pit-loss IQR (3.0 s, D24). So the model's error is no bigger than an uncertainty the strategy already carries.
- Source / evidence:

  | Compound | Accepted | Not accepted, and why |
  |---|---|---|
  | C3 | polynomial degrees 1–3, wear ODE, KNN k = 50, 100, 200 uniform | KNN k = 10, 25 (not monotonic); KNN k = 400 (bias −0.19); all distance-weighted KNN (not monotonic) |
  | C4 | polynomial degree 1, KNN k = 100 uniform | wear ODE (+0.129) and polynomial degree 2 (+0.134) (bias); polynomial degree 3 and most KNN (not monotonic) |

  Caveat: individual folds can exceed 0.10 s/lap — the largest per-fold bias is 0.18 s/lap for C3 polynomial degree 1 and 0.33 for C4. This is reported in `bias_max_abs_fold`.
- How it is validated: the `accepted` column in `phase5_cv_summary.csv`; `summarize_folds` is tested.
- Proposed by AI, approved by me.

## D52: Compounds in scope (amends D4)
- Phase / date: Phase 5 / 2026-10-24
- Options considered: C3 only; add C4; add C2/C5.
- Decision: **model C3 and C4** (`pirelli_compounds: ["C3", "C4"]`), each fitted and cross-validated separately.
  - C2 is excluded: only 2022 has it, so leave-one-race-out is impossible.
  - C5 is excluded: 24 clean laps in the training races.
- Justification: The ranking needs two compounds, and Phase 6 needs two different compounds for a legal one-stop race (this resolves OI-3).
- Source / evidence:
  - Clean training laps: C3 1,991 (87 stints); C4 921 (55 stints, data in all 3 races); C2 207 (2022 only); C5 24.
  - **Ranking** (linear rate, 95% bootstrap CI): C4 0.0714 s/lap [0.060, 0.087]; C3 0.0705 s/lap [0.065, 0.077]. **The two rates are not statistically distinguishable**; the ranking is reported, not forced.
- How it is validated: `test_rank_compounds_reports_without_forcing_an_order`; `reports/phase5_compound_ranking.csv`.
- Proposed by AI, approved by me.

## D53: Physical-consistency thresholds
- Phase / date: Phase 5 / 2026-10-24
- Options considered: monotonicity tolerance (a) 0; (b) 0.05 s; (c) 0.1 s.
- Decision:
  - Non-negative: d ≥ −0.01 s (as D43), on ages 0 … max.
  - Increasing: d(n+1) ≥ d(n) − **0.05 s** on a 1-lap grid.
- Justification: 0.05 s is about the noise in an average over one tyre age (0.45/√59).
- Source / evidence:
  - KNN with small k, or with distance weighting, drops by 0.08–0.62 s at sparsely sampled old ages, and fails.
  - The polynomial degree 1 and wear-ODE curves only ever increase.
- How it is validated: `test_monotonic_check`; the columns `monotonic_ok` and `largest_drop`.
- Proposed by AI, approved by me.

## D54: Residual analysis and the leftover fuel effect
- Phase / date: Phase 5 / 2026-10-24
- Options considered: (a) residuals against lap number only; (b) also a diagnostic model with one offset per driver per race.
- Decision:
  - **Plots:** CV residuals of the selected model against tyre age and against lap number (binned means ± 2 SE): `reports/figures/phase5_residuals.png`, `phase5_residual_bins.csv`.
  - **Fuel diagnostic:** one offset per driver per race, a tyre-age slope per compound, plus a lap-number coefficient (= leftover fuel effect). Bootstrap that resamples whole driver-races (the units that own an offset; this is the stint bootstrap's principle applied to this model), B = 200, seed 42.
- Justification: Within a stint, lap number and tyre age both rise by 1 per lap, so with per-stint offsets a residual-vs-lap-number slope is 0 by construction (exploratory: exactly 0.00000).
- Source / evidence:
  - **Leftover fuel effect: +0.00076 s/lap, 95% CI [−0.0031, +0.0042]** (58 driver-races). Not flagged, so k_fuel = 0.046 is supported.
  - C3 residuals stay within about ±0.2 s across tyre ages.
  - **C4 residuals reach +0.6 to +1.3 s beyond about 25 laps of tyre age** (see OI-6).
- How it is validated: `test_leftover_fuel_effect_is_recovered` (a planted 0.02 s/lap is recovered and flagged), `test_no_leftover_fuel_effect_is_not_flagged`, `test_binned_residuals`.
- Proposed by AI, approved by me.

## D55: Test-set firewall
- Phase / date: Phase 5 / 2026-10-24
- Options considered: n/a.
- Decision:
  - **Two stages** in `scripts/compare_models.py`. `--stage cv` loads only the training races, asserts that no test year is present, and writes `reports/model_selection.json` (selection, training races, test races *not used*, k_fuel, anchor, UTC timestamp, git commit).
  - `--stage test` refuses without that file (`FirewallError`), fits the frozen family winners and the baseline on all training races, and scores 2025 **once**.
  - **A repeat needs `--force`.** Every test run is appended to `reports/test_runs.log`.
- Justification: Makes it possible to state, with evidence, that the test data did not influence model selection.
- Source / evidence: `reports/model_selection.json` was written by the CV run on 2026-10-24.
- How it is validated: `test_test_stage_refuses_without_selection`, `test_selection_round_trip`, `test_test_run_happens_once_unless_forced`.
- Proposed by AI, approved by me.

## Phase 5 final test result (2025 Hungarian GP, evaluated once)
- **Sequence:**
  1. Phase 5 code committed (`7f7d6eb`).
  2. CV stage rerun on that commit; the selection written.
  3. `reports/model_selection.json` committed (`a64967b`).
  4. **Then** `--stage test` run once (2026-10-24T11:40:44Z, logged in `reports/test_runs.log`).

  Git history therefore shows the selection was fixed before the test.
- **Result** (`reports/phase5_test_results.csv`, anchored on the first 3 laps of each stint):

  | Compound | Model | Test RMSE | Test bias | Baseline RMSE | CV RMSE |
  |---|---|---|---|---|---|
  | C3 | **polynomial degree 1 (selected)** | **0.942 s** | **+0.276 s/lap** | 1.311 s | 0.633 s |
  | C3 | wear ODE | 0.942 s | +0.273 | | |
  | C3 | KNN k = 100 uniform | 0.919 s | +0.201 | | |
  | C4 | **polynomial degree 1 (selected)** | **1.042 s** | **+0.536 s/lap** | 1.082 s | 0.851 s |
  | C4 | KNN k = 100 uniform | 0.962 s | +0.400 | | |

- **Assessment against D51:**
  - Both selected models still beat the baseline (C4 only narrowly).
  - **Both fail the bias criterion (≤ 0.10 s/lap) on the test race:** they predict more degradation than occurred.
- **Post-test diagnostic** (descriptive only, NOT used to change any selection). Linear degradation rate per year, with 95% stint-bootstrap CI:

  | Compound | 2022 | 2023 | 2024 | 2025 |
  |---|---|---|---|---|
  | C3 | 0.072 (as MEDIUM) | 0.063 | 0.075 | **0.045 [0.033, 0.059]** |
  | C4 | **0.134 (as SOFT)** | 0.058 | 0.065 | **0.050 [0.037, 0.065]** |

  - 2025 wear was lower than in every training year.
  - The 2025 C3 stints reached a tyre age of **55** laps (the training maximum was 41), so part of the test is extrapolation.
- See OI-7 for what this means for Phase 6.

## Track temperature (reviewed after the test; not modelled)
- Phase / date: Phase 5 / 2026-10-24
- Options considered: (a) add track temperature to the model; (b) report it as a likely contributor and cover it through the year-to-year spread in the Phase 7 sensitivity analysis; (c) also record per-lap weather (changing D8) for plots and future work.
- Decision: **(b). Track temperature is not a model input.** Option (c) is left open: D8 still skips weather data.
- Justification:
  1. Track temperature is essentially one value per race: 4 data points, only 3 in training. That is far too few to estimate an effect.
  2. Between races it is confounded with car development, Pirelli's compound revisions, 2022's rain and the different tyre roles.
  3. Within a race it drifts roughly with lap number, which is already tied to tyre age and fuel load, so it cannot be separated from them.
- Source / evidence: race weather (FastF1 mirror for 2022, OpenF1 `weather` for 2023–2025), read-only check on 2026-10-24:

  | Race | Track temperature mean (min–max) | Air temperature | Rain recorded | C3 wear rate [s/lap] |
  |---|---|---|---|---|
  | 2022 | 26.7 °C (22.8–29.3) | 18.6 °C | yes | 0.072 |
  | 2023 | 48.6 °C (45.5–51.4) | 28.8 °C | no | 0.063 |
  | 2024 | 44.9 °C (40.4–49.7) | 28.8 °C | no | 0.075 |
  | 2025 (test) | 32.0 °C (30.6–36.5) | 22.0 °C | no | 0.045 |

  There is no clean temperature trend: 2022 was the coolest race but had high wear, and 2023 was the hottest but had the lowest training-year wear. Cool conditions alone do not explain 2025's low wear.
- How it is validated: n/a. Reported in the discussion and limitations; covered by the Phase 7 rate range (OI-7 (d)).
- Proposed by AI, approved by me.

## Factors affecting tyre wear: review of what the model covers
- Phase / date: Phase 5 / 2026-10-24
- Options considered: add more factors to the model vs keep it and document them.
- Decision: **keep the model as it is; document all factors in the report's limitations.**
- Justification: With four races, every extra factor would be estimated from too little data (as for temperature).
- Source / evidence: review of the pipeline.

  **Handled directly or indirectly:**

  | Factor | How |
  |---|---|
  | Tyre age | Modelled (`TyreLife`) |
  | Compound | Pirelli C-number, fitted per compound |
  | Fuel load **plus track evolution** | Fuel correction (D21–D22; see the restatement below) |
  | Car, driver and race pace | Per-stint offsets (D39) |
  | Pit laps, safety cars, yellow flags, first lap | Cleaning (D17–D18) |
  | Isolated slow laps | Outlier rule (D19) |
  | Earlier use of the set | Partly: `TyreLife` counts earlier laps, but not how hard they were run |

  **Not measurable from timing data (limitations):**
  - **Driver tyre management:** drivers on long stints save their tyres, which makes long stints look like they degrade less. This probably contributes to OI-6 (C4 levelling off) and to the 55-lap stints in 2025.
  - Tyre pressure and camber limits set by Pirelli per event.
  - Car setup and how tyre-friendly a car is.
  - The wear mechanism (graining, blistering, overheating), which the linear model averages over.
  - Track surface. **Not verified:** whether the Hungaroring was resurfaced between 2022 and 2025.

  **Checkable with our data, not run (see OI-8):**
  - wear rate by team;
  - dirty air (following within about 1–2 s);
  - a damp track in 2022;
  - track evolution, which is part of the fuel coefficient (below).
- How it is validated: n/a (documentation).
- Proposed by AI, approved by me.

## D22 restatement: the fuel coefficient also contains track evolution
As the track rubbers in, lap times fall lap by lap, exactly like burning fuel:
both effects grow linearly with lap number. The coefficient estimated from the
data, k_fuel = 0.046 s/lap (D22), is therefore **fuel load plus track
evolution combined**. The correction removes both, so no result changes, but
the report should describe it that way. The leftover-fuel diagnostic (D54) is
consistent with this: +0.0008 s/lap, CI includes 0.

---

# Phase 6: pit-stop strategy

**For Phase 6 only, the decision protocol was overridden:** every decision below was made by the AI and implemented straight away. **Each is to be reviewed by me.** Problems met along the way are in `CHALLENGES.md` (C1–C6). Evidence: `reports/phase6_*.csv` and `reports/figures/phase6_*.png` from `scripts/optimise_strategy.py`.

## D56: Data window for the strategy models (resolves OI-7, part 1)
- Phase / date: Phase 6 / 2026-10-24
- Options considered: (a) the frozen models trained on 2022–24; (b) refit on 2022–2025; (c) refit on races where each compound had the same role; (d) year-to-year spread as uncertainty.
- Decision: **(c) and (b): refit the model form selected in Phase 5 (polynomial degree 1 for both compounds) on 2023, 2024 and 2025**, the years with the C3/C4/C5 allocation. 2022 is excluded (C3 was the MEDIUM, C4 the SOFT, and some rain was recorded). **(d) is deferred to Phase 7.**
- Justification: Each compound keeps the same role, and the newest year is included. The test has already run and is locked, so refitting is allowed. **The Phase 5 test result (RMSE 0.94/1.04 s) remains the reported accuracy; strategy numbers for 2025 are in-sample.**
- Source / evidence: refit rates C3 0.0597 s/lap [0.051, 0.070], C4 0.0551 s/lap [0.045, 0.066] (stint bootstrap). C4 in-sample residuals are within ±0.2 s at every tyre age (OI-6 had shown +0.6 to +1.3 s on the 2022–24 data).
- How it is validated: Phase 7 sensitivity; `reports/phase6_inputs.csv`.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D57: Demonstration race and reference car
- Phase / date: Phase 6 / 2026-10-24
- Options considered: n/a (the only circuit in scope).
- Decision: **the Hungarian GP, 70 laps** (the same in all 2023–25 races; `race.total_laps_override` remains available). The reference car is the "typical car": its new-C3 base pace is the **median C3 stint offset**, 85.02 s fuel-corrected to full fuel.
- Justification: Base pace adds the same amount to every strategy with the same number of laps per compound, so it hardly affects the comparison; a typical value gives realistic totals.
- Source / evidence: `TotalLaps` = 70 for every race.
- How it is validated: n/a.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D58: Pit loss
- Phase / date: Phase 6 / 2026-10-24
- Options considered: the D24 estimate (2022–24, 21.51 s); a re-estimate on the strategy years; an override.
- Decision: **re-estimate on 2023–2025 with the D24 method: median 20.89 s** (IQR 19.82–22.31 s, 105 green-flag stops). `pit_loss_override` stays null.
- Justification: Consistent with D56. Pit loss fell between 2022 and 2024, so 2022 would bias it upwards.
- Source / evidence: race medians 21.48 s (2023), 20.29 s (2024), 20.65 s (2025).
- How it is validated: D24 tests; the IQR feeds the Phase 7 sensitivity.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D59: Compounds and strategy types
- Phase / date: Phase 6 / 2026-10-24
- Options considered: include or exclude C5; one-stop only, or two-stop as well.
- Decision:
  - **C3 and C4 only.** C5 is excluded: 62 clean laps, 5 stints, ages ≤ 16 in 2023–25.
  - **One-stop:** C3 → C4 and C4 → C3.
  - **Two-stop:** every three-stint sequence from {C3, C4} that uses both compounds (6 sequences), by brute force.
- Justification: C5 is too sparse to model, so the real "soft" option is missing; that is a limitation. Two-stops are cheap to enumerate (at most 973 combinations each).
- Source / evidence: clean-lap counts.
- How it is validated: `test_two_stop_matches_exhaustive_enumeration`, `test_compare_strategies_ranks_and_agrees_across_methods`.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D60: Compound pace difference for the same car
- Phase / date: Phase 6 / 2026-10-24
- Options considered: (a) the difference of the two compounds' median offsets; (b) the pooled paired difference for the same driver and race; (c) **the order-balanced paired difference**.
- Decision: **(c)**. Base pace of a new C4 = base C3 + δ, with **δ = −0.080 s** (C4 faster). δ is the mean of the paired medians for the two stint orders: +0.154 s (C4 first, n = 35) and −0.315 s (C3 first, n = 8).
- Justification:
  - (a) mixes different cars (CHALLENGES C1).
  - (b) is biased by stint order: later stints look faster, and C4 usually starts the race (CHALLENGES C2).
  - Averaging over the two orders cancels a common order effect.
- Source / evidence: CHALLENGES C1, C2. The plausible range is −0.32 to +0.15 s; **this is the least certain input.**
- How it is validated: `test_order_balanced_compound_delta_removes_order_effect` (a planted δ = −0.1 s is recovered despite a 0.25 s order effect); Phase 7 varies δ.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D61: New or used tyres
- Phase / date: Phase 6 / 2026-10-24
- Options considered: new sets for every stint; used sets for the start (qualifying wear).
- Decision: **every stint starts on a new set** (tyre age 1 on its first lap).
- Justification: Hard and medium race sets are normally new. Used-set wear is not modelled beyond `TyreLife`.
- Source / evidence: n/a (modelling assumption).
- How it is validated: n/a.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D62: Fuel effect in the predicted race time
- Phase / date: Phase 6 / 2026-10-24
- Options considered: report fuel-corrected totals; add the fuel effect back.
- Decision: **add it back.** Lap n's time is base + d(age) − k_fuel·(n − 1), with k_fuel = 0.046 s/lap (fuel plus track evolution, D22 restatement).
- Justification: Gives real race times. The fuel term totals k_fuel·N(N − 1)/2 = 111.09 s for every strategy, so it never changes the ranking.
- Source / evidence: n/a.
- How it is validated: `test_fuel_effect_shifts_every_strategy_by_the_same_amount`.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D63: Maximum stint length (no extrapolation)
- Phase / date: Phase 6 / 2026-10-24
- Options considered: (a) the largest observed tyre age (C3 55, C4 42); (b) **the largest tyre age with at least 5 clean laps**; (c) at least 10 clean laps (C3 36, C4 31).
- Decision: **(b): C3 at most 40 laps, C4 at most 35.** Applied in every optimiser.
- Justification: (a) would trust a single 55-lap stint; (c) would forbid well-supported stints. Resolves OI-6 point 2.
- Source / evidence: lap counts per tyre age, 2023–25.
- How it is validated: `test_stint_limit_moves_optimum_to_window_edge`, `test_stint_longer_than_limit_is_rejected`. **The limit is binding for the one-stop result (CHALLENGES C5).**
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D64: Continuous relaxation, rounding and checking
- Phase / date: Phase 6 / 2026-10-24
- Options considered: piecewise-linear interpolation of the integer race times; **a smooth extension of the degradation sum**.
- Decision:
  - **Smooth extension:** each stint's sum d(1) + … + d(n) is replaced by ∫ from ½ to n + ½ of d (midpoint rule). This is exact for linear d at every integer, and in closed form for the polynomial and wear-ODE models. KNN has none, so it uses brute force only.
  - **Derivative:** dT/dL with my central difference; default step 6e-6 × L ≈ 2e-4 laps, which is fine here (OI-5).
  - **Root finding:** my secant (started at the feasible-window ends) and Newton (second difference, started at the window centre), with xtol = 1e-6 laps and ftol = 0 (round-off noise in the derivative).
  - **Rounding:** candidates floor(root) − 1 … ceil(root) + 1, clipped into the feasible window, evaluated with the exact integer race time, and the fastest taken. A root outside the window marks `constraint_active`. If root finding fails, the window ends are compared and a note is recorded. **Brute force is the reference.**
- Justification: Piecewise-linear interpolation has a derivative that is constant between integers and jumps at each integer, so secant and Newton cannot work on it.
- Source / evidence:

  | Strategy | Root | Iterations (secant / Newton) | Evaluations (secant / Newton / brute force) |
  |---|---|---|---|
  | C3 → C4 | 32.890 | 2 / 3 | 9 / 18 / 6 |
  | C4 → C3 | 37.110 | 2 / 2 | 9 / 13 / 6 |

  All three methods agree on pit lap 35 for both orders.
- How it is validated: `test_continuous_relaxation_finds_analytic_optimum` (root 40.1 on the analytic case, both methods, ≤ 3 iterations), `test_rounding_checks_neighbours`, `test_continuous_relaxation_equals_race_time_at_integers_for_linear_models`, `test_wear_ode_continuous_optimum_matches_brute_force`.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D65: Which degradation model the strategy uses
- Phase / date: Phase 6 / 2026-10-24
- Options considered: the Phase 5 selected model per compound; another family winner.
- Decision: **the model selected in Phase 5** (read from `reports/model_selection.json`): polynomial degree 1 for C3 and C4, refitted per D56.
- Justification: Follows the frozen selection. The KNN alternative is a Phase 7 model-choice sensitivity, which OI-6 requires because the optimal C4 stint (35 laps) is above 25 (C5).
- Source / evidence: `reports/phase6_inputs.csv`.
- How it is validated: n/a.
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## D66: Wear rate by team (OI-8 diagnostic, reported only)
- Phase / date: Phase 6 / 2026-10-24
- Options considered: n/a.
- Decision: report the linear rate per team (teams with at least 4 stints) in `reports/phase6_team_degradation.csv`. The model is unchanged (one rate per compound, D39). The 2022 damp-track check is skipped, since 2022 is dropped (D56).
- Justification: Quantifies what the shared-rate assumption hides.
- Source / evidence:
  - **C3: 0.039 s/lap (Mercedes) to 0.074 s/lap (Kick Sauber).**
  - **C4: 0.029 s/lap (Aston Martin) to 0.079 s/lap (Ferrari).**
  - That is a factor of about 2–3 between cars (analytic SEs 0.003–0.008). One shared rate describes a typical car only.
- How it is validated: n/a (diagnostic).
- **Decided by AI without prior approval (Phase 6), to be reviewed by me.**

## Phase 6 result (in-sample, typical car, Hungarian GP)
| Rank | Strategy | Stints (laps) | Predicted time | Gap |
|---|---|---|---|---|
| 1 (tie ×3) | two stops, one C3 stint and two C4 stints in any order | 21 C3 + 24 C4 + 25 C4 | 5926.50 s | 0 |
| 4 (tie ×3) | two stops, two C3 stints and one C4 | 22 + 22 C3, 26 C4 | 5929.66 s | +3.16 s |
| 7 (tie ×2) | **one stop at lap 35** (C3 → C4 or C4 → C3) | 35 + 35 | 5930.83 s | +4.33 s |

The one-stop optimum is constrained by D63. The unconstrained root is 32.89 laps (C3 first), which would need a 37-lap C4 stint. Margins are small, and ties come from the model having no order effect (CHALLENGES C6). **Phase 7 must test whether "two stops" survives the uncertainty in pit loss, compound delta, wear rate and model choice.**

---

# Phase 7: sensitivity analysis

**For Phase 7 only, the decision protocol was overridden:** every decision below was made by the AI and implemented straight away. **Each is to be reviewed by me.** Problems met are in `CHALLENGES.md` (C7–C10). Evidence: `reports/phase7_*.csv` and `reports/figures/phase7_*.png` from `scripts/sensitivity_analysis.py`; settings in the `sensitivity:` section of config.yaml.

## D67: Inputs and the ranges tested (one at a time)
- Phase / date: Phase 7 / 2026-10-24
- Options considered: ±1/±2 SE for every input; physically motivated ranges per input; the full range only.
- Decision: physically motivated ranges, each applied alone around the Phase 6 nominal:

  | Input | Nominal | Values tested | Why this range |
  |---|---|---|---|
  | Fuel coefficient k_fuel (refits everything) | 0.046 | 0.015, 0.070 | D22 range: published 0.01–0.045 s/kg |
  | Pit loss | 20.89 s | 19.82, 22.31 s | IQR of the 2023–25 stops (D58) |
  | C3 wear rate | 0.0597 s/lap | ±1 and ±2 SE (SE = 0.00474) | stint bootstrap (D45) |
  | C4 wear rate | 0.0551 s/lap | ±1 and ±2 SE (SE = 0.00511) | stint bootstrap (D45) |
  | Compound delta C4 − C3 | −0.080 s | −0.315, +0.154 s | the two stint-order medians (D60) |
  | Year-to-year wear (C3 and C4 together) | 0.0597 / 0.0551 | 2025 (0.0451 / 0.0496) and 2024 (0.0749 / 0.0651) | lowest- and highest-wear years; OI-7 (d) |
  | Degradation model | polynomial degree 1 | polynomial degree 2, wear ODE, KNN k = 100 uniform | the other Phase 5 candidates; OI-6 point 3 |
  | Stint-limit rule | ≥ 5 laps | ≥ 3, ≥ 10 laps | D63 alternatives |

- Justification: Each range reflects how uncertain that input really is, rather than a uniform ±10 %. The year range resolves OI-7 (d), and the KNN model resolves OI-6 point 3.
- Source / evidence: `reports/phase7_oat.csv`.
- How it is validated: the nominal run reproduces Phase 6 exactly (5930.83 / 5926.50 s, L* = 32.890).
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## D68: Perturbation size for the central-difference coefficients
- Phase / date: Phase 7 / 2026-10-24
- Options considered: a relative step of 0.1 %, 1 % or 10 %.
- Decision:
  - **h = 1 % of the nominal value** for k_fuel, pit loss and the two wear rates.
  - **h = 0.01 s** (absolute) for the compound delta, whose nominal is close to 0.
  - Every relative derivative is repeated with 0.1 %, 1 % and 10 % steps (`phase7_step_size_check.csv`).
- Justification: The outputs are only piecewise smooth (integer argmin, medians). A step much larger than 1 % crosses jumps; a step much smaller than 0.1 % would only amplify round-off.
- Source / evidence:
  - Derivatives with respect to pit loss are identical at all three steps (+1, +2, −1).
  - Derivatives with respect to the wear rates agree at 0.1 % and 1 %; small changes appear only at 10 %.
  - **Derivatives with respect to k_fuel differ by about 3 % between 0.1 % and 1 %, and badly at 10 %** (one-stop time 1149 / 1158 / 745) — see C8. They are reported as indicative only.
- How it is validated: `test_central_difference_error_is_second_order`, `test_step_size_check_detects_a_kink`.
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## D69: Outputs analysed, and the integer pit lap
- Phase / date: Phase 7 / 2026-10-24
- Options considered: differentiate the integer pit lap; use the continuous optimum; OAT only.
- Decision:
  - **Derivatives are taken of smooth outputs only:**
    - L* (the continuous, UNCONSTRAINED optimum, C3 first; computed with the stint limits relaxed, C7);
    - the best one-stop time;
    - the best two-stop time;
    - **the margin** (one-stop minus two-stop time; > 0 means two stops are faster). This is the decision-relevant output.
  - **The integer pit lap appears only in the OAT ranges.**
- Justification: A finite difference of an integer is 0 or a jump. L* is smooth: its derivative agrees across steps (99.90 / 99.91 / 100.55 for k_fuel).
- Source / evidence: `phase7_tornado_pit_lap.csv`: the integer pit lap stays at 35–36 in almost every variation because the C4 stint limit pins it (C9).
- How it is validated: `test_linear_degradation_integral_and_optimum_sensitivity` (dL*/da1 matches the analytic derivative to 1e-4).
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## D70: Dimensionless coefficients
- Phase / date: Phase 7 / 2026-10-24
- Options considered: elasticity for every output; the absolute derivative only.
- Decision:
  - Report the **elasticity (dy/dx)·x/y** for L* and the race times.
  - Report **only the derivative** for the margin, since its nominal value of 4.3 s is close to 0 and changes sign, so a relative change is meaningless.
  - The delta's elasticity is reported but should be read with care (nominal −0.08 s).
- Justification: Race-time elasticities are tiny (at most 0.009) because the total is about 5900 s. The absolute derivatives [s per unit] are more informative for them.
- Source / evidence: `phase7_sensitivity_coefficients.csv`.

  | Input | Elasticity of L* |
  |---|---|
  | C3 rate | −0.53 |
  | C4 rate | +0.55 |
  | k_fuel | +0.14 |
  | pit loss | 0 |

  **Exact checks:**
  - d(one-stop time)/d(C3 rate) = 630 = 35·36/2, the sum of tyre ages over the 35-lap stint (the optimal laps do not move locally);
  - d(two-stop)/d(C3 rate) = 231 = 21·22/2;
  - d(margin)/d(pit loss) = −1.
- How it is validated: `test_coefficient_matches_exact_derivative`, `test_known_elasticities`, `test_margin_against_pit_loss_has_slope_minus_one`.
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## D71: Race used
- Phase / date: Phase 7 / 2026-10-24
- Options considered: n/a.
- Decision: the Phase 6 setup: Hungarian GP, 70 laps, typical car, models refitted on 2023–2025 (D56–D63).
- Justification: The sensitivity must be of the result actually reported.
- Source / evidence: nominal outputs equal Phase 6.
- How it is validated: n/a.
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## D72: How the fuel coefficient changes the fitted wear rate
- Phase / date: Phase 7 / 2026-10-24
- Options considered: n/a (an analysis requested by the brief).
- Decision: refit both compounds for k_fuel = 0, 0.005, …, 0.080 (`phase7_fuel_vs_rate.csv/.png`).
- Justification and finding: **d(rate)/d(k_fuel) = 1.000000 exactly, for both compounds.**
  - Within a stint, lap number = tyre age + a constant. Changing k by dk therefore adds dk·age + a constant to every lap.
  - The constant goes into the stint offset, and the degradation slope rises by exactly dk.
  - **With per-stint offsets (D39), the data cannot separate fuel burn from tyre wear. The wear rate is only as good as k_fuel.**
  - k_fuel itself was identified in D22 using driver-race offsets, across pit stops, which is the only place the two effects separate.
- Source / evidence: slope 1.000000000 for both compounds. Over the D22 range 0.015–0.070, the C3 rate moves from 0.029 to 0.084 s/lap.
- How it is validated: `test_fitted_rate_rises_one_for_one_with_fuel_coefficient` (exact on synthetic data).
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## D73: Break-even values
- Phase / date: Phase 7 / 2026-10-24
- Options considered: n/a.
- Decision: find where margin = 0 (one stop and two stops equal) for k_fuel and for pit loss, with my bisection (xtol 1e-5).
- Justification: Tells directly whether an input's plausible range can flip the decision.
- Source / evidence: `phase7_break_even.csv`.

  | Input | Break-even | Nominal | Plausible range | Can it flip the decision? |
  |---|---|---|---|---|
  | **k_fuel** | **0.0333 s/lap** (12 iterations) | 0.046 | 0.015–0.070 | **Yes**: break-even is inside the range |
  | **Pit loss** | **25.22 s** | 20.89 s | IQR 19.82–22.31 s | **No**: break-even is outside the IQR. Matches 20.89 + 4.33 because d(margin)/dP = −1 |

  In rule-of-thumb units, the k_fuel break-even is 0.0333 / 1.57 ≈ 0.021 s/kg, inside the published 0.01–0.045 s/kg range.
- How it is validated: the pit-loss break-even agrees with the analytic value to 1e-3.
- **Decided by AI without prior approval (Phase 7), to be reviewed by me.**

## Phase 7 result: is "two stops" robust?
One-at-a-time margins (one-stop minus two-stop) [s], from `phase7_oat.csv`, nominal **+4.33 s**:

| Input (range) | Margin low … high | Decision flips? |
|---|---|---|
| **k_fuel** (0.015 … 0.070) | **−6.28 … +13.01** | **Yes** (one stop below 0.0333) |
| **Year-to-year wear** (2025 … 2024) | **−1.27 … +10.49** | **Yes** (in a 2025-like low-wear year, one stop wins) |
| C3 rate (±2 SE) | +0.83 … +8.29 | no |
| Compound delta (−0.315 … +0.154 s) | +3.70 … +7.90 | no |
| Pit loss (IQR) | +2.91 … +5.40 | no |
| Model (polynomial degree 2, ODE, KNN) | +2.33 … +4.33 | no |
| C4 rate (±2 SE) | +4.33 … +4.73 | no |
| Stint-limit rule (≥ 3 / ≥ 10 laps) | +4.07 / one stop infeasible | no (≥ 10 makes a one-stop impossible, C7) |

**Conclusion:** two stops is the better strategy for most inputs. **But the decision rests on the fuel coefficient (equivalently, on how fast the tyres wear that year).** The fuel coefficient is the least certain assumption, and both it and year-to-year wear can reverse the ranking within their plausible ranges.
- **Model choice:** KNN's two-stop advantage is the smallest (+2.3 s), and the C4 rate barely matters. OI-6 is therefore not decisive.
- **Integer pit lap:** stays at 35–36 because the stint limit pins it (C9); the unconstrained L* ranges from 28.2 to 36.0 laps.

---

# Phase 8: performance and optimisation

**For Phase 8 only, the decision protocol was overridden:** every decision below was made by the AI and implemented straight away. **Each is to be reviewed by me.** Problems met are in `CHALLENGES.md` (C11–C15). Evidence: `reports/phase8_*.csv`, `reports/phase8_machine.json` and `reports/figures/phase8_*.png` from `scripts/benchmark.py`; settings in the `performance:` section of config.yaml.

**Machine** (`phase8_machine.json`): Windows 11 (10.0.26300), AMD64 processor (Family 25 Model 124), 12 logical CPUs, Python 3.13.15, NumPy 2.2.6, pandas 2.3.3, SciPy 1.15.3, scikit-learn 1.7.2. Other programs were running (an ordinary laptop).

## D74: How timing is measured
- Phase / date: Phase 8 / 2026-10-24
- Options considered: (a) one timed call per repeat; (b) calls per repeat calibrated to a minimum duration (as Python's `timeit` does); (c) the `timeit` module itself.
- Decision:
  - `time.perf_counter`; **1 unrecorded warm-up run, then 7 recorded repeats**, with `gc.collect()` before timing.
  - **Each repeat runs the function enough times to last at least 10 ms; the time per call is reported** (option (b), adopted after C12).
  - Report mean, std and minimum. Figures use the minimum.
  - Machine and library versions are saved with the results.
  - Memory uses `tracemalloc` (it sees NumPy buffers but not all compiled-library memory, so scikit-learn peaks are lower bounds).
- Justification: the warm-up removes first-call costs, repeats give the spread, and the minimum is least affected by other processes. **Option (a) failed for short functions:** std ÷ mean had a median of 67 % below 0.1 ms (C12). Calibration reduced it to 2.8 % (C13). Option (c) is equivalent but hides the method.
- Source / evidence: `phase8_ode.csv` before/after (C12, C13).
- How it is validated: `test_time_function_runs_warmup_and_repeats`, `test_time_function_calibrates_calls_for_short_functions`, `test_peak_memory_sees_numpy_allocations`.
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D75: ODE benchmark: problem, step sizes and RK45 tolerances
- Phase / date: Phase 8 / 2026-10-24
- Options considered: the fitted real ODE (b ≈ 0.001, almost linear) or the Phase 3 test problem.
- Decision: the wear ODE dd/dn = 0.05 + 0.03·d over 40 laps (the Phase 3 problem; with b ≈ 0 every method would look exact).
  - Fixed-step solvers: h = 40/n for n = 4, 8, …, 4096 (h from 10 down to 0.0098 laps).
  - RK45: rtol = 1e-2 … 1e-12 with atol = rtol/1000.
  - Plus the exact solution at 41 tyre ages.
- Justification: the range spans from unusable to round-off-limited accuracy for every method.
- Source / evidence (`phase8_ode.csv`, `phase8_ode_error_vs_cost.png`): the cheapest run reaching each accuracy.

  | Method | Error ≤ 1 ms (timing resolution) | Error ≤ 1e-8 s |
  |---|---|---|
  | Euler | 4096 f evaluations, 18 ms | — |
  | Heun | 128 f evaluations, 0.58 ms | — |
  | RK4 | **16** f evaluations, 0.09 ms | 256 f evaluations, 1.27 ms |
  | RK45 | 25 f evaluations, 0.19 ms | **103** f evaluations, 0.75 ms |
  | Exact solution | | **0.009 ms** for all 41 ages, error 0 |

  The exact solution is cheapest by far. RK4 runs at only **1.35 MFLOP/s (4.6 µs per f evaluation)**: run time is dominated by Python overhead, not arithmetic.
- How it is validated: errors match Phase 3's orders of convergence.
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D76: FLOP-counting convention
- Phase / date: Phase 8 / 2026-10-24
- Options considered: count only +, −, ×, ÷; also count special functions; weight special functions (for example exp ≈ 20).
- Decision:
  - **1 FLOP = one +, −, × or ÷ of floating-point numbers.**
  - exp, sqrt, a power, abs and max each count as **1** (stated wherever they are used; in hardware they cost about 10–50).
  - Indexing, comparisons and Python overhead are not counted.
  - Cost of f for the wear ODE: **2** (one ×, one +).
  - Counts are for a scalar state.
- Justification: simple, and the derivations are written out in the code comments.
- Source / evidence: per-step counts with f_flops = 2, derived in the docstrings of `performance.py`:

  | Method | FLOPs per step | General formula |
  |---|---|---|
  | Euler | **5** | f + 3 |
  | Heun | **11** | 2f + 7 |
  | RK4 | **25** | 4f + 17 |
  | RK45 (per attempt) | **105** | 6f + 93, counted from the Butcher tableau's non-zero entries |

  A rejected RK45 step costs as much as an accepted one. **FLOPs do not predict run time here** (D75: Python overhead dominates).
- How it is validated: `test_flops_per_step_match_hand_counts`, `test_flops_scale_with_cost_of_f`, `test_solver_flops_totals`; my own hand count was wrong once (C11).
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D77: KNN scaling test
- Phase / date: Phase 8 / 2026-10-24
- Options considered: data with whole-lap tyre ages (many ties) or continuous data.
- Decision:
  - Training sizes n = 500, 1000, 2000, 4000, 8000, 16000; 1000 queries; k = 50; one continuous feature (seed 42; no ties, so both methods must agree exactly).
  - My brute force against scikit-learn's `KNeighborsRegressor(algorithm="kd_tree")`, timing fit + predict.
  - Memory with tracemalloc.
  - Scaling exponent = slope of log(time) against log(n), fitted with my least squares.
- Justification: the theory to compare against (m queries, n points, d features):
  - **Brute force:** time O(m·n·d), memory O(block·n), with blocks of 512 queries.
  - **kd-tree:** build O(n log n), query about O(m·(log n + k)) for small d.
- Source / evidence (`phase8_knn.csv`, `phase8_knn_scaling.png`):

  | | Mine (brute force) | scikit-learn kd-tree |
  |---|---|---|
  | Time ∝ n^ | **1.07** (≈ linear) | **0.23** (≈ logarithmic) |
  | At n = 16000 | 0.294 s | 0.0059 s (**50× faster**) |
  | Peak memory | **8.5 MB → 270 MB** (linear in n) | about 1.4 MB (a lower bound) |

  Predictions are identical (max difference 0.0). The exponents vary by about ±0.06 between runs (C13).
- How it is validated: KNN equality with scikit-learn is also tested in Phase 4.
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D78: Least-squares ill-conditioning test
- Phase / date: Phase 8 / 2026-10-24
- Options considered: n/a.
- Decision: polynomial degrees 1–12 on tyre ages 1–41, unscaled and scaled to [−1, 1]. Noise-free data from known coefficients, with the exact reference computed by binomial expansion. Compare my normal equations, QR (numpy QR + my back substitution) and SVD (`numpy.linalg.lstsq`). Report cond(X) and cond(XᵀX).
- Justification: covers the range from well-conditioned to numerically singular (cond(X) from 49 to 2.7e21).
- Source / evidence (`phase8_least_squares.csv`, `phase8_least_squares_conditioning.png`), unscaled:

  | Method | Behaviour |
  |---|---|
  | Normal equations | Warns from degree 4 (cond(XᵀX) = 3.6e13); **refuses as singular from degree 7** |
  | QR | Error ≤ 1e-7 up to degree 9; refuses from degree 10 |
  | **SVD (`lstsq`)** | **Never refuses, but is silently 98–100 % wrong from degree 9**: its default `rcond` drops small singular values and returns a minimum-norm solution |

  - Scaled: every method is accurate to degree 12 (normal equations 2.5e-9, QR and SVD ≤ 5e-13).
  - Speed: `lstsq` (compiled LAPACK) 0.007–0.021 ms; my methods 0.1–0.5 ms.
- How it is validated: consistent with Phase 3 (D35).
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D79: Profiling scope (data loading and network excluded)
- Phase / date: Phase 8 / 2026-10-24
- Options considered: profile everything, including loading; profile the compute only; profile both separately.
- Decision: **profile the compute pipeline only:** Phase 5 cross-validation of every candidate for C3 and C4, plus the Phase 6 strategy inputs and comparison, on prepared data. **Network time is excluded** (all data was already cached). Data preparation from the caches is timed separately (3 repeats) and not optimised.
- Justification: loading is I/O-bound and cache-dependent (C15); mixing it in would hide the compute bottleneck.
- Source / evidence:
  - Data preparation: **0.85 ± 0.03 s** warm; about 2.8 s per call with a cold OS file cache (C15).
  - Compute: 2.16 s (before the optimisation).
  - Profiles: `phase8_profile_before.csv` / `after.csv` (top 25 functions by cumulative time).
- How it is validated: `test_machine_info_and_profile`.
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D80: The bottleneck and the one optimisation
- Phase / date: Phase 8 / 2026-10-24
- Options considered (from the "before" profile, 3.53 s under cProfile):
  - (a) **vectorise `predict_held_out`**: 2.36 s (67 %), which looped over every held-out stint, built pandas objects and called the model twice per stint (3480 KNN predictions);
  - (b) speed up the wear-ODE fits (0.66 s, an RK4 Python loop);
  - (c) data preparation (excluded, D79).
- Decision: **(a)**. Call the model **once** for all held-out laps, compute every stint's anchor offset with `numpy.bincount`, and build one table. The original is kept as `predict_held_out_loop` (reference), selectable through `cross_validate(..., implementation=...)`.
- Justification: the largest share of the profile, and the change cannot alter the arithmetic.
- Source / evidence (`phase8_optimisation.csv`):

  | | Before | After |
  |---|---|---|
  | Compute pipeline, wall clock (7 repeats) | 2.16 ± 0.04 s | **1.75 ± 0.02 s** |
  | `predict_held_out` under cProfile | 2.36 s | 1.09 s |

  - **Speed-up: 1.23×**, less than the profile suggested (C14).
  - **Results identical:** max |difference| 5.6e-16 in the CV metrics and 0.0 in the strategy times (tolerance 1e-12 s).
  - The next bottleneck is now KNN distance computation (0.88 s), followed by the ODE fits (0.66 s).
- How it is validated: **`test_vectorised_prediction_equals_original_loop`** (5 model types × anchors 1, 3, 5, shuffled input; tolerance 1e-12 s) and `test_cross_validation_identical_with_both_implementations`.
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D81: Strategy optimiser benchmark
- Phase / date: Phase 8 / 2026-10-24
- Options considered: n/a.
- Decision: time brute force, secant and Newton on the real Phase 6 inputs, (i) with the stint limits (6 feasible laps) and (ii) with them relaxed (69 laps), plus the two-stop brute force.
- Justification: the cost comparison depends on the size of the search space.
- Source / evidence (`phase8_strategy.csv`):

  | Case | Brute force | Secant | Newton |
  |---|---|---|---|
  | (i) with stint limits | **6 evaluations, 0.28 ms** | 9 evaluations, 0.38 ms | 18 evaluations, 0.69 ms |
  | (ii) limits relaxed | 69 evaluations, 3.3 ms | **12 evaluations, 0.56 ms** | 21 evaluations, 0.89 ms |

  - In case (i) brute force is fastest; in case (ii) secant is **5.9× faster**.
  - All methods agree: pit lap 35 in case (i), 33 in case (ii).
  - Two-stop brute force: 818 combinations in 2.9 ms.
- How it is validated: method agreement (Phase 6 tests).
- **Decided by AI without prior approval (Phase 8), to be reviewed by me.**

## D55 amendment: the CV stage may not overwrite the selection after the test (Phase 8)
After C16 (a verification re-run overwrote the frozen `model_selection.json`;
restored from git), `compare_models.py --stage cv` refuses to run when the test
results exist, unless `--force` is given (`guard_cv_rerun`, tested). The
committed selection (11:40:30 UTC, commit 7f7d6eb) is unchanged.
**Decided by AI without prior approval (Phase 8), to be reviewed by me.**

---

# Phase 9: pipeline, documentation and reproducibility

**For Phase 9 only, the decision protocol was overridden:** every decision below was made by the AI and implemented straight away. **Each is to be reviewed by me.** Problems met are in `CHALLENGES.md` (C17–C22). Evidence: `reports/pipeline_manifest.json`, `reports/pipeline_cleaning_report.csv`, `reports/test_report.html`, `reports/phase9_api_review.csv`.

## D82: End-to-end pipeline script
- Phase / date: Phase 9 / 2026-10-25
- Options considered: (a) one script that calls the existing phase scripts' functions in order; (b) a rewrite of all stages inside one script; (c) a Makefile or shell script that runs the phase scripts one after another.
- Decision: **(a)** `scripts/run_pipeline.py`:
  - Stages `data → validate → test → strategy → sensitivity`. `--stages` runs a subset, always in pipeline order.
  - Other options: `--config`, `--force-test`, `--log-level`, `--log-file` (default `reports/pipeline.log`).
  - Logging goes to the console and to the log file. FastF1's INFO messages are reduced to warnings.
  - **Test firewall:**
    - Once the test has been run, `validate` recomputes the CV and only **verifies** that the selection equals the frozen `model_selection.json`. It raises an error if they differ, and never writes the file (D55, C16).
    - `test` is skipped unless `--force-test` is given; every forced run is logged.
  - `data` writes `reports/pipeline_cleaning_report.csv`: laps loaded, laps removed per rule, clean laps kept, per race.
  - The Phase 8 benchmarks are not a stage, because their timings depend on the machine.
- Justification:
  - (a) reuses the tested code, so the pipeline and the phase scripts cannot give different results.
  - (c) would need Make, which is not installed on Windows by default.
  - A verify-only CV makes the pipeline safe to re-run after the test.
- Source / evidence:
  - Full runs with cached data: 14.5 s, 23.5 s and 30.2 s (other programs were running; the sensitivity stage dominates).
  - The selection check printed "Recomputed selection matches the frozen model_selection.json (not overwritten)".
  - `git diff` shows `model_selection.json` and `phase5_test_results.csv` unchanged.
- How it is validated: `tests/test_pipeline.py`, which covers stage order, rejection of an unknown stage, the hash exclusions, changed-file detection and `selections_agree`.
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

## D83: Reproducibility manifest
- Phase / date: Phase 9 / 2026-10-25
- Options considered:
  - (a) record the inputs only (config, git commit);
  - (b) also the SHA-256 hash of every result file, compared with the previous run;
  - (c) compare against stored reference values with a tolerance.
- Decision: **(b)**.
  - Contents of `reports/pipeline_manifest.json`:
    - UTC time;
    - git commit;
    - SHA-256 of the config file;
    - stages run and their durations;
    - SHA-256 of every file in `reports/` and `reports/figures/`.
  - Files left out of the hashes: the manifest itself, `pipeline.log`, `test_runs.log`, `phase8_*` (benchmarks), `test_report*` and `coverage/`.
  - If the config hash equals the previous manifest's, the run logs which result files changed; with the same code, none should.
- Justification:
  - Byte-identical outputs are the strictest reproducibility test, and a hash needs no tolerance.
  - Excluded files change on every run by nature: timestamps, timings, logs.
  - (c) is already covered by the unit tests.
- Source / evidence:
  - Two consecutive full runs: "all 40 result files identical".
  - After the Phase 9 edits: "all 41 result files identical" (the new file is `phase9_api_review.csv`).
  - The one change seen during development was intended: the new cleaning-report format (D82). It was reported as a warning, as designed.
- How it is validated: `test_result_hashes_skip_logs_manifest_and_benchmarks`, `test_changed_results_ignores_new_files_and_reports_changed_ones`.
- Limitation: identical bytes are guaranteed only with the same library versions (`requirements-lock.txt`) and the same code. A different implementation can change round-off (C18).
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

## D84: README and API documentation
- Phase / date: Phase 9 / 2026-10-25
- Options considered:
  - pdoc docstring format: `--docformat numpy` vs the default (markdown);
  - output: committed `docs/` vs generated on demand only.
- Decision:
  - **README.md** sections:
    - purpose and engineering problem;
    - inputs table (key, unit, the valid range enforced by `config.py`, value used);
    - outputs table (unit, file);
    - headline results copied from the result files;
    - installation, running, tests, documentation;
    - repository structure, data and licensing, limitations;
    - links to DECISIONS, CHALLENGES and LESSONS_SUMMARY;
    - an AI-use section with placeholders for me to complete.
  - **API docs:** `.venv/Scripts/python -m pdoc src/tyredeg -o docs --docformat numpy`. The HTML in `docs/` is committed, so it can be read without installing anything.
  - Module constants that hold machine-specific values are private (leading underscore), so pdoc does not publish them (C19).
- Justification: `--docformat numpy` renders the Parameters/Returns/Raises sections as headed lists instead of plain text. 25 modules were built with no warnings.
- Source / evidence: pdoc 15.0.4 `--help` lists `--docformat` with the choices markdown, google, numpy and restructuredtext.
- How it is validated: search of `docs/` for local paths (0 found; C19), visual check of `docs/index.html`.
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

## D85: Test report and coverage (new dependency: pytest-cov)
- Phase / date: Phase 9 / 2026-10-25
- Options considered: (a) pytest-html only; (b) pytest-html plus pytest-cov; (c) the `coverage` command-line tool run separately.
- Decision: **(b)**. One command produces both reports:
  ```
  .venv/Scripts/python -m pytest tests src/tyredeg --doctest-modules --html=reports/test_report.html --self-contained-html --cov=tyredeg --cov-report=term --cov-report=html:reports/coverage
  ```
  - **New dependencies:** `pytest-cov==6.2.1` and its dependency `coverage==7.10.6`, pinned in `requirements.txt` (an amendment to D11). `requirements-lock.txt` was regenerated: only these 2 lines were added.
  - Doctests are included (`--doctest-modules src/tyredeg`). Plain `pytest` still runs the unit tests only.
  - `--self-contained-html` puts the CSS inside the file, so the report is one file. It is committed.
  - The coverage HTML (3 MB, regenerated by the command) and `.coverage` are git-ignored.
  - A root `conftest.py` shortens skip locations, so the report contains no local paths (C20).
- Justification:
  - The Phase 9 brief allows a new dependency for coverage if it is logged.
  - (c) needs a second command and gives the same numbers.
- Source / evidence:
  - Final run: **813 passed, 42 skipped** (all 42 are doctest examples marked `+SKIP` because they need downloaded data). Total line coverage 94 % (3,068 statements, 170 missed).
  - Lowest-covered modules: `preparation.py` 52 % (it loads real data, so only the pipeline exercises it), `sensitivity.py` 78 %, `strategy.py` 81 %.
  - `pip check` reports no broken requirements.
- How it is validated: the command above; a search of the report for the user name (0 found).
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

## D86: Review pass of docstrings and input validation
- Phase / date: Phase 9 / 2026-10-25
- Options considered: (a) review by hand; (b) a script that parses the source code and lists the gaps, followed by a manual check of what it flags.
- Decision: **(b)** `scripts/review_api.py`, which writes `reports/phase9_api_review.csv`.
  - It checks every public function, method and class for the sections required by CLAUDE.md rule 5: Parameters (if the function takes arguments), Returns (if it returns a value), Raises and Example. Classes need an Example only.
  - It also checks whether each function raises an error, directly or through package functions it calls. Calls are matched by name only, so this is a heuristic.
  - **The gaps are listed, not fixed, in Phase 9** (the brief asks for a list). Fixing them is a separate, reviewable change.
- Justification: 214 objects are too many to check reliably by hand, and the script can be re-run after the docstrings are fixed.
- Source / evidence (`phase9_api_review.csv`):
  - **126 of 214 objects lack at least one required section:** Raises 65, Example 63, Parameters 53, Returns 48, and 1 with no docstring at all (`LinearDegradation.degradation`). 66 of the 126 miss only Raises and/or Example.
  - **30 functions take arguments but contain no check.** Checked by hand:
    - *Real gaps (bad input gives an obscure error or a silently wrong result):*
      - `strategy.fuel_effect_total`: negative laps are accepted silently.
      - `strategy.feasible_pit_laps`: an unknown compound gives a `KeyError`.
      - `validation.binned_residuals`: arrays of different lengths, or unsorted edges.
      - `validation.summarize_folds`: no baseline rows.
      - `validation.rank_compounds`: no `rate` column.
      - `sensitivity.tornado_table`: no nominal row.
      - `sensitivity.one_at_a_time`, `sensitivity.plot_tornado`, `validation.write_selection`.
      - `models.common.check_non_negative`, `resample_stints`, `format_parameter_table`.
      - The six `cleaning.*_mask` functions: a missing column gives a `KeyError`. They are normally called through `apply_cleaning`, which does validate.
    - *Accept any input by design* (they return False or a fallback): `is_green_track_status`, `is_missing`, `is_green_lap`, `performance.short_path`.
    - *Internal helpers that are public by name* and are only called with validated data: `StintData.demean`, `StintData.stint_means`, `differentiation.default_step`, `OpenF1Client.cache_path`, and the four `*_flops` counters.
- How it is validated: re-run the script after the fixes. The target is 0 incomplete docstrings and no unexplained "validates = no".
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

## D87: Consistency review (DECISIONS.md vs config.yaml vs code)
- Phase / date: Phase 9 / 2026-10-25
- Options considered: n/a (a review).
- Decision: every numerical value in config.yaml was traced to its decision, and every module-level constant in the code to config.yaml. Mismatches found:

  | # | Where | Mismatch | Action |
  |---|---|---|---|
  | M1 | D9 | names the key `data.cache_dir`; the code and config use `fastf1.cache_dir` (moved when the `openf1:` section was added, D15) | note added to D9 |
  | M2 | D12 | says `k_fuel`, `outlier_k` and `min_stint_laps` are `null`; they were set by D19, D20 and D22 in Phase 2. The 2018 lower year limit is still unverified | note added to D12 |
  | M3 | D3 | seasons 2022–2025, but the strategy uses 2023–2025 (D56) | none: D56 records it; the CV/test still use 2022–2025 |
  | M4 | D4, D6 | the "Decision:" lines still say Bahrain/HARD and Red Bull only | none: the amendments below them (Hungary/C3, all teams) and D52 (C3 + C4) supersede them |
  | M5 | D11 | the pin list leaves out `requests` (D15) and `pytest-cov`/`coverage` (D85) | covered by the D11 amendment and D85 |
  | M6 | `scripts/benchmark.py` | `SEED = 42` hard-coded instead of `config.random_seed` | **fixed**: passed from the config. Same value, so the Phase 8 results stay valid; the benchmark was not re-run |
  | M7 | README.md | Phase 1 placeholder | rewritten (D84) |
  | M8 | `LICENSE` | copyright holder is the placeholder `[my name]` | left for me to fill in |

  - No value mismatches: all numbers in config.yaml match the decision that set them. The code defaults that mirror config.yaml (ODE, root finding, differentiation, linear, model, sensitivity and performance defaults) are already tested for equality (`tests/test_numerics_defaults.py`, `tests/test_config.py`).
  - Constants that are **not** in config.yaml, by design: the MAD-to-SD factor 1.4826 and the minimum of 3 laps for the outlier test (cleaning), the round-off factor 4 (D30 amendment), the RK45 error exponent −1/5, the uniform-spacing tolerance 1e-9, the HTTP timeout of 30 s, and the KNN query block of 512 (memory only, identical results). These are mathematical constants or implementation details, not modelling choices.
- How it is validated: the review can be repeated with `grep` over `src/`, plus the defaults tests.
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

## D88: Git workflow for submission
- Phase / date: Phase 9 / 2026-10-25
- Options considered: (a) one commit per phase on `main` (as in Phases 1–8); (b) a branch per phase, merged into `main`; (c) (a) plus an annotated tag on the submitted commit.
- Decision: **(c)**. Phase 9 is committed on `main` like the earlier phases. The final submitted state gets an annotated tag (e.g. `v1.0-submission`), so the assessed version can be named exactly.
  - Commit and tag only on my instruction.
  - The local-path leak in the history of commit c01bd56 (C17) can only be removed by rewriting history. That is my decision; the repository has not been pushed.
- Justification: one developer and a linear history, so branches add no safety. A tag names the assessed version without moving files.
- How it is validated: `git status` is clean after the commit; `git ls-files` contains no `cache/` files.
- **Decided by AI without prior approval (Phase 9), to be reviewed by me.**

---

# Open issues (need my decision)

## OI-7: Degradation changes from year to year (found by the final test) — RESOLVED: D56–D58 (Phase 6); (d) year scenarios in D67 (Phase 7) — the year effect can flip the strategy
The test race degraded less than every training race (above). Also, the same
compound behaves differently depending on its label/role: C4 used as the
SOFT (2022) wore about twice as fast as C4 used as the MEDIUM (2023–2024),
which inflates the pooled C4 rate. This challenges the D52 assumption that
the Pirelli C-number alone determines wear. Options to decide in Phase 6:
(a) use the frozen, validated models as they are (the test error then
describes their real accuracy); (b) refit the selected model forms on all
four races for the strategy (standard practice after the final test; the
test result remains the honest accuracy estimate); (c) use only races where
the compound had the same label (e.g. C4 as MEDIUM: 2023–2025); (d) carry
the year-to-year spread of the rate into the Phase 7 sensitivity analysis.

**Proposed resolution (to be decided as the first Phase 6 decision; not yet approved):**
- Refit the selected model forms on **2023–2025 only**. These years share the C3/C4/C5 allocation, so each compound had the same role; 2022 is dropped from the strategy models.
- Re-estimate the pit loss on 2023–2025.
- Keep the Phase 5 test result as the reported accuracy; label any 2025 strategy numbers as in-sample.
- In Phase 7, use the per-year rates as low/middle/high wear scenarios.

## OI-6: The linear C4 model over-predicts degradation on old tyres (Phase 5 residuals) — RESOLVED: points 1–2 in Phase 6 (D56, D63); point 3 in Phase 7 (D67): with KNN the margin is +2.3 s (two stops still best), and the C4 rate barely matters
CV residuals of the selected C4 model (polynomial degree 1) are about +0.6 to
+1.3 s beyond about 25 laps of tyre age: the data level off at about 2.2 s while
the line keeps rising. This may be partly selection (only drivers managing their
tyres ran C4 that long; few laps there). Consequence for Phase 6: the strategy
will be too pessimistic about long C4 stints. To decide in Phase 6, e.g.
restrict C4 stint lengths to the validated range, or add this to the
sensitivity analysis.

**Proposed resolution (Phase 6 decision; not yet approved):**
1. Re-check the C4 residuals after the OI-7 refit on 2023–2025.
2. Limit each stint to the tyre ages observed for its compound (no extrapolation).
3. If the optimal C4 stint is 25 laps or fewer, document that OI-6 does not affect the decision. Otherwise, compare against the KNN C4 model as a model-choice sensitivity (Phase 7).

## OI-1: F1 timing data now requires an F1 TV login (resolved by D14: free sources)
Since about 15 Oct 2026, `livetiming.formula1.com/static` returns HTTP 401 to
unauthenticated requests. FastF1 3.8.3 cannot download any session that is not
already cached; its fallback mirror only has 2021–2022. Confirmed on
2026-10-24: 2022 Bahrain loaded (via the mirror); 2023, 2024, 2025 failed.
FastF1 maintainers published pre-release `3.9.0a0` (18 Oct 2026) with
authentication support, which requires an F1 TV Access (or higher) subscription.
Sources: [FastF1 issue #978](https://github.com/theOehrly/Fast-F1/issues/978).

## OI-2: The 2022 HARD tyre is a different compound (resolved: switched to MEDIUM, see D4 amendment)
The 2022 C1 became the 2023 C0; the 2023–2025 C1 is a newer, softer compound
(Pirelli 2023 preview, see D4). Also, in the 2022 data Red Bull ran **no HARD
laps at all** (VER: S-S-M-S, PER: S-M-S-S). With D4 (HARD only) and D6
(Red Bull only), 2022 contributes zero training laps.

## OI-3: Data volume and the Phase 6 one-stop rule
Red Bull + HARD + Bahrain gives at most a few stints per season, which is thin
for cross-validation and KNN. Also, Phase 6 requires a one-stop race on two
*different* compounds (dry-race rule), which a HARD-only model cannot cover on
its own.

## OI-4: Root-finder stopping rule on flat functions (from the Phase 3 study) — RESOLVED by the D30 amendment
With the approved "either" rule (D30), the residual test |f| ≤ 1e-12 can stop
too early when f is flat near the root: on (x − 1)³ the result is only
accurate to about 1e-4. A "step only" rule reaches about 1e-10 there, at
2–3× the iterations. A third option is "both" (stop only when the step AND
the residual are small), which takes the more accurate result in every study
case. This matters only if a root finder is applied to a flat function: the
Phase 4 (dRSS/db = 0) and Phase 6 (dT/dL = 0) roots are expected to be simple.

## OI-5: Finite-difference step scaling for large |x| (from the Phase 3 study) — checked in Phase 6: no problem for dT/dL (secant converges in 2 iterations, all methods agree; D64)
The default step is scaled by max(1, |x|) (D32). For sin at x = 10 the
empirical optimum is 0.1–0.3 × the default, so the scaling makes h too large
there (errors still ≤ 7e-8). For the planned uses |x| < 1 (the wear-rate
parameter b), so no change is needed now. Phase 6 differentiates race time
with respect to the pit lap (|x| ≈ 20–50), where this should be re-checked.

## OI-8: Optional wear-factor diagnostics — (1) RUN in Phase 6 (D66); (2) skipped because 2022 is dropped (D56)
Proposed cheap checks that would not change any model:
(1) degradation rate per team, to show how much assuming one shared rate per
compound (D39) hides; (2) whether 2022 laps on dry tyres ran on a damp track
(match the recorded rain times against lap times). A dirty-air
(traffic) analysis is possible with OpenF1 gaps for 2023+ and FastF1 timing
for 2022, but defining "in traffic" would need new decisions, so it is not
proposed unless brought into scope.

**Proposed resolution (Phase 6 decision; not yet approved):** run (1), the
wear rate by team, reported only. Skip (2) if OI-7 drops 2022. Dirty air
stays out of scope.
