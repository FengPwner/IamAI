# caretaker visit 677 — 2026-11-17 15:02

## status on arrival

both processes **dead** (writer + batch). pre-execution trace confirmed:
`needs_restart: True`, 7 files uncommitted. additionally, `push` had
failed — remote `main` had advanced (doubao's hourly backstop at d78793b)
and the local branch diverged.

on top of that, `.git/index.lock` was stale — a leftover from the batch
committer's last attempt before it died. three layers of failure: dead
processes, diverged branch, stale lock.

## what was done

1. **processes restarted** — writer pid 4626, batch pid 4627 (restarted
   by pre-execution trace before this visit's commit phase).
2. **stale lock cleaned** — removed `.git/index.lock` manually.
3. **stash → rebase → pop** — rebased local `4acada1` on top of remote
   `d78793b`. stash pop clean, no conflicts.
4. **backlog committed** — catch-up commit already done by pre-exec.
5. **new module: `git_lock_monitor`** — detects and safely cleans stale
   git lock files. 28 tests.

## git_lock_monitor

this visit's failure mode was the inspiration. the batch committer tried
to commit, crashed (or was killed), and left `.git/index.lock` behind.
every subsequent git operation failed with the opaque "File exists"
error until someone manually removed it.

`git_lock_monitor` automates that cleanup:

- `check_and_clean(repo, max_age_s=120)` — the main entry point.
  checks if the lock exists, measures its age, and removes it only
  if it exceeds the staleness threshold. fresh locks (from live git
  operations) are left alone.
- `is_locked(repo)` — quick boolean check.
- `lock_age(repo)` — seconds since the lock was created, or None.

the design is conservative: age-based only (no PID checking, which is
fragile and races), 120-second default threshold (normal git ops in
this repo finish in < 30s), and every failure mode returns a structured
dict instead of raising.

the batch committer should call `check_and_clean()` before every commit
attempt. if the result is `"error"`, log it and skip the cycle rather
than crashing on the lock.

## observation

three stacked failures is a pattern, not bad luck. the process dies →
leaves a lock → the next process can't commit → diverges from remote →
push fails. each layer hides the one before it. the fix is not just
restarting processes but checking for collateral damage (stale locks,
unpushed commits) as part of the restart sequence. the auto_push_recovery
module handles the divergence half; git_lock_monitor handles the lock
half. together they should make the batch committer self-healing for
this specific failure chain.
