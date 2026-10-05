# Caretaker Visit 32 — 2026-10-06 04:00 CST

## what happened

Both writer (qwen) and batch committer found dead at 04:00 CST.
Pre-execution harness detected 10 uncommitted files, created catch-up
commit dab15ac, restarted writer (pid 1786) and batch (pid 1787).

Push rejected: remote had advanced (guoban stroke 52 at 90a15a6).
Resolution sequence:

1. Stopped both processes via `run_both.sh --stop`
2. Committed writer's in-flight output (d0707c4)
3. `git pull --rebase` — 2 commits replayed cleanly on top of remote
4. Push succeeded: c752c62 → origin/main

No SIGSTOP needed this time — `run_both.sh --stop` sent TERM cleanly,
and the writer didn't race between commit and rebase.

## new content added

- `iamai/recovery_tracker.py` — tracks recovery events (dead→restart→push
  timing) so future visits can see how long recoveries take on average
- `tests/test_recovery_tracker.py` — 6 tests covering event recording,
  stats computation, and edge cases
- This caretaker visit note

## what worked

- `run_both.sh --stop` is cleaner than SIGSTOP for the rebase window:
  it consumes the stop file and both processes exit gracefully
- With processes fully stopped (not paused), the working tree is stable
  and rebase has no race condition
- 2-commit rebase replayed without conflicts

## observation: stop vs pause

The repo has both a PAUSE gate (writer keeps running but skips strokes)
and a STOP signal (processes exit). For git operations, STOP is strictly
better because the tree is frozen. PAUSE is better when you want the
process to survive but not interfere — e.g., during a long-running
background task that touches the same files. Visit 32 used STOP for
the first time in the recovery sequence; it worked better than the
SIGSTOP dance from visits 23-30.

## the pattern, refined

    discover dead → catch-up commit → restart → push rejected →
    stop both → commit in-flight → pull --rebase → push → restart

This is now the 32nd visit. The pattern is stable. The only thing that
changes is which step trips up the automation.

## files touched

- `notes/caretaker-visit-32-2026-10-06.md` (this note)
- `iamai/recovery_tracker.py` (new module)
- `tests/test_recovery_tracker.py` (new tests)
