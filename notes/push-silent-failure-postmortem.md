# Push Silent Failure Postmortem — 2026-10-26

## What happened

Container recycled at ~07:00 UTC. The SSH deploy key (`~/.ssh/id_ed25519`) was
ephemeral and lived only on the old container's filesystem. No backup existed in
the repo, no credential helper fallback was configured, and the git sshCommand
hardcoded the missing path. Writer and batch committer restarted cleanly via
`run_both.sh`, accumulated 60+ local commits, and never once pushed successfully.

The failure was silent from the user's perspective: processes were green, commits
were landing, strokes kept flowing. Only an explicit `git push` probe revealed
the `Permission denied (publickey)` error.

## Root cause

Single point of failure: one file on one ephemeral filesystem. No backup, no
health check that surfaces push failures to the caretaker before they accumulate.

The irony is not lost: the repo already contains `push_key_recovery.py`,
`push_key_watchdog.py`, `push_preflight.py`, and `ssh_key_mismatch.py` — four
modules about the exact failure mode that took us down. Theory without a
runbook is just poetry.

## What should have caught it

A pre-commit or post-commit hook that runs `push_preflight.py --fix` before the
batch committer fires. If the key is missing, the committer should refuse to
accumulate more than N unpushed commits and escalate to the caretaker.

## What to build next

- `push_silent_failure_detector.py`: count consecutive failed pushes, alert
  after threshold (default: 3 failures or 30 minutes, whichever comes first)
- Credential readiness check in `commit_batch.py` before starting the interval
  timer — don't commit if you can't push
- Store the deploy key in a location that survives container recycle, or use
  HTTPS with a token from a secrets manager

## Numbers

| Metric | Value |
|--------|-------|
| Unpushed commits at detection | 60 |
| Time from recycle to detection | ~1600s |
| Strokes written during blackout | ~400 |
| Data at risk if disk lost | ~314k lines |

## Lesson

A local commit is not a saved commit. Push health is as critical as writer
health. The caretaker should treat N consecutive push failures the same way it
treats writer silence: as an emergency, not a footnote.
