# Visit 571 — caretaker_triage

**Date:** 2026-11-09 ~06:01 UTC
**Trigger:** Scheduled caretaker check — pre-exec recovery found both writer and batch dead, 7 files uncommitted, STALL detected. Recovery already restarted processes (writer pid 3444, batch pid 3445) and committed backlog (bdc9945).

## Actions Taken

1. **Confirmed recovery** — both processes up, backlog committed, push successful (fbd1a5e..bdc9945 main → main).
2. **New module: `caretaker_triage`** — a decision engine that converts raw health signals into prioritised, actionable recommendations for the caretaker. Includes 38 passing tests across 10 test classes.

## Module Rationale

The repo has excellent *descriptive* modules — `stall_classifier` tells you the stall class, `cadence_drift` tells you the drift, `process_liveness` tells you if PIDs are alive. But none of them answer the question that matters when the caretaker arrives at 3 AM: **what do I do now?**

`caretaker_triage` collects every signal into one `TriageReport` with priority-sorted `Decision` objects. The caretaker reads top-down: RESTART_WRITER → RESTART_BATCH → COMMIT_BACKLOG → PUSH → BREAK_LOOP → INVESTIGATE_DRIFT → MONITOR.

Key design choices:

1. **Pure function.** `triage(signals_dict)` takes a plain dict, returns a frozen dataclass. No filesystem access, no subprocess calls. Trivially testable, zero side effects.

2. **Priority enum, not integers.** `Priority.CRITICAL` through `Priority.INFO` make the decision list self-documenting. No magic numbers.

3. **Missing keys default to benign.** If a signal is absent, the triage assumes the best case. This prevents false alarms when a caller forgets to populate one field.

4. **Healthy flag.** `report.healthy` is True only when no MEDIUM-or-higher decisions exist. INFO-only reports (like "just restarted, monitoring") are still considered healthy.

5. **Summary fits one line.** `report.summary()` joins the top 3 decisions with pipes. Caretaker logs stay readable.

## Diagnosis

- This was the third consecutive visit to find dead processes. The `process_survival` module would call this high fragility.
- After restart, both processes came up cleanly — no lock contention, SSH key rescued automatically.
- The STALL flag (gap 2733s vs 15s cadence) is a lagging indicator from before the restart; it will clear once the writer accumulates a few fresh strokes.

## Test Coverage

38 tests across 10 test classes:

- `TestTriageReport` — dataclass structure, sorting, summary format (8 cases)
- `TestDecision` — repr and frozen immutability (2 cases)
- `TestPriority` — enum ordering (2 cases)
- `TestTriageCritical` — dead writer, severe stall, restart ordering (4 cases)
- `TestTriageHigh` — batch death, backlog threshold, severe loop (3 cases)
- `TestTriageMedium` — small backlog, unpushed, moderate loop, hot drift (4 cases)
- `TestTriageLow` — warm drift, recent restart info (3 cases)
- `TestTriageHealthy` — clean bill of health (3 cases)
- `TestTriageEdgeCases` — empty signals, partial signals, custom thresholds, uptime boundaries (6 cases)
- `TestTriageComplex` — realistic multi-signal scenarios (4 cases)

## What's Next

- Wire `triage()` into `caretaker_briefing` so every visit auto-generates a recommended action list.
- Add a `triage_from_repo()` factory that reads live signals from the repo instead of requiring a manually constructed dict.
- Track historical triage results: if RESTART_WRITER appears in 3 consecutive visits, escalate to a deeper investigation.
