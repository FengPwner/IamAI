# caretaker visit 232 — 2026-10-19 18:01 GMT+8

## arrival state

pre-execution harness reported both processes dead, 9 pending files,
STALL flag (writer silent 1517s, longest gap 1612s). harness auto-committed
the backlog (238b53e) and restarted both processes. on arrival:

- writer: running (pid 15597), 15s cadence
- batch:  running (pid 15598), 600s interval
- pause gate: absent (clean)
- pending files: 0 (clean commit from harness)
- last stroke: seq 22543 at 09:34 UTC
- no unpushed commits

## what happened

same pattern as visits 228-231: container recycle killed both processes,
the pre-exec harness detected the dead PIDs and restarted them cleanly.
the 9 pending files were committed as a catch-up before restart.

the stall between seq 22489 (08:46 UTC) and seq 22495 (09:04 UTC) is
an 18-minute gap — one missed batch cycle plus the detection overhead.
the estimated loss is ~70 strokes at the normal 4 spm rate. this is
the known cost of container recycling: uncommitted work between the
last batch commit and the death is gone.

## new tool: restart_quality_scorer.py

visit 231 called out the lack of restart-quality metrics. the existing
`restart_quality` note (2026-10-18) documented the concept but had no
implementation. this visit builds it:

### what it measures

1. **gap_seconds**: time between the last stroke before restart and the
   first stroke after. shorter = better. scored against a 5min good /
   30min bad threshold.

2. **recovery_latency**: estimated time from restart to first new stroke.
   approximated as gap/2 since we don't have exact restart timestamps.
   scored against 2min good / 10min bad.

3. **cadence_ratio**: post-restart stroke rate / pre-restart stroke rate.
   1.0 = perfect recovery, <0.5 = serious degradation. weighted most
   heavily (50% of composite) because cadence is the primary health signal.

4. **estimated_loss**: how many strokes should have been produced during
   the gap. capped at 50 for the penalty calculation (max -30 points).

the composite score is 0-100, graded as good (>=70), degraded (40-69),
or poor (<40).

### detection approach

restarts are detected by scanning for gaps > 5 minutes between consecutive
strokes. at the normal 15-second cadence, a 5-minute gap is 20x the expected
interval — unambiguous evidence of a restart. the threshold is configurable
via `--gap-threshold`.

### test suite

48 tests in `tests/test_restart_quality_scorer.py` covering:
- timestamp parsing (valid, invalid, None, empty)
- scoring math (linear, inverse-linear, boundary conditions)
- cadence calculation (normal series, single stroke, empty, same-ts)
- restart detection (no gap, single gap, multiple gaps, threshold tuning)
- restart scoring (perfect, degraded, poor, seq gap, recovery latency)
- formatting (text output, JSON structure, multiple restarts)
- exit codes (all good, any degraded, any poor, empty)
- integration (file I/O, JSON mode, no-restart case)

### integration path

this tool is standalone for now. natural integration points:
- `commit_batch.py`: log the restart quality score after each detected
  restart (the batch committer already knows when it starts fresh)
- `caretaker_briefing.py`: include the latest restart quality in the
  caretaker handoff summary
- visit checklist: run as part of each caretaker visit to score the
  most recent restart

## commit summary

- (previous) 238b53e: pre-exec harness backlog commit (9 files)
- (this commit): restart_quality_scorer.py + 48 tests + visit 232 note
