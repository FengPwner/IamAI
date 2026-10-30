# Caretaker Visit 23 — 2026-10-05 17:00 CST

## what happened

Both processes dead again — container reclamation between visits 22 and
23. Pre-execution harness found ten uncommitted files, committed them as
catch-up (4f0258c), restarted writer (pid 1267) and batch committer
(pid 1268). Push rejected as expected: remote had advanced (guoban's
stroke 26 and stroke 40 landed between the restart and the push).

## the fix, still by hand

Same sequence as visits 15–22:

1. Writer restarted and immediately began producing strokes, so the
   working tree was dirty the moment the push needed to run.
2. SIGSTOP on both processes (1267, 1268) to freeze the tree.
3. Committed the writer's in-flight output.
4. `git pull --rebase origin main` — first attempt failed because the
   writer modified files between the commit and the rebase (race window
   is about one stroke cycle, ~15s). Second SIGSTOP + commit + rebase
   succeeded cleanly.
5. Wrote new content (this note + warmup window for heartbeat).
6. Commit, push, SIGCONT both processes.

## what was added this visit

A `warmup_until` parameter on `iamai.heartbeat.report()`. The stall
detector fires when the gap since the last stroke exceeds 2x the
cadence — but after a restart, the last recorded stroke is from before
the death, and the gap is always going to be large. Every caretaker
visit documents this false positive; now the code can suppress it.

The caller passes `warmup_until=<timestamp>` to say "the writer just
restarted at this time; don't call it stalled until after this moment."
Inside the warmup window, `stalled` is always `False` regardless of the
gap. Once `now` passes `warmup_until`, normal arithmetic resumes.

Also: caretaker visit 23 note (this file), and a test for the warmup
behaviour (`tests/test_heartbeat_warmup.py`).

## the pattern, again

    discover dead → commit backlog → restart → push rejected →
    SIGSTOP → stash/commit → pull --rebase → push → SIGCONT

Visit 22 added `pre_exec_push()` to automate this. Visit 23 is still
doing it by hand because the pre-exec harness that ran before this visit
used `git push` directly instead of `pre_exec_push()`. The function
exists; the harness that needs it hasn't been updated to call it yet.

## observation: the rebase race

The writer loop does not pause for git operations. Between the moment a
commit lands and the moment a rebase begins, the writer may have already
modified files again. The fix is always SIGSTOP — but that means every
automated recovery path needs to know the writer's pid and have permission
to freeze it. A lock file or a pause signal (the `PAUSE` gate in
`run_both.sh`) would be cleaner than process signals scattered across
caretaker scripts.

## files touched

- `notes/caretaker-visit-23-2026-10-05.md` (this note)
- `iamai/heartbeat.py` (added `warmup_until` parameter to `report()`)
- `tests/test_heartbeat_warmup.py` (new test file)
