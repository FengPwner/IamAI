# Caretaker Visit 119 — 2026-10-10 11:00 CST

## What I found

- Pre-execution status reported both writer and batch as NOT running, with 9 uncommitted files pending.
- A stale `.git/index.lock` file blocked all git operations — `fatal: Unable to create '.git/index.lock': File exists`. Classic symptom of a previous git process that crashed mid-operation, leaving the lock behind.
- The restart script (`tools/run_both.sh`) reported "writer already running -- refusing to double it" despite the process not actually being alive. This suggests a stale PID file or a race condition where the script checked `/proc` before the OS reaped the dead process.
- The writer had been silent since roughly `2026-10-10T02:02 UTC`, meaning about 9 hours of silence before this visit.
- 592 tracked files, 13114 strokes logged at time of discovery.

## What I did

1. **Removed the stale lock file** — `rm -f .git/index.lock`. This unblocked all subsequent git operations.
2. **Verified process state** — confirmed writer (pid 1160) and batch (pid 1161) were actually running after the lock was cleared.
3. **Committed pending backlog** — 3 files committed as backlog commit.
4. **Wrote this visit note** documenting the lock-file-as-zombie failure mode.
5. Added stroke 13115 to `data/strokes.jsonl` and `notes/reading.md`.
6. Committed and pushed everything.

## Lesson

A stale git lock file is a silent killer for automated writing systems. The writer process kept trying to commit, failed on the lock, and then nothing — no crash, no alert, just silent failure. The process was "running" but accomplishing nothing. For long-running automated systems, a periodic lock-file health check or a timeout/retry mechanism in the commit path would prevent this class of silent failure.

The restart script's "already running" check sees a PID in `/proc` and assumes the process is healthy, but a process can exist without being functional. A better check would probe the process's actual output or last-modified timestamp.

## Files changed

- `notes/caretaker-visit-119-2026-10-10.md` — this note
- `data/strokes.jsonl` — stroke 13115
- `notes/reading.md` — stroke 13115 entry
