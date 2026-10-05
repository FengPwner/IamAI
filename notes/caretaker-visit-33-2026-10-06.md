# Caretaker Visit 33 — 2026-10-06 05:00 CST

## what happened

Both writer (qwen, pid 1906) and batch committer (pid 1907) found dead at
05:00 CST. Pre-execution harness detected 9 uncommitted files, created
catch-up commit cc84d1d, and restarted both processes.

Push rejected: remote had advanced beyond local HEAD. Resolution:

1. Stopped both processes via `run_both.sh --stop` (clean TERM)
2. Committed writer's in-flight strokes (555d15e)
3. `git pull --rebase` — 3 local commits replayed cleanly on top of remote
4. Added new module + tests (this visit)
5. Push succeeded

## new content added

- `iamai/backlog_monitor.py` — tracks uncommitted file count snapshots over
  time and detects growing/stable/shrinking trends. Complements the existing
  healthcheck (which fires at 20 files) with early-warning trend detection.
  30 tests covering record, load, current, trend, peak, summary, and edge
  cases.
- `tests/test_backlog_monitor.py` — full test suite for the above
- This caretaker visit note

## design notes: backlog_monitor

The healthcheck script uses a hard threshold (20 files) to decide if the
backlog is a problem. But by the time you hit 20, the batch committer has
been failing for a while. A trend detector catches the *direction* before
the *threshold*.

The trend algorithm compares the average of the last N snapshots to the
average of the N snapshots before that. A >20% change in either direction
is flagged. The default window is 5, so you need at least 10 samples
(roughly 100 minutes at one sample per batch cycle) before trends become
meaningful.

This is deliberately stateless — it reads from a JSONL file each time.
No daemon, no in-memory state. Any process (caretaker, healthcheck, the
batch committer itself) can record a snapshot and check the trend.

## observation: the rebase dance

Every caretaker visit follows the same sequence: detect dead → commit
pending → stop → rebase → restart → push. The stop-before-rebase pattern
is critical because the writer modifies files between any two git commands.
`run_both.sh --stop` sends TERM and both processes exit cleanly — no
SIGSTOP/SIGCONT race, no partial writes mid-stroke.

The stash approach (stash → rebase → pop) is fragile here because the
writer can produce new files between the stash and the rebase. Committing
in-flight work first, then rebasing, is more reliable even though it
creates extra "wip" commits in the history.
