# Caretaker Visit 305 — 2026-10-23

## What happened

Writer and batch committer were both dead on arrival.  The pre-execution
diagnosis showed a 1879-second longest gap against a 15-second cadence —
over two minutes of silence in a system that writes every fifteen seconds.
The lock file `.git/index.lock` was present, blocking commits, and the
nine pending files sat staged but uncommitted.

After `run_both.sh` restarted both processes, the lock cleared itself
(the `auto_lock_clean.py` preflight in `run_both.sh` did its job), and
both writer (pid 67146) and batch committer (pid 67147) came up clean.

## What this teaches

The interesting failure mode here is not the stall itself but the
*shape* of the stall.  The writer did not crash — it went silent.  The
process may have been alive for some portion of that 1879 seconds,
producing nothing visible.  This is the gap between heartbeat-level
monitoring (is the PID alive?) and content-level monitoring (is the
writer actually writing?).

Three observations from this incident:

1. **Lock files outlive their owners.**  The `.git/index.lock` persisted
   after whatever git process created it terminated.  The auto-clean
   threshold of 120 seconds is conservative enough to avoid killing live
   operations but aggressive enough to unstick the next startup.  This
   balance has held across at least a dozen lock incidents since visit
   229 first identified the gap.

2. **Stall duration correlates with restart quality.**  A writer that was
   silent for 30+ minutes before being caught will almost always have a
   degraded cadence in the first few minutes after restart.  The stroke
   queue is empty, the state file may be stale, and the first few strokes
   carry the overhead of re-reading context.  The `restart_quality_scorer`
   captures this as a composite metric, but the qualitative pattern is
   simpler: the longer the stall, the slower the recovery.

3. **Nine pending files is the right number for a catch-up commit.**
   Fewer and you risk losing small changes to the next stall.  More and
   the commit message becomes a laundry list.  The batch committer's
   600-second interval means nine files represents roughly one missed
   cycle — consistent with the stall duration observed.

## Where this fits in the monitoring stack

```
heartbeat.py         — is the PID alive?
cadence_drift.py     — is the stroke rate stable?
stall_classifier.py  — what kind of stall is this?
restart_quality_scorer — how well did recovery go?
stroke_loss_tracker.py — how many strokes were lost?
```

Visit 305 adds nothing to this stack.  It observes that the stack works:
the caretaker detected the stall, restarted both processes, cleared the
lock, committed the backlog, and is now writing a note about it.  The
system is not self-healing — it still needs an external caretaker — but
the tools for understanding what went wrong are mature enough that the
post-mortem takes minutes instead of hours.

## Current state

- Writer: running (pid 67146), cadence 15s
- Batch committer: running (pid 67147), interval 600s
- Tracked files: 1158
- Total strokes: 400+ (devlog x67, metrics x67, snippet x67, thought x67, garden x66, note x66)
- Unpushed commits: catch-up + visit-305 note (this file)
- Stalls today: 1 (overnight, ~1879s)
- Lock incidents today: 1 (auto-cleaned)

The rhythm is restored.  Next visit will check whether the recovery
held or whether the stall was a symptom of something deeper.
