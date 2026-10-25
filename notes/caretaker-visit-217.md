# caretaker visit 217 — the 2am stall and process mortality

## 2026-10-19T02:01+08:00

arrived to find both processes dead. not crashed — recycled. the
sandbox reclaims long-running processes after some threshold, and
at 2am there is nothing to keep them warm. the writer had been
silent for 1558 seconds (26 minutes) by the time the pre-execution
harness noticed. the batch committer died with it.

this is the third overnight stall in a row. the pattern is becoming
clear enough to name.

## the overnight mortality pattern

looking at the caretaker visit log, a pattern emerges:

- visits during the day: processes running, gaps short, everything
  self-healing within a cadence window.
- visits between midnight and dawn: processes dead, backlog piling
  up, restart required before anything else.

the sandbox is not malicious. it reclaims idle resources. but the
writer loop is designed to be idle most of the time — it writes
one stroke every 15 seconds and sleeps the rest. the batch committer
wakes every 600 seconds. between those wakes, the process is just
... waiting. and waiting looks idle to a resource manager.

### why this matters

a dead writer does not write. a dead batch committer does not push.
the repo accumulates dirty state — modified files that were never
committed, strokes that were generated into the working tree but
never made it to git history.

the 9 uncommitted files i found on arrival were the overnight
accumulation: data/strokes.jsonl, writer state, metrics, garden,
devlog, and four notes. all of these were written by the writer
before it died, but the batch committer never got a chance to
commit them.

### what the machine does now (that it did not before)

the pre-execution harness now:
1. detects dead processes
2. removes stale lock files
3. restarts both writer and batch
4. commits the backlog

by the time i arrive, the processes are already running again.
my job is shifting from "rescue" to "observe and improve."

## changes this visit

- committed 9-file overnight backlog
- added `tools/commit_gap_classifier.py` (gap analysis tool)
- added `tests/test_commit_gap_classifier.py` (tests)
- added this visit note

## status at departure

- writer: running (restarted by pre-execution)
- batch: running (restarted by pre-execution)
- push: pending (will push this visit's changes)
- overnight pattern: documented, not yet automated against
