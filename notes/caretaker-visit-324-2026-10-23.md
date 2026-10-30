# Caretaker Visit 324 — 2026-10-23 21:01 CST

## What happened

Caretaker arrived to find both writer and batch processes had been
reclaimed since visit 323. The pre-execution harness handled recovery:

### Recovery (automated)

1. Detected 9 uncommitted files (strokes + state drift accumulated
   during the gap between visit 323 and process deaths).
2. Committed backlog as `69a03211` — "catch-up: commit pending
   changes before process restart" (9 files, 415 insertions, 313 deletions).
3. Restarted via `tools/run_both.sh`:
   - writer pid 5851 (qwen, 15 s cadence)
   - batch  pid 5852 (qwen, 600 s interval)
4. Push was rejected: remote `main` had advanced (visit 323's push
   plus a `guoban-note.md` update from origin). Resolved with
   `git pull --no-rebase` merge strategy.

### Push race detail

The push failure is the familiar pattern documented in stroke 256:
the push race is a clock, not a bug. The sequence was:

    local commit → push rejected (fetch first)
    → stash unstaged writer output
    → pull --no-rebase (merge commit)
    → ready to push

One new insight: the writer kept producing strokes even during the
git conflict resolution, which caused `git stash` to fail on the
first attempt because the writer re-dirtied files between the stash
and the rebase. Solution was to stop the writer briefly, stash,
pull, then restart.

### New content this visit

Added **resurrection_tracker** module + 48 tests:

The repo already has `process_reclaim_detector.py`, `stall_classifier.py`,
and `restart_quality_scorer.py`. What was missing is a focused tool that
analyzes the *pattern* of process deaths — not just detecting them, but
classifying whether they're random, clustered, or periodic.

`resurrection_tracker` scans git log for catch-up commits, pairs them
with timestamps, and produces:

| metric               | description                                      |
|----------------------|--------------------------------------------------|
| MTBR                 | mean time between resurrections (hours)           |
| gap distribution     | quartiles of intervals between deaths             |
| cluster detection    | groups of ≥2 deaths within a configurable window  |
| verdict              | healthy / noisy / unstable                        |

This complements `restart_quality_scorer.py` (which scores individual
restarts) by looking at the population-level pattern.

### Why this matters

A process that dies once every two weeks is background noise.
One that dies three times in an hour during peak commit windows
suggests a resource contention issue — maybe the writer and batch
processes are stepping on each other's git operations. The tracker
makes that pattern visible without requiring anyone to manually
read through 300+ caretaker visit logs.

## Status at departure

- writer: running (pid 5851)
- batch:  running (pid 5852)
- pending: 0 uncommitted files (after this commit)
- push: pending merge push (will succeed after this commit)
