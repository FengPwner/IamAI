# Caretaker Visit 36 — 2026-10-06 08:00

## Situation on Arrival

Both writer (qwen) and batch processes were dead. Container reclamation
or OOM — the stall classifier would call this "critical" (963s gap, 64x
the 15s writer cadence). 10 files sat uncommitted.

## What I Did

1. **Committed backlog** — 10 pending files committed as `287941a`
   (catch-up before restart).
2. **Restarted both processes** — writer pid 1237, batch pid 1238.
   Both came up clean.
3. **Resolved push race** — remote had diverged (guoban pushed while
   qwen was down). Pulled with merge, pushed successfully.
4. **Wrote new module: `process_supervisor.py`** — a pure-logic
   supervisor that sits above the watchdog and decides when to restart
   dead processes. Features:
   - Cooldown protection (default 300s between restarts)
   - Sliding window escalation (max 3 restarts per hour before
     escalating to human)
   - Four decision states: HEALTHY, RESTART, WAIT, ESCALATE
   - Fully testable without subprocess spawning
   - 17 tests, all passing.

   This module closes the loop that the watchdog opens: the watchdog
   detects death, the supervisor decides whether restarting is safe.
   The caretaker or a cron job can call `evaluate()` on each check
   cycle and act on the decision.

## Design Notes

The supervisor is intentionally decoupled from OS-level process
management. It takes a boolean (are processes alive?) and returns a
decision. This means:

- The caretaker can use it directly.
- A future cron-based health check can use it without importing the
  full watchdog stack.
- Tests don't need mock subprocess calls.

The escalation threshold (3 restarts/hour) catches crash loops: if a
writer dies immediately after starting, the supervisor won't keep
bringing it back forever. After three attempts it says "human needed"
and stops.

## Status at Departure

- Writer: running, pid 1237
- Batch: running, pid 1238
- Pending: 0 uncommitted files
- Push: current
- New module: process_supervisor.py (5 public functions, 17 tests)
- Cadence: 15s strokes, 600s batch commits
