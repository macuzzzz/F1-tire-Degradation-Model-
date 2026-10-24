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

---

# Open issues (need my decision)

## OI-6: The linear C4 model over-predicts degradation on old tyres (Phase 5 residuals)
CV residuals of the selected C4 model (polynomial degree 1) are about +0.6 to
+1.3 s beyond about 25 laps of tyre age: the data level off at about 2.2 s while
the line keeps rising. This may be partly selection (only drivers managing their
tyres ran C4 that long; few laps there). Consequence for Phase 6: the strategy
will be too pessimistic about long C4 stints. To decide in Phase 6, e.g.
restrict C4 stint lengths to the validated range, or add this to the
sensitivity analysis.

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

## OI-5: Finite-difference step scaling for large |x| (from the Phase 3 study)
The default step is scaled by max(1, |x|) (D32). For sin at x = 10 the
empirical optimum is 0.1–0.3 × the default, so the scaling makes h too large
there (errors still ≤ 7e-8). For the planned uses |x| < 1 (the wear-rate
parameter b), so no change is needed now. Phase 6 differentiates race time
with respect to the pit lap (|x| ≈ 20–50), where this should be re-checked.
