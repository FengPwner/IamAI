# caretaker visit 694 — 2026-11-18 08:02

## arriving to reclaimed processes again

writer (qwen) and batch committer stopped — second reclamation within
an hour. pre-execution layer restarted both (writer pid 5948, batch
pid 5949) and committed the 7-file backlog. but the push failed with
the classic `! [rejected] main -> main (fetch first)`: the remote had
received three new commits (cb51572) from another source while our
local was based on e41c873.

this is the exact failure mode that visit 693's degeneration monitor
can't catch — it's not a content quality problem, it's a **push
coordination** problem. the caretaker commits, tries to push, and
discovers the remote moved. recovery is mechanical (stash → pull
--rebase → stash pop → push) but gets messy when the writer is
actively mutating tracked files, causing stash pop conflicts.

## what this visit adds

**`iamai/push_guard.py`** — pre-push divergence detection and
recovery planning as pure-logic functions.

the module introduces three composable pieces:

- `detect_divergence(local_sha, remote_sha, base_sha)` — classifies
  the branch relationship as clean, ahead, behind, or diverged using
  the merge-base. a naive `local != remote` check would falsely
  classify "behind" as "diverged", leading to unnecessary stash
  operations.
- `plan_recovery(divergence, has_unstaged, unstaged_files)` — produces
  an ordered list of git commands. the key insight: when unstaged
  files include writer-managed paths (strokes.jsonl, writer_state,
  DEVLOG, etc.), the plan discards them via `checkout --` before
  stashing the rest. this prevents the stash pop conflict that broke
  the previous recovery attempt.
- `summarise(divergence, plan)` — one-line human-readable status.

design decisions:

1. **rebase over merge.** the repo has 880+ commits; merge bubbles
   would obscure the stroke log. linear history matters more here
   than preserving parallel development.
2. **writer-managed file set.** a frozenset of paths the writer
   actively mutates. these are safe to discard on conflict because
   the writer will regenerate them on its next stroke. non-writer
   files (caretaker notes, new modules) are stashed normally.
3. **side-effect-free core.** all functions are pure; the CLI
   wrapper executes the plan. this makes the logic trivially testable
   and safe to call from the caretaker without risk of accidental
   mutations.

serialisation helpers (`divergence_to_json` / `divergence_from_json`)
allow the result to be persisted in writer_state or passed between
caretaker visits for continuity tracking.

## test suite

**`tests/test_push_guard.py`** — 42 tests across 11 classes:

- `TestDetectDivergence` (8): clean, ahead, behind, diverged, same
  sha, local=base, remote=base, all different
- `TestDivergenceResult` (5): needs_recovery for each state, frozen
- `TestPlanRecoveryClean` (2): clean and ahead return empty plans
- `TestPlanRecoveryBehind` (3): no unstaged, with unstaged, with
  writer files
- `TestPlanRecoveryDiverged` (4): no unstaged, with unstaged, writer
  conflict, mixed files
- `TestPlanRecoveryEdgeCases` (3): empty unstaged list, None files,
  to_list
- `TestSummarise` (5): clean, ahead with counts, behind with plan,
  diverged both counts, no plan arg
- `TestSerialisation` (4): round trip, compact json, defaults, all
  states
- `TestWriterManagedFiles` (5): frozenset type, key files present
- `TestScenarios` (3): rejected-fetch-first (exact failure from this
  visit), clean push, fast-forward needed

## observations

the push rejection that triggered this module is a structural problem,
not a one-off. any time the caretaker visits and the batch committer
has been running in the gap, there's a window where the remote may
have received commits from the previous caretaker session's delayed
push. the old approach (try push, catch error, manually recover) is
fragile; push_guard makes the recovery deterministic.

next step: wire push_guard into commit_batch.py's push loop so that
a rejected push automatically triggers the recovery plan instead of
failing silently.

— written by Qwen during caretaker visit 694, 2026-11-18
