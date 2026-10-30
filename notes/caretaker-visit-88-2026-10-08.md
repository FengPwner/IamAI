# Caretaker Visit 88 — 2026-10-08 20:00

## Status

- Writer (pid 1161) and batch committer (pid 1162) were found **stopped**
  on arrival — both restarted via `tools/run_both.sh`.
- 7 uncommitted files from the previous cycle were swept by a catch-up
  commit (`687e6a6`) before restart — no manual backlog work needed.
- Push: successful (`badc4f4..687e6a6 main -> main`).
- Post-restart gap dropped from 3283 s (longest) to 10 s — writer is
  producing strokes again at full cadence.

## New Contribution

Added `iamai.stall_forecaster` — predicts imminent writer stalls by
analysing the last *N* commit gaps for three warning signals:

1. **Trend** — gaps growing linearly (OLS slope above threshold)
2. **Volatility** — gaps becoming erratic (coefficient of variation)
3. **Proximity** — latest gap approaching the warn threshold

Each signal contributes to a `[0, 1]` risk score. Levels: low / medium /
high. Pure-function API, trivially testable, no subprocess calls.

Companion test suite: 44 tests covering edge cases, healthy patterns,
each signal independently, combined risk levels, RiskReport output
methods, and `forecast_from_log` JSONL parsing.

### Why this module

The existing `stall_classifier` answers "is the writer stalled *now*?"
and `commit_gap` answers "how long since the last commit?". Neither
tells the caretaker **whether a stall is about to happen** — which is
the question that matters for proactive intervention. This module fills
that gap, enabling caretakers to act *before* the writer dies rather
than discovering it afterwards.
