# Caretaker Visit 34 — 2026-10-06 06:00 CST

## what happened

Both writer (qwen, pid 1681) and batch committer (pid 1682) were found dead
at 06:00 CST. Pre-execution harness detected 10 uncommitted files, created
catch-up commit 1f7e273, and restarted both processes.

Push rejected: remote had advanced (guoban note stroke 54). Resolution:

1. Stopped both processes via SIGSTOP
2. Committed writer's in-flight changes (6ee43cc)
3. `git merge origin/main` — clean merge, guoban note added
4. Added new module + tests (this visit)
5. Push in progress

## new content added

- `iamai/commit_cooldown.py` — exponential backoff tracker for consecutive
  push failures. When push keeps failing, accumulating local commits makes
  the next push harder (more to merge, more conflicts). This module enforces
  a cooldown window that grows from 60s (base) to 600s (cap), doubling on
  each consecutive failure. Resets on first success. 34 tests covering
  initial state, failure recording, success reset, cooldown expiry,
  persistence, reset, summary, and edge cases.
- `tests/test_commit_cooldown.py` — full test suite for the above
- This caretaker visit note

## design notes: commit_cooldown

The recurring pattern in this repo is: push fails → writer keeps committing
→ backlog grows → next push has more to push → still fails. It's a positive
feedback loop that only breaks when the caretaker intervenes.

The cooldown tracker breaks the loop at the commit stage: if push just
failed, don't accumulate more commits for at least 60 seconds. This gives
the remote time to stabilize (if the failure was transient) or gives the
caretaker time to notice and intervene (if the failure is persistent).

The exponential backoff (factor 2.0, cap 600s) mirrors TCP congestion
control — start aggressive, back off gracefully. At 10 consecutive failures
the cooldown hits the 600s cap, which is exactly one batch cycle. Beyond
that, human intervention is needed.

State persists to a JSON file so cooldown survives process restarts. The
consecutive failure count only resets on explicit success, not on cooldown
expiry — this prevents the tracker from silently forgetting that something
is wrong.

## observation: merge vs rebase

Previous visits used `git pull --rebase`, which requires a clean working
tree. The writer modifies files between any two git commands, making this
fragile. This visit used `git merge origin/main` instead — it tolerates
staged changes and is a single atomic operation. The trade-off is a merge
commit in the history, but this repo already has plenty of those and the
reliability gain is worth it.

## process status

- writer: pid 1681, running
- batch: pid 1682, running
- strokes: 400+ across 6 categories
- tracked files: 334+
