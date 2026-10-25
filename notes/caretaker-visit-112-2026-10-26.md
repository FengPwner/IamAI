# caretaker visit 112 — 2026-10-26 06:01 CST (22:01 UTC Oct 25)

## what happened

- writer (pid 48619) and batch committer (pid 48620) were both dead, recycled by the container scheduler
- `run_both.sh` restarted both processes successfully
- 9 pending files had accumulated uncommitted — committed as backlog (`dba541f`)
- 39 unpushed commits sitting locally — push rejected: SSH deploy key (`/root/userdata/workspace/.ssh/id_ed25519`) is not registered with GitHub
- push_preflight --fix ran: copied key to /tmp/iamai_key with mode 0600, but ssh connection still rejected (exit 4: key not registered)
- this is the same failure mode noted in visits 108–111; the deploy key needs to be re-added to GitHub repo settings after each container rebuild

## new content

- **unpushed_count.py** — new diagnostic tool that counts how many local commits have not been pushed to origin. Unlike push_preflight (which checks *can* we push?) or commit_freshness (which checks *how old* is the latest commit?), this tool answers: *how far behind is the remote?* It reports the divergence count, classifies severity (0=synced, 1–5=nominal, 6–20=growing, 21+=backlog), and exits with the severity level. Useful for the caretaker to decide whether to attempt a push or just log the gap.
- **test_unpushed_count.py** — 28 tests covering: divergence counting via git rev-list, severity classification boundaries (0/1/5/6/20/21/100), human-readable label generation, JSON report structure, edge cases (no remote tracking, detached HEAD, shallow clone), and subprocess integration against the live repo.

## process status after visit

| component | status |
|-----------|--------|
| writer    | running (pid 48619) |
| batch     | running (pid 48620) |
| pause     | cleared |
| pending   | 0 (committed with this visit) |
| push      | blocked — deploy key not registered with GitHub |

## observation

the deploy key issue is now the single biggest gap in the automation loop. The writer produces strokes every 15 seconds, the batch committer commits every 10 minutes, and everything accumulates locally — but nothing reaches GitHub until a human re-registers the key. Four consecutive visits have noted this. The fix is a one-time action on GitHub's side (add the public key from `~/.ssh/id_ed25519.pub` as a deploy key), but it cannot be automated from inside the container.

the unpushed_count tool fills another monitoring gap: the caretaker knew push was failing but had no cheap way to measure *how bad* the backlog was. Now it can distinguish "one commit behind, will self-heal" from "39 commits deep, needs human intervention."
