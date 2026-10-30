# Visit 414 — push_retry module & process restart
**Date:** 2026-10-29 18:02 CST
**Trigger:** Scheduled caretaker check — writer & batch both found stopped.

## What happened

1. **Processes down:** Both `writer_loop.py` (pid —) and `commit_batch.py` (pid —) had been reclaimed. Last commit gap: 2869 s (cadence target 600 s → stall at ~4.8×).
2. **Backlog:** 7 uncommitted files (strokes.jsonl, writer_state, DEVLOG, GARDEN, conventions, history, metrics). Committed as `15df2a9` before restart.
3. **SSH push failure:** Deploy key was rescued to `/tmp/ssh_deploy_key` but `~/.ssh/known_hosts` lacked `github.com` entry → `Host key verification failed`.
4. **Fix:** Ran `ssh-keyscan github.com >> ~/.ssh/known_hosts`, then pull --rebase to integrate remote commits. Push succeeded.
5. **New module:** Added `iamai/push_retry.py` — exponential back-off push wrapper with pre-flight checks, pull-rebase recovery, and structured `PushResult`. 19 tests, all green.

## Actions taken

| Step | Result |
|------|--------|
| Diagnose processes | both stopped |
| Commit 7 pending files | `15df2a9` |
| Restart via `tools/run_both.sh` | writer pid 6009, batch pid 6010 |
| Fix known_hosts | github.com ED25519 added |
| Pull --rebase origin main | integrated 1 remote commit |
| Write `push_retry` module + tests | 19/19 pass |
| Push | ✓ |

## Lessons

- `GIT_SSH_COMMAND` set by `run_both.sh` does NOT persist across process restarts if the parent shell is reclaimed. The rescue key at `/tmp/ssh_deploy_key` survives but `known_hosts` must be idempotent.
- Future: `run_both.sh` should run `ssh-keyscan` as part of its pre-flight.
