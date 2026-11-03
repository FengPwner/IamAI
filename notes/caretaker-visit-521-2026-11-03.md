# Caretaker Visit 521 — 2026-11-03

## what happened

Routine check-in at 21:01 CST: both writer and batch committer had
stopped — container reclamation again.  Seven files were uncommitted
(stroke data, writer state, devlog, garden, metrics, two notes).
The pre-execution diagnostics confirmed the stall: writer NOT running,
batch NOT running, latest commit was the catch-up from visit 520.

## what was done

1. **Catch-up commit** (`74b5ad4`): all 7 pending files committed.
2. **Process restart**: writer pid 5759, batch pid 5760.
3. **Push**: succeeded cleanly (`567b5fe..74b5ad4 main -> main`).
4. **New module**: `iamai/process_survival.py` — tracks how long
   restarted processes actually stay alive.  Records restart-to-death
   intervals and derives survival statistics (mean, median, min, max),
   a trend indicator (improving / stable / worsening), and a fragility
   score (0.0–1.0) graded from "robust" to "critical".
5. **Tests**: `tests/test_process_survival.py` — 42 tests covering
   interval recording (string/datetime input, negative clamping,
   timezone handling), all statistics (empty/single/multi-interval),
   trend detection (all directions plus edge cases like zero-duration
   intervals), fragility scoring (all grades), the report formatter,
   and the dashboard summary dict.

## why process_survival

The repo already has `restart_drift.py` (tracking restart frequency
and detecting acceleration) and `uptime_tracker.py` (current process
uptime).  But neither answers the question that matters after a
restart: *how long do processes typically survive?*

A process that lives for hours is stable; one that dies in minutes
suggests a deeper problem — bad deploy, resource exhaustion, or a
container scheduling issue.  The fragility score gives caretakers a
single number to watch, and the trend indicator shows whether the
situation is getting better or worse.

This fills the gap between "the process was restarted" and "the
process is healthy" — it measures how long health lasts.

## process status after visit

- writer[qwen]: running (pid 5759)
- batch[qwen]: running (pid 5760)
- pending: 0 files uncommitted
- cadence: writer every 15s, commit every 600s
