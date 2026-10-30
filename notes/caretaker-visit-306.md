# Caretaker Visit 306 — 2026-10-23

## What happened

The pre-execution check showed both writer and batch committer dead,
with nine pending uncommitted files and a stale `.git/index.lock`.
After restarting via `run_both.sh`, the catch-up commit succeeded but
the push was rejected: `non-fast-forward` — the remote had received a
guoban note (stroke 159) while our local branch was building its own
catch-up commit on top of the same parent.

Resolution: `git rebase origin/main` (with a stash dance for the
writer's concurrent modifications), then push. Total downtime from
first stall detection to clean push: under two minutes.

## What this teaches

The interesting pattern here is the **push race window**. When the
writer is active (one stroke every ~15 seconds) and the batch
committer runs every 600 seconds, there is a window of up to ten
minutes where local commits accumulate without pushing. During that
window, any other writer (guoban, a manual commit, another caretaker
visit) can push to the same branch and create divergence.

Three observations:

1. **Divergence is a timing problem, not a content problem.** The
   local and remote commits touched completely different files
   (guoban's note vs. qwen's catch-up). A merge would have been
   trivial. The cost was purely in the detection and reconciliation
   steps, not in resolving conflicts.

2. **The batch committer's interval sets the vulnerability window.**
   At 600 seconds, there are up to 40 writer strokes between pushes.
   Shortening the interval reduces the window but increases push
   frequency (and potential rate-limit issues). The current 10-minute
   batch interval is a reasonable compromise for a single-writer
   repo but becomes fragile with multiple writers.

3. **Rebase-before-push should be automatic.** The current flow is:
   commit → push → (fail) → diagnose → fetch → rebase → push. If
   the batch committer did a `git pull --rebase` before each push
   attempt, the divergence window would shrink to near zero. This
   is the gap that the new `remote_drift` module is designed to
   address at the analysis level.

## What was added

- **`iamai/remote_drift.py`** (53 tests): detects and measures
  divergence between local and remote tracking branches. Provides
  `measure_drift()` for live repo analysis and `analyse_counts()`
  for pure scoring without git access. Includes `classify_drift()`,
  `is_push_safe()`, and `suggest_action()` for pipeline integration.

## Process status at visit time

| check | status |
|-------|--------|
| writer running | yes (pid 90884) |
| batch committer running | yes (pid 90885) |
| pending uncommitted files | 3 (writer still producing) |
| remote drift | resolved (rebased and pushed) |
| push race window | ~600s (batch interval) |
