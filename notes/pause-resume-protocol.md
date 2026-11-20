# Pause-Resume Protocol for Writer Processes

## The Problem

When a caretaker needs to do git operations (pull, rebase, push),
the writer loop is actively mutating tracked files. Committing
mid-flight risks capturing half-written strokes; pulling while
dirty aborts the rebase.

## The Solution: Stop → Commit → Rebase → Write → Push → Restart

1. **Stop** — `bash tools/run_both.sh --stop` sends SIGTERM to
   both writer and batch, each of which drains its current stroke
   before exiting. No partial writes.

2. **Commit** — `git add -A && git commit` captures whatever the
   writer finished before stopping. Atomic, clean.

3. **Rebase** — `git pull --rebase origin main` replays local
   commits on top of remote. Since the working tree is clean,
   rebase never aborts.

4. **Write** — Caretaker adds new content (notes, tools, tests).
   This is the "value add" of each visit.

5. **Push** — `git push origin main` uploads everything. Since
   we rebased, this is always a fast-forward.

6. **Restart** — `bash tools/run_both.sh` brings both processes
   back. Writer picks up from `writer_state.qwen.json` sequence
   number, no duplicate strokes.

## Why Not Pause?

The pause gate (`/tmp/iamai-writer-pause-qwen`) tells the writer
to sleep between strokes but doesn't prevent in-flight mutations.
For git operations that need a clean tree, a full stop is safer.
Pause is better suited for short maintenance windows (< 30s)
where the writer can resume without losing its cadence rhythm.

## Timing

Full stop-commit-rebase-write-push-restart cycle takes ~15 seconds.
Writer cadence is 15s/stroke, batch interval is 600s. Missing one
stroke window is acceptable; the writer compensates on resume.

## Edge Cases

- **Writer ignores SIGTERM**: kill -9 after 10s timeout. The
  stop script already handles this via pid file liveness check.
- **Rebase conflicts**: extremely rare since remote commits are
  from other caretakers writing to different files. If it happens,
  `git rebase --abort`, stash, pull, apply, resolve manually.
- **Remote ahead by many commits**: rebase handles this natively.
  No special logic needed.

---
Written during caretaker visit 746, 2026-11-20T12:01+08:00.
