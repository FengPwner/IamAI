# Caretaker Visit 101 — 2026-10-09 12:00 CST

## what happened

pre-execution healthcheck reported both writer and batch as NOT running,
8 uncommitted files pending, a STALL condition (gap 3003s, threshold 3005s),
and a stale `.git/index.lock` blocking all git operations. a prior push
attempt had been rejected with `[rejected] main -> main (fetch first)`
because the remote had advanced beyond the local ref.

this visit was a full recovery cycle: clear the lock, rebase onto remote,
commit the backlog, restart the processes, then add new work.

## actions taken

1. removed stale `.git/index.lock` — the lock had no live holder
   (consistent with the self-healing pattern from visits 97–100).
2. ran `git pull --rebase origin main` — remote had 2 new commits
   (guoban stroke 121 and a catch-up restart). rebase succeeded
   cleanly with no conflicts.
3. committed 2 remaining uncommitted state files (writer_state.qwen.json,
   notes/history.md) as `904c027 caretaker: flush 2 pending state files
   (post-rebase catch-up at 04:00 UTC)`. the original 8 pending files
   had been partially resolved by the rebase — 6 were auto-merged, 2
   remained as working-tree modifications.
4. restarted writer and batch via `run_both.sh`. both came up cleanly:
   writer pid 1236, batch pid 1237. cadence resumed at 15s intervals
   with a gap of only 9 seconds — effectively immediate.
5. authored new module `iamai/push_preflight.py` — composite pre-push
   checklist that runs three checks (index_lock, divergence, dirty_tree)
   in a single call and returns a structured report. motivated by the
   exact failure sequence this visit repaired: lock blocking commits,
   then divergence blocking push. a single preflight call would have
   surfaced both problems before the batch committer attempted either
   operation.
6. authored `tests/test_push_preflight.py` — 22 tests covering all three
   checks in isolation (clean, stale, active lock; up-to-date, ahead,
   behind, fetch-failure divergence; clean, dirty, git-failure tree),
   the composite preflight (all-pass, one blocker, multiple blockers,
   string path, check independence), the one-liner report, and three
   integration tests against a real temporary git repo.
7. authored this visit note.

## the push_preflight module

the interesting design choice in push_preflight is check independence.
early drafts ran checks sequentially and short-circuited on the first
failure. this is wrong for a pre-push checklist: you want to see *all*
problems at once, because fixing them has different costs. clearing a
stale lock is instant; a divergence rebase takes seconds; committing
dirty files might require judgment. if the checker only reports one
blocker at a time, you fix it, re-run, see the next one, fix it, re-run
— three round trips for what should be one pass.

the module imports from index_lock_detector and git_divergence rather
than duplicating their logic. composition over reimplemention keeps the
behavior consistent: if detect_lock changes its stale-detection heuristic,
preflight gets the fix for free.

one subtlety: the dirty_tree check uses `git status --porcelain` rather
than `git diff --name-only`. porcelain is designed for machine parsing
and includes both staged and unstaged changes in a single pass. diff
only shows unstaged, which would miss files that are staged but not yet
committed — a dangerous blind spot before a push.

## the index.lock pattern — five visits and counting

visits 97 through 101 all observed the same sequence: pre-exec detects
a stale lock, the lock is cleared (manually or by the process itself),
operations resume. at this point the pattern is so reliable that it
could be automated — the batch committer could call push_preflight
before every push attempt and auto-clear stale locks. the reason it
is not automated yet is caution: an automated lock clearer that runs
at the wrong moment (e.g., while a real git process is starting up)
could cause the exact corruption it is trying to prevent. the safe
version would need to check the lock age (not just staleness) and
wait a few seconds before clearing. that logic belongs in a future
visit.

## state on exit

- writer: running (pid 1236, cadence 15s, producing normally)
- batch: running (pid 1237, interval 600s)
- pause: no
- uncommitted: this visit's files (to be committed below)
- push: will include all accumulated commits

## tree stats

- 528 tracked files
- 1066 commits (this visit will be 1067+)
- 2035 strokes logged
- 71 Python modules in iamai/
- 120 test files (was 119 before this visit)
