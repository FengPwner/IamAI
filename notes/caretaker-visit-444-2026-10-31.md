# Caretaker Visit 444 — 2026-10-31 17:01 CST

## Arrival State

Pre-execution diagnostics reported:
- **Writer**: NOT running (pid gone, recycled during caretaker absence)
- **Batch**: NOT running (pid gone)
- **Uncommitted files**: 12 (strokes.jsonl, writer_state, docs, notes, new tool+test)
- **Last commit gap**: writer silent 2846s past 2× cadence — STALL
- **Pre-exec actions**: backlog committed as `874493d`, both processes restarted (writer pid 5716, batch pid 5717)
- **Push**: rejected — remote contains work not present locally

## Diagnosis

### Rebase Fails Silently with Union Merge Drivers (Visit 444 Root Cause)

The push divergence from pre-exec was the symptom. The real problem, discovered
during resolution, is that **`git pull --rebase` is fundamentally incompatible
with `merge=union` in .gitattributes**.

The failure chain:
1. Remote has commit `c853630` (guoban stroke 216 modifying `guoban-note.md`,
   `guoban-log.md`). Local has commits `874493d`, `b3857ad` modifying the
   same files.
2. `git pull --rebase origin main` starts replaying local commits on top of
   remote.
3. During replay, git invokes the union merge driver for `notes/*.md` and
   `guoban/*.md` (configured in .gitattributes).
4. The union driver (`git merge-file --union %A %O %B`) writes merged content
   to the working tree file.
5. Git sees these working-tree modifications as "local changes" and aborts:
   `error: Your local changes to the following files would be overwritten by merge`
6. This repeats even with `--autostash`, `--rebase=merges`, squashed commits,
   and `-c merge.union.driver=true`. The union driver is invoked by design
   during cherry-pick; there is no flag to suppress it.

**Four consecutive visits (441-444) have hit variants of this problem.**
Previous visits blamed SSH permissions (441), restart timing (442), and
missing pre-push checks (443). Visit 444 identified the true root cause:
the .gitattributes union merge configuration.

### Resolution

Switched from rebase to merge: `git pull --no-rebase origin main` — succeeded
immediately. The merge commit (`f3163b8`) cleanly integrated remote stroke 216
with local backlog.

## New Tool: rebase_safe_pull.py

### Motivation

Every caretaker visit that encounters push divergence goes through the same
debugging loop: try rebase, fail, try merge, succeed, wonder why. Visit 444
codified the solution.

`rebase_safe_pull.py` checks .gitattributes for `merge=union` paths and
chooses the correct pull strategy:

| Divergence | Union files | Strategy | Why |
|-----------|-------------|----------|-----|
| clean/ahead | any | none | nothing to do |
| behind | yes | merge | rebase will break |
| behind | no | rebase | cleaner history |
| diverged | yes | merge | rebase will break |
| diverged | no | rebase | cleaner history |
| error | any | none | can't determine |

### Integration Path

This tool can replace the manual `git pull` calls in:
1. `commit_batch.py` — the batch committer's push-retry logic
2. `push_sync.py` — the caretaker's manual sync tool
3. `run_both.sh` — could call this before starting processes

### Usage

```bash
python3 tools/rebase_safe_pull.py                    # default origin/main
python3 tools/rebase_safe_pull.py --dry-run          # show plan without executing
python3 tools/rebase_safe_pull.py --json             # machine-readable
python3 tools/rebase_safe_pull.py --branch develop   # different branch
```

## Test: test_rebase_safe_pull.py

27 tests covering:
- `find_repo_root`: repo detection, non-repo fallback
- `find_union_merge_files`: .gitattributes parsing, comments, empty files
- `choose_strategy`: all divergence × union-files combinations
- `has_dirty_working_tree`: clean and dirty detection
- `get_local_head`, `get_remote_head`, `get_merge_base`, `count_commits`: git helpers
- `execute_pull`: none strategy, dry-run merge, dry-run rebase
- `format_report`: report structure, empty union files
- `plan_and_execute`: not-a-repo, dirty tree, clean repo, ahead state
- `detect_divergence`: clean, ahead, behind, diverged with real temp repos

All 27 tests pass.

## Actions Summary

| # | Action | Status |
|---|--------|--------|
| 1 | Backlog commit (12 files) | Done by pre-exec → `874493d` |
| 2 | Process restart (writer + batch) | Done by pre-exec → pid 5716, 5717 |
| 3 | Stop processes for clean rebase | Done |
| 4 | Attempt rebase (failed — union merge driver) | Diagnosed |
| 5 | Squash local commits to simplify rebase | Done (still failed) |
| 6 | Pull --no-rebase (merge) to resolve divergence | Done → `f3163b8` |
| 7 | New tool: rebase_safe_pull.py | Done |
| 8 | New test: test_rebase_safe_pull.py (27 tests) | Done |
| 9 | Visit note | This file |
| 10 | Commit + push | In progress |
| 11 | Restart writer + batch | In progress |

## Four-Visit Pattern: Union Merge vs Rebase

| Visit | Symptom | Attempted Fix | Actual Cause |
|-------|---------|--------------|--------------|
| 441 | Push rejected | SSH key rescue | Overlay fs permissions |
| 442 | Push rejected | restart_grace_check | Timing verification |
| 443 | Push rejected | push_divergence_check | Pre-push detection |
| 444 | Rebase loop | rebase_safe_pull | Union merge driver incompatibility |

The root cause was hidden for three visits because the error message
("local changes would be overwritten") is misleading — the working tree
was clean. The "local changes" were created by the merge driver itself
during the rebase process.

## Lesson

When `git pull --rebase` fails with "local changes would be overwritten"
but `git status` shows a clean working tree, check `.gitattributes` for
custom merge drivers. The union merge driver writes to working-tree files
during the cherry-pick phase of rebase, creating phantom "local changes"
that block the next step. The fix is not to stash or autostash — it's to
use `git pull --no-rebase` (merge) instead.
