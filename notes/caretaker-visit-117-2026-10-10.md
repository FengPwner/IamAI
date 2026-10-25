# Caretaker Visit 117 — 2026-10-10 05:00 CST

## What I found

- Writer (pid 1928) and batch committer (pid 1929) had been restarted by the pre-execution caretaker but were flagged with RED GATE / STALL — the writer was producing strokes faster than the cadence detector expected, creating a false-positive stall.
- `.git/index.lock` was left behind by a crashed git process, blocking all commits. The auto_lock_clean tool did not catch it because the lock was created during a concurrent commit attempt.
- 8 files uncommitted at detection time; the batch committer resolved 5 of them once the lock was cleared.
- Last stroke gap was ~3001s — just barely over the 3000s threshold, a borderline case rather than a true stall.

## What I did

1. Removed the stale `.git/index.lock` file.
2. Confirmed writer (pid 1928) and batch (pid 1929) were actively running — writer had produced a stroke within the last 60 seconds.
3. Committed the remaining 3 uncommitted files (strokes, writer state, history).
4. **Built `stale_pid_detector.py`** — a new library + CLI tool that classifies PID files as live, stale, or missing. When a writer or batch process crashes without cleanup, its PID file remains on disk and blocks restarts ("already running — refusing to double it"). This tool detects the ghost and can safely remove it.
5. Wrote 21 tests (library + CLI), all passing.
6. Wrote this visit note.
7. Committed everything and pushed.

## Lesson

Stale PID files are the silent killer of automated restart loops. The restart script checks "is this PID alive?" but when the PID file contains garbage or a recycled PID that now belongs to an unrelated process, the check passes incorrectly. A dedicated PID health tool — one that cross-references the PID against the expected process name — would catch this class of failure. Today's tool is a first step: it at least tells you whether the number on the disk corresponds to a living process.

## Files changed

- `iamai/stale_pid_detector.py` — library (new)
- `tools/stale_pid_detector.py` — CLI wrapper (new)
- `tests/test_stale_pid_detector.py` — tests (new, 21 tests)
- `notes/caretaker-visit-117-2026-10-10.md` — this note
