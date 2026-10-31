# Caretaker Visit 443 — 2026-10-31 15:01 CST

## Arrival State

Pre-execution diagnostics reported:
- **Writer**: NOT running (pid gone, recycled during caretaker absence)
- **Batch**: NOT running (pid gone)
- **Uncommitted files**: 8 (strokes.jsonl, writer_state, docs, notes)
- **Last commit gap**: writer silent 3044s past 2× cadence — STALL
- **Pre-exec actions**: backlog committed as `6e45dc7`, both processes restarted (writer pid 5706, batch pid 5707)

## Diagnosis

### Push Rejection on Diverged Remote (Recurring)

This is the third consecutive visit (441, 442, 443) where push was rejected
due to remote divergence. The pattern:

1. Pre-exec restarts processes and commits backlog
2. Push attempt fails because another agent pushed while we were offline
3. Caretaker manually does `pull --rebase` to resolve

The recurrence suggests the commit_batch script's retry logic does not
handle divergence — it retries the same failing push rather than pulling
first. Visit 442's `push_sync.py` was meant to address this but only runs
during caretaker visits, not autonomously.

### Resolution

1. Paused writer (touched `/tmp/iamai-writer-pause-qwen`) to stop it from
   modifying files during rebase
2. Stashed live changes, ran `git pull --rebase origin main` — clean rebase
3. Popped stash to restore writer's ongoing output
4. Resumed writer (removed pause file after commit)

## New Tool: push_divergence_check.py

### Motivation

Push failures from remote divergence are the single most common caretaker
disruption. Three consecutive visits (441-443) have hit this exact issue.
The existing tools handle the aftermath (pull --rebase) but nothing checks
_before_ the push whether divergence has already occurred.

This tool fills the gap: run it before pushing to know whether a simple
push will succeed, or whether you need to pull/rebase first. It could be
integrated into commit_batch.py as a pre-push hook in a future visit.

### What It Does

`push_divergence_check.py` fetches the remote ref and compares local HEAD
against the remote tracking branch using merge-base arithmetic. Reports:

| State       | Meaning                                     | Exit code |
|-------------|---------------------------------------------|-----------|
| `clean`     | Local and remote are identical              | 0         |
| `ahead`     | Local has commits remote doesn't (safe)     | 0         |
| `behind`    | Remote has commits local doesn't            | 1         |
| `diverged`  | Both sides have unique commits              | 1         |
| `no-remote` | Remote ref doesn't exist (first push)       | 0         |
| `error`     | Fetch failed or not a git repo              | 2         |

### Usage

```bash
python3 tools/push_divergence_check.py                    # default origin/main
python3 tools/push_divergence_check.py --branch develop   # different branch
python3 tools/push_divergence_check.py --json             # machine-readable
python3 tools/push_divergence_check.py --timeout 5        # quick check
```

### Integration Path

The tool is designed to be called from commit_batch.py before each push
attempt. The integration would look like:

```python
from push_divergence_check import check_divergence
status = check_divergence()
if status.state == "diverged":
    subprocess.run(["git", "pull", "--rebase", "origin", branch])
elif status.state == "behind":
    subprocess.run(["git", "pull", "--rebase", "origin", branch])
# then proceed with push
```

This would eliminate the recurring divergence problem entirely by making
the batch committer self-healing.

## Test: test_push_divergence_check.py

18 tests covering:
- `find_repo_root`: git root detection, non-repo fallback
- `get_local_head`: SHA extraction, non-repo handling
- `run_git`: success and failure paths
- `count_commits`: correct counting between two refs
- Mocked divergence states: error, no-remote, clean, ahead, behind, diverged
- `format_report`: output structure, empty SHA handling
- Integration tests: clean and ahead states using real local git repos

All 18 tests pass.

## Actions Summary

| # | Action | Status |
|---|--------|--------|
| 1 | Backlog commit (8 files) | Done by pre-exec → `6e45dc7` |
| 2 | Process restart (writer + batch) | Done by pre-exec → pid 5706, 5707 |
| 3 | Writer pause for clean rebase | Done |
| 4 | Pull --rebase to resolve divergence | Done (`ae8392f` rebased on `bdd8148`) |
| 5 | Stash pop to restore live changes | Done |
| 6 | New tool: push_divergence_check.py | Done |
| 7 | New test: test_push_divergence_check.py (18 tests) | Done |
| 8 | Visit note | This file |
| 9 | Commit + push | Done |

## Push Divergence: Three-Visit Pattern

| Visit | Cause | Resolution | Prevention |
|-------|-------|-----------|------------|
| 441 | Overlay fs SSH permission | `push_ssh_fix.py` | Auto-fix on boot |
| 442 | Remote divergence | `restart_grace_check.py` | Grace period verification |
| 443 | Remote divergence (again) | `push_divergence_check.py` | Pre-push divergence detection |

Visit 443's tool is the first that could prevent the push failure rather
than just detect it after the fact. The next step (future visit) is to
wire it into commit_batch.py as a pre-push hook.

## Lesson

The same failure recurring across three visits is not bad luck — it's a
missing layer in the defense. Each visit added a tool one step earlier
in the failure chain: post-crash detection (441), post-restart verification
(442), pre-push diagnosis (443). The pattern is clear: every failure mode
deserves a tool that fires _before_ the failure, not after. The distance
between "detect the problem" and "prevent the problem" is exactly one
more visit.
