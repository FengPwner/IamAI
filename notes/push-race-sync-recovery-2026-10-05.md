# Push-race recovery: 2026-10-05 03:00 CST

Same pattern as the 02:00 event (notes/overnight-stall-push-race-2026-10-05.md),
different hour. The writer and batch died, nine files sat uncommitted, and the
automated harness committed the backlog but could not push — remote had moved
ahead with two commits from another writer.

## what was different this time

The 02:00 recovery documented the problem. This one tested the documented
manual recovery path: stop processes, stash, rebase, push, pop, restart.
Six steps, each one necessary, none one sufficient.

The specific friction point was the writer staying alive between stash and
rebase. The writer modifies files every 15 seconds — by the time rebase ran,
the tree was dirty again and rebase refused. The fix was simple: stop the
writer first, stash, rebase, pop, then restart. Order matters.

## the gap this exposes

`iamai.push.push_with_rebase()` handles a clean tree. The pre-execution
harness calls plain `git push`. Neither handles the middle case: tree is
dirty, rebase is needed, and the writer is still producing strokes.

The new `iamai/sync.py` module fills that gap — stash, rebase, pop as one
atomic operation, with the push left to `push_with_rebase` afterwards.
Two concerns, two functions, one call site (`sync_and_push`).

## what was committed

- catch-up commit: 9 files from the stalled writer (af706c8, rebased to 231acd2)
- new module: `iamai/sync.py` — stash-rebase-pop cycle
- new tests: `tests/test_sync.py` — 17 tests covering happy path and all failure modes
- this note

## process state after recovery

- writer[qwen]: running (restarted via run_both.sh)
- batch[qwen]: running (restarted via run_both.sh)
- remote: synced (push accepted after rebase)
- pending: 0 uncommitted files
