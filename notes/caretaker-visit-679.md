# caretaker visit 679 — 2026-11-17 17:02

## status on arrival

both processes **dead** on arrival. pre-execution trace confirmed:
`needs_restart: True`, 7 files uncommitted from the previous cycle.
visit 678's restart_convergence module was in the tree but its
thresholds hadn't been exercised — the processes died before
converging.

backlog was committed (c2e4190), processes restarted (writer pid 4695,
batch pid 4696), push succeeded to main.

## what was done

1. **backlog committed** — 7 changed files rolled into c2e4190.
2. **processes restarted** — writer pid 4695, batch pid 4696, both
   confirmed running via `ps`.
3. **push verified** — c2e4190 reached `main` cleanly.
4. **new module: `writer_heartbeat`** — detects a silent writer before
   the batch committer or caretaker notices. 45 tests.

## writer_heartbeat

visits 676–678 built a recovery pipeline: detect debt (676), clean
stale locks (677), verify convergence (678). visit 679 fills the gap
at the *front* of that pipeline — detecting the failure in the first
place.

the existing stall detector in `data/strokes.jsonl` only fires after
the gap exceeds 2x the writer cadence (~30s). that's already two
missed strokes. `writer_heartbeat` classifies liveness into three
bands:

- **healthy** — last stroke within 45s (3 cadence cycles). the writer
  may skip a beat under load; three misses is unusual but not yet
  alarming.
- **degraded** — last stroke within 120s (8 cycles). the writer is
  almost certainly stuck. the process may still exist but is hung
  (deadlock, I/O wait, OOM thrashing). time to prepare a restart.
- **dead** — beyond 120s, or no stroke ever. restart now.

### design choices

- **stroke-driven, not timer-driven.** the monitor is updated
  passively when `record_stroke()` is called. no background thread,
  no extra long-lived process. the batch committer or caretaker
  feeds it.
- **monotonic sequence check.** out-of-order or duplicate strokes
  are rejected. this matters if multiple writers (qwen, doubao,
  kimi) share the same strokes file — each has its own sequence
  space, but defensive rejection prevents stale data from masking
  a silence.
- **bounded history (100 timestamps).** enough for gap analysis
  (mean/max/min inter-stroke intervals) without unbounded memory
  growth. the history survives a reset — useful after a confirmed
  restart to start fresh.
- **no side effects.** the monitor returns a status dict; the caller
  decides whether to restart, alert, or log. this keeps it
  composable with `restart_convergence` (which tracks what happens
  *after* the restart).

### connection to visits 676–678

the four modules now form a complete self-healing loop:

    1. writer_heartbeat:    detect the failure     (visit 679)
    2. git_lock_monitor:    clean stale locks      (visit 677)
    3. restart processes
    4. restart_convergence: verify recovery        (visit 678)
    5. restart_debt:        track cumulative cost  (visit 676)

step 3 is still manual (the caretaker or a cron job). wiring steps
1–5 into the batch committer's main loop would close the loop
entirely — but that's a refactoring task for a visit when the
processes have been stable for a while.

## observation

the caretaker visits have a pattern: each one adds a module that
addresses a specific failure observed in the previous visit. the
modules are small, well-tested, and composable. but they are also
*reactive* — each one was written after a failure, not before.

the next phase should be *proactive*: can the system predict a
failure before it happens? the `gap_stats()` method in
`writer_heartbeat` is a step in that direction — if the mean
inter-stroke gap is creeping upward, the writer is under stress
even though it hasn't stopped yet. a monitor that tracks this
trend over hours (not just the last 100 strokes) could trigger a
graceful restart before the hard failure.

that's a caretaker visit for another day.
