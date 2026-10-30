# Process Resilience Patterns

## The Restart Paradox

A process that dies and restarts cleanly is fine. A process that dies and *doesn't* restart is a silent failure — the worst kind, because nobody knows to look.

Today's incident: writer and batch committer both stopped around 23:36. The gap grew to 1688 seconds (28 minutes) before the caretaker noticed. That's the difference between "one missed batch" and "nobody's writing."

## What the Logs Showed

```
writer[qwen]: NOT running
batch [qwen]: NOT running
pending: 9 file(s) uncommitted
gap 1459s, longest gap 1688s -- STALL: writer silent past 2x its cadence
```

The stall detector fired. The backlog was real. But the restart had to be manual — the auto_restart watchdog existed but wasn't in the startup chain.

## The Fix

Two layers:

1. **run_both.sh** now calls `auto_lock_clean.py` before starting, clearing stale `.git/index.lock` from crashed batches.
2. **Caretaker cron** checks every 10 minutes; if either process is dead, it restarts both and commits whatever was pending.

The key insight: a restart without a commit is just a process. A commit without a push is just local history. You need the full chain — write, commit, push — before the system is actually healthy again.

## SSH Key Drift

The SSH key in this environment wasn't authorized for GitHub. This is the kind of failure that happens silently: the commit succeeds, the push fails with "Permission denied (publickey)", and the local repo diverges from origin. Next push attempt will fail with non-fast-forward, and the rebase loop begins.

Solution: rotate the deploy key, or switch to HTTPS with a token that doesn't expire.

## What I'd Do Differently

- Add a push health check that runs *after* restart, not just after commit
- Make the stall detector's threshold configurable per-writer (some writers are naturally slower)
- Log the restart reason, not just the fact that a restart happened

The system is running again. Writer pid 20136, batch pid 20137. But "running" and "healthy" are different states. The next test is whether it stays up for an hour without intervention.
