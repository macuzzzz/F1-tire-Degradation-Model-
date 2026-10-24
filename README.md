# F1 tyre degradation and pit-stop strategy

MMA3001 (Numerical Methods and Machine Learning) project: model Formula 1 tyre
degradation from race lap timing data and use it to optimise pit-stop strategy.

> This README is a placeholder from Phase 1. The full version (inputs/outputs,
> usage, limitations, AI-use statement) is written in Phase 9.

## Quick start (Windows, Git Bash or PowerShell)

```bash
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest
```

- Configuration: `config.yaml` (validated by `src/tyredeg/config.py`).
- Decisions and their justification: `DECISIONS.md`.
- Race data is downloaded on demand with FastF1 into `cache/fastf1/` and is never committed.
