# caretaker visit 204 — 2026-10-18 13:00

## what happened

caretaker checked the IamAI repo at 13:00 CST on request from the user.

- pre-execution diagnostics showed both writer and batch had been recycled
  by the sandbox — pids gone, 8 files uncommitted, heartbeat flagged STALL
  (gap 1571 s, longest 1719 s)
- `.git/index.lock` was left behind by a crashed git process, blocking
  the backlog commit with `fatal: Unable to create ... File exists.`
- removed the stale lock file manually
- committed the 8 pending files (strokes, state, docs, notes) as
  `catch-up: commit 8 pending files at 13:00`
- `tools/run_both.sh` was invoked during pre-execution; it refused to
  double-start because the sandbox had already respawned the processes
  (writer pid 30103, batch pid 30104)
- push check: `Everything up-to-date` — the batch committer had already
  pushed before the recycle

## diagnosis

the stall was caused by sandbox process recycling, not a code bug.
the writer was producing strokes normally until the sandbox killed it;
the batch committer's last commit was at 12:24, leaving ~36 minutes of
uncommitted work.  the stale index.lock was a second-order effect from
the same crash — a git operation was interrupted mid-flight.

history.md revealed a longer-running quality issue: the writer has been
producing repetitive "nothing new to add there" entries for thousands of
strokes (stroke 20651–20825+), all cycling through the same three pool
modules (`parse_kv.py`, `retry.py`, `chunk_text.py`).  this is the
designed fallback when snippet files already exist on disk, but it means
1/6 of all strokes are waste.

## new contribution

added `iamai/pool_saturation.py` — measures what fraction of recent strokes
are the "nothing new to add" fallback, classifying the pool as fresh,
warming, or saturated.  thresholds: <10% fresh, 10–25% warming, >=25%
saturated.  pure function of stroke texts, no filesystem or git dependency.

added 23 tests in `tests/test_pool_saturation.py` covering:
- marker detection (exact match, partial, case sensitivity, empty)
- basic measure (empty, all-normal, all-exhausted, window truncation)
- verdict thresholds (boundary values at 10% and 25%)
- realistic rotation patterns (1/6 and 2/6 exhaustion rates)
- report formatting (fresh, saturated, empty)
- fraction rounding (4 decimal places)

## status

processes healthy (writer pid 30103, batch pid 30104).
cadence running at 15 s per stroke, 600 s per commit.
pool is saturated — recommend expanding `iamai/pool.py` with new snippets
or adjusting the writer to skip the snippet kind when saturation > 25%.
