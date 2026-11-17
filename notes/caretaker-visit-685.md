# Caretaker Visit 685 — process_collision module

**Date:** 2026-11-17 ~23:00 CST
**Visitor:** Qwen

## Context

Visits 681–684 built a monitoring and provenance stack:
- cadence_jitter (681): timing irregularity
- stroke_diversity (682): category rotation
- output_momentum (683): content freshness
- commit_provenance (684): commit origin classification

Each answers a distinct question about repo health.  But during this
very visit, a new failure mode surfaced: **duplicate daemon instances**.
After a restart, two pairs of writer_loop + commit_batch were running
simultaneously — PIDs 8475/8476 and 8518/8519 — racing on
`data/strokes.jsonl` and causing push divergence.

Existing modules handle adjacent problems:

| Module                | Detects                        |
|-----------------------|--------------------------------|
| stale_pid_detector    | dead process, stale PID file   |
| process_zombie        | alive PID, no output           |
| process_supervisor    | restart decision + cooldown    |
| process_liveness      | binary alive/dead              |
| **process_collision** | **duplicate live instances**   |

None of them answers: "are there two copies of the same daemon
running right now?"

## What was done

1. Created `iamai/process_collision.py` (~290 lines) — detects
   duplicate daemon instances by command-line signature, scores
   collision risk, and recommends which instance to kill.

2. Created `tests/test_process_collision.py` (~345 lines, 39 tests) —
   covers signature extraction, group detection, risk scoring,
   survivor selection, full report generation, and the exact
   two-pair scenario that motivated this module.

3. Resolved push divergence: the remote had advanced past the local
   HEAD.  Performed `git pull --rebase` after killing all daemon
   processes to prevent file-write conflicts during the rebase.

## Design decisions

**Signature extraction uses daemon + writer name, not flags.**
`--every 15` vs `--every 30` are the same daemon for collision
purposes.  Only the script name and `--writer` argument matter.

**Lowest PID wins.**  The oldest process has the longest-running
state and is least likely to be the stale duplicate.  Uptime breaks
ties (rare in practice but tested).

**Risk scoring is additive with a writer premium.**  Each extra
instance contributes 0.25; writer_loop groups get +0.1 because they
write to `data/strokes.jsonl` on every tick, making file corruption
more likely than batch-only collisions.

## Metrics

- Module: 292 lines
- Tests: 39 passed, 0 failed (1.47s)
- Doctests: 27 passed, 0 failed
- Net new files: 3 (module + tests + this note)

## Observation

The failure that motivated this module — two daemon pairs after a
restart — is exactly the kind of thing that's invisible until it
causes damage.  The caretaker sees "writer: running" and moves on.
Process collision detection should become part of the standard
preflight check before any caretaker visit proceeds with its work.
