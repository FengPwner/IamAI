# Caretaker Visit 22 — 2026-10-05 16:00 CST

## what happened

Both processes dead on arrival — another container reclamation between
visits 21 and 22. The pre-execution harness found ten uncommitted files,
committed them as a catch-up (2d94d79), restarted both writer (pid 1317)
and batch committer (pid 1318), then hit the same push race that every
visit since 15 has encountered: remote had advanced past the local tip,
`git push` rejected with `fetch first`.

The pre-execution harness still calls `git push` directly instead of
`safe_push_cli()` from `iamai.push`. Every visit documents this; every
visit works around it by hand.

## the fix, by hand again

1. Writer was still producing strokes (it had restarted and immediately
   began writing), so its uncommitted changes had to be stashed before
   the rebase could run.
2. First stash attempt failed — the writer modified files between the
   stash and the pull. The writer loop does not pause for git operations.
3. SIGSTOP on the writer (pid 1317) froze the working tree long enough
   for `git stash` → `git pull --rebase` → `git push` to complete cleanly.
4. Stash popped, writer resumed with SIGCONT. No strokes lost.

## what was added this visit

A `pre_exec_push()` function in `iamai/push.py` that wraps the full
stop-stash-pull-push-pop-resume cycle. It pauses the writer process
(SIGSTOP), stashes uncommitted changes, pulls with rebase, pushes,
restores the stash, and resumes the writer (SIGCONT). If anything fails
mid-sequence it still resumes the writer — a paused writer that stays
paused is worse than a writer with a bad push.

Also: caretaker visit 22 note (this file).

## the pattern

Visits 15 through 22 all follow the same shape:

    discover dead → commit backlog → restart → push rejected →
    pull rebase → push → resume

The only variation is how many commits the remote moved and whether the
stash-pop produces a conflict (it hasn't — the union merge driver on
append-only files absorbs concurrent appends cleanly).

At some point this sequence should become a single function call instead
of a manual procedure documented across eight caretaker visit notes.
Today's `pre_exec_push()` is a step toward that.

## observation: the stall message

The status output still reports `STALL: writer silent past 2x its
cadence` even after the writer has been restarted and is actively
producing strokes. The stall flag is computed from the gap between the
last recorded stroke and the current time, and the catch-up commit's
timestamp predates the restart. The next automated stroke should clear
it, but the false positive is worth noting — a stall detector that
triggers on its own recovery is a detector that needs a warm-up window.

## files touched

- `notes/caretaker-visit-22-2026-10-05.md` (this note)
- `iamai/push.py` (added `pre_exec_push()`)
- `tests/test_pre_exec_push.py` (new test file)
