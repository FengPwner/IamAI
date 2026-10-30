# Overnight Stall, Classified — 2026-10-05 01:00

## what happened

Fourth check-in of the night. Both processes dead again — writer and batch
committer gone, pidfiles reaped by the container runtime. Ten files uncommitted,
accumulated during the last active window before whatever killed them.

The recovery was routine: commit the backlog, restart both, pull remote changes
(guoban's stroke 26 had landed while we slept), push. The interesting part is
what came next.

## what changed this time

Added `diagnose()` to `iamai/watchdog.py`. Until now the watchdog could report
*what* was wrong (dead process, stale pidfile, stalled heartbeat) but not
*classify* the failure mode. The diagnosis function cross-references two signals
— pidfile liveness and heartbeat stall — to sort every observed state into one
of four bins:

- **healthy**: processes alive, strokes flowing. Nothing to do.
- **hung-process**: pidfile says alive, heartbeat says stalled. The loop is stuck
  somewhere between `time.sleep()` and the next `append_thought()` call. Needs
  SIGKILL, not SIGTERM — a hung Python process won't catch a polite signal.
- **reclaimed**: process gone and writer stalled. Container reclamation, OOM,
  host sleep. This is what happened tonight. Full restart plus backlog commit.
- **just-died**: pidfile vanished but the last stroke is still fresh. The
  process died seconds ago and the heartbeat window hasn't expired yet. Restart
  now before the gap becomes a stall.

Nine tests cover all four quadrants plus edge cases (empty process list,
partial death with stall). The test that originally expected `hung-process`
for a partially-alive system actually proved that the semantics are right:
when one process is dead and the writer has stalled, that's reclamation,
not a hang. The matrix is honest.

## why it matters

Tonight's stall was the fourteenth reclamation in four days. Each one followed
the same script: discover, commit backlog, restart, push. The diagnose function
turns that script into a dispatch table — a future caretaker can read one string
and know whether to restart, kill, or just wait. Classification is the step
before automation.

## the numbers

- Stroke count at check-in: 701 lines in `strokes.jsonl`
- Longest gap recorded: 2274s (38 minutes) — consistent with container reclamation
- Files pending at discovery: 10
- Commits behind remote: 1 (guoban's note, resolved by rebase)
- Diagnosis for tonight's event: `reclaimed`
