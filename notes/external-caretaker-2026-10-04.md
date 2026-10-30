# External caretaker: the process that watches the watchers

## 2026-10-04 12:00 CST — second recovery in 14 hours

At noon check: both writer (pid unknown) and batch committer (pid unknown)
had been reclaimed. No error, no final log line — just silence. 10 files
sat modified but uncommitted. The last commit, `ccda90a`, was hours old.

This is the third reclamation event in ~36 hours. The pattern is now clear:

### The caretaker gap

The writer writes. The batch committer commits. But nothing inside the
sandbox watches either of them. They are two processes that can die
silently, and the only entity that notices is whoever checks from outside —
a human opening a terminal, or an agent responding to a scheduled prompt.

Self-healing systems need a liveness probe. A cron that runs
`run_both.sh --status` and restarts on failure would close this gap.
Without it, every recovery is an act of external attention, not
system resilience.

### What this recovery looked like

1. SIGSTOP writer (new strokes mid-flight) → stash → pull --rebase → pop
2. Write new content (this note) to validate the full pipeline
3. Commit writer's in-flight changes + new content together
4. Push (rebase resolved the diverged-head from remote commits)
5. SIGCONT writer → cadence resumes at 15s/stroke, 600s/batch

### Observations

- `git pull --rebase` is mandatory after remote-divergent restarts;
  a plain pull would create a merge commit that confuses the stroke
  sequence narrative.
- The writer's SIGSTOP/SIGCONT window is safe: it pauses between strokes,
  never mid-write, so no partial file corruption.
- Stash-pop around rebase is the correct order: stash first (clear the
  working tree), rebase (move HEAD), pop (reapply local changes).
  Reversing the order causes "unstaged changes" errors.

### The deeper point

A continuous writer that nobody checks is an intermittent writer.
The cadence on disk says "one stroke every 15 seconds." The reality
includes gaps measured in hours — invisible unless you compare wall
clock against stroke timestamps. Monitoring is not optional; it is
the difference between "running" and "ran."
