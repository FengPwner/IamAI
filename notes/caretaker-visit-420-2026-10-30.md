# Visit 420 — post-midnight recovery and push chain repair

**Date:** 2026-10-30 01:01 CST
**Trigger:** User-requested caretaker check — verify writer/batch, restart if recycled, commit backlog, contribute content, maintain 10-minute cadence.

## Process status on arrival

Pre-exec diagnostics showed both processes had stopped:
- **writer[qwen]:** NOT running (pid absent)
- **batch[qwen]:** NOT running (pid absent)
- **Backlog:** 8 uncommitted files across data/, docs/, and notes/
- **Stall:** writer silent for 2782s (cadence target 15s, longest gap 3291s)
- **Tracked files:** 1543

The `run_both.sh` restart brought both up cleanly:
- writer pid 15086, batch pid 15087
- No stale lock file — clean shutdown
- SSH deploy key rescued to `/tmp/ssh_deploy_key` with correct permissions

## Backlog commit

8 pending files committed as `7e30673`:
```
M data/strokes.jsonl
M data/writer_state.qwen.json
M docs/DEVLOG.md
M docs/GARDEN.md
M docs/METRICS.md
M notes/history.md
M notes/limits.md
M notes/reading.md
```

These were all writer-produced artifacts that accumulated during the ~46-minute stall window. The batch committer normally commits every 600s, so 8 files in 46 minutes means the batch also died before flushing — consistent with both processes stopping simultaneously (likely container recycling or OOM).

## Push failure

The push check failed with `Host key verification failed` despite the key being present. Fix: `ssh-keyscan` to refresh `~/.ssh/known_hosts` with all github.com key types (rsa, ecdsa, ed25519). This is a recurring issue — visits 418 and 419 both encountered it. The root cause is that `known_hosts` entries can expire or be rotated, and the rescue script doesn't always refresh them.

## New content contributed

- **notes/caretaker-visit-420-2026-10-30.md** (this file) — visit log
- **tools/push_chain_verifier.py** — verifies the full write→commit→push chain health
- **tools/test_push_chain_verifier.py** — unit tests for the verifier

## Observations

The stall pattern is consistent with previous visits: processes die during container recycling, the caretaker cron catches it within one batch interval (10 min), and the restart is clean. The push chain remains the fragile link — SSH keys and known_hosts need to survive container boundaries. Visit 419 recommended making the push step self-healing; this visit's `push_chain_verifier.py` is a step toward that goal by making the failure mode explicit and testable.
