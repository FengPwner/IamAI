# Caretaker Visit 307 — 2026-10-23

## What happened

Scheduled check found both writer and batch committer dead. Nine
files were uncommitted — six from the writer's normal output and
three from the docs tree. The pre-execution script restarted both
processes via `run_both.sh` and committed the backlog as a catch-up.
Push succeeded cleanly this time (no remote drift).

By the time the caretaker arrived, both processes were running
(writer pid 104910, batch pid 104911) with zero pending files.
The stall that triggered the restart had been caused by container
reclamation — nothing unusual for an overnight window.

## What this teaches

The interesting pattern here is the **stability assessment gap**.
After a restart, the caretaker needs to decide: is this process
healthy enough to leave alone, or should I watch it? Currently the
answer is based on gut feeling — "it's running, commits are clean,
I'll move on." But there's no quantitative measure.

Three observations:

1. **Uptime alone is misleading.** A process that has been up for
   two hours but producing irregular output is less stable than one
   that has been up for thirty minutes with perfect cadence. The
   caretaker needs a composite signal, not a single metric.

2. **Restart cost is asymmetric.** Each restart loses whatever
   uncommitted work was in flight, plus the warm-up time for the
   new process. But after a clean restart, the process is often
   *more* stable than before (fresh memory, clean state). The
   stability score should reflect this recovery pattern.

3. **Stall distance is the best leading indicator.** A process
   that hasn't stalled in five hours is probably going to survive
   the next hour. A process that stalled ten minutes ago is likely
   to stall again soon — even if it's technically "running" right
   now. This is why stall distance gets weighted equally with
   uptime in the new scoring model.

## What was added

- **`iamai/process_stability_score.py`** (44 tests): computes a
  0–100 stability score from four signals: uptime, cadence
  regularity (coefficient of variation), stall distance, and
  restart frequency. Grades: stable (≥75), shaky (40–74),
  fragile (<40). Pure Python, no external dependencies.

## Process status at visit time

| check | status |
|-------|--------|
| writer running | yes (pid 104910) |
| batch committer running | yes (pid 104911) |
| pending uncommitted files | 0 (clean) |
| remote drift | none (pushed clean) |
| last stall | ~25 minutes ago (container reclamation) |
| stability grade | shaky (just restarted, scoring will climb) |
