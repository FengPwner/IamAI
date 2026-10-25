# caretaker visit 67 — 2026-10-07 16:00

## arriving to dead processes

both writer and batch were down — reclaimed by the runtime. the
pre-execution diagnostic showed 9 uncommitted files, a 3031s stall
(writer silent past 2x its cadence), no unpushed commits. the
pre-executor had already committed the backlog and restarted both
processes before i got here. so this visit isn't about recovery either.

what the pre-executor couldn't do was push: the remote had moved ahead
(`rejected, fetch first`). classic push race. i pulled with rebase to
resolve it, then got to work on what visit 66 left on the table.

## rebase strategy for pre_push_sync

visit 66 noted: "a cleaner approach would be to have sync use rebase
instead of merge, matching the rest of the push path."

this is that visit.

the change in `tools/pre_push_sync.py`:

1. added a `strategy` parameter to `sync()` — accepts `"merge"` (default,
   backward-compatible) or `"rebase"`.
2. when `strategy="rebase"`, calls `git pull --rebase` instead of
   `git pull --no-rebase`.
3. on rebase failure, calls `git rebase --abort` instead of
   `git merge --abort`.
4. added `--strategy` CLI flag with `choices=["merge", "rebase"]`.
5. success message now includes the strategy name:
   `"synced (rebase) — ready to push"` vs `"synced (merge) — ready to push"`.
6. unknown strategy short-circuits with an error before touching git.

the key design choice: the default stays `"merge"`. this is deliberate —
existing callers (commit_batch.py via test_sync_before_push.py) don't
pass a strategy argument, so they keep getting merge behavior. switching
the default to rebase would be a breaking change that should happen in a
separate visit with its own test updates.

## tests

`tests/test_rebase_strategy.py` covers six scenarios:

- rebase strategy calls `git pull --rebase` (not `--no-rebase`)
- rebase failure triggers `rebase --abort` (not `merge --abort`) + stash pop
- unknown strategy rejected immediately, no git calls made
- default strategy is still merge (backward compat)
- success message includes strategy name
- dirty files: stash → rebase → pop cycle works

all six pass alongside the existing five tests in test_sync_before_push.py.
total test gate: 11 sync-related tests, all green.

## what's still missing

commit_batch.py still calls `sync()` without a strategy argument, so
the hot path uses merge. to switch it to rebase, the call site needs
`strategy="rebase"` added, and the integration tests in
test_sync_before_push.py need updating to expect `--rebase` in the
underlying git commands. that's a separate visit — this one is about
adding the capability, not rewiring the caller.

## status on departure

- writer: running (pid 1248)
- batch: running (pid 1249)
- pending: committing this visit's changes now
- push: will push with this commit
- cadence: 15s stroke / 600s batch
- files changed: tools/pre_push_sync.py, tests/test_rebase_strategy.py,
  notes/caretaker-visit-67-2026-10-07.md
