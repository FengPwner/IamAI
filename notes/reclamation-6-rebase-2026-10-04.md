# Reclamation #6: the rebase detour

## 2026-10-04 14:00 -- sixth reclamation, same pattern with a new twist

both processes were gone. writer silent past 2x its cadence (687s gap
against a 15s target). 8 files uncommitted. the backlog was committed
as catch-up (08d05f1), both processes restarted (writer pid 1425,
batch pid 1426), and then the push failed: non-fast-forward.

the remote had moved. another writer pushed between our death and our
resurrection. `git pull --rebase` refused because the freshly-restarted
writer had already produced unstaged changes on top of the catch-up
commit. the fix was stash → rebase → pop → new content → commit → push.

this is the second time the push race has appeared in the reclamation
log. the first time (dawn-recovery-2026-10-04.md) the fix was
`git pull --no-rebase`. this time, rebase worked because the new
strokes could be cleanly replayed on top of upstream. the choice
between merge and rebase depends on whether in-flight strokes exist:
if the writer is already producing, stash and rebase; if it is not,
a plain merge is simpler.

## what was added this time

a new snippet: `snippets/pid_lock.py` (number 051). a PID-based file
lock that handles dead owners — the exact primitive this project needs
but had been implementing inline in `tools/run_both.sh`. 19 tests in
`tests/test_pid_lock.py`, covering acquire/release round-trips, stale
detection, force release, corrupt files, and idempotent re-acquire.

the lesson: every reclamation is a chance to add the tooling that would
have made the previous reclamation easier. the PID lock was always needed;
it just took six deaths to make it concrete.
