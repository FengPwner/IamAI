# caretaker visit 234 — 2026-10-19 20:01 GMT+8

## arrival state

pre-execution harness reported both processes dead, 9 pending files,
STALL flag (writer silent past 2x cadence, gap 1482s, longest 1586s).
harness auto-committed the backlog (aa0a0f6) and restarted both.
on arrival:

- writer: running (pid 10742), 15s cadence
- batch:  running (pid 10743), 600s interval
- pause gate: absent (clean)
- pending files: 0
- push: successful (e9d0fd6..aa0a0f6 main → main)

## what happened

same container-recycle pattern as visits 228-233. harness detected
the stall, committed 9 files (422 insertions, 319 deletions), and
restarted cleanly. no data loss beyond the expected gap.

stroke diversity shows the usual pattern: 400 strokes across 6 categories
(metrics, note, snippet, thought, devlog, garden) with ~67 each except
devlog and garden at 66. the 1482s gap at arrival confirms the writer
went silent well before the batch interval fired.

## new tool: availability_trend.py

visit 233 built the stroke_loss_tracker for point-in-time availability
measurement. this visit adds the trend layer — aggregating those
readings across visits into a time series.

### what it does

1. accepts `Reading` objects (timestamp, visit number, availability %)
2. computes rolling average over a configurable window
3. classifies trend direction: improving / stable / degrading
4. assigns regime: healthy (>=85%) / strained (60-85%) / critical (<60%)
5. detects regime changes between consecutive readings
6. tracks worst consecutive streak below threshold
7. produces human-readable trend reports

### why it matters

the 60% availability problem identified in visit 233 is a trend, not
a point-in-time issue. individual visit notes capture snapshots but
no tool was connecting them. availability_trend bridges that gap:
a caretaker can now record each visit's reading and immediately see
whether things are getting better, worse, or holding steady.

### design choices

- **pure Python, no I/O.** all state is in-memory. callers decide
  whether to persist to disk (natural: append readings to a JSONL
  alongside the caretaker_log). this keeps the module testable and
  free from filesystem assumptions.

- **direction via split-window comparison.** compares the average of
  the most recent half against the earlier half within the window.
  avoids over-reacting to single-reading fluctuations while still
  catching sustained shifts.

- **regime boundaries match operational reality.** 85% is healthy
  because the system has inherent overhead (batch intervals, commit
  latency). 60% is the critical threshold because visit 233 measured
  exactly that — the system can survive at 60% but it's clearly
  unsustainable long-term.

- **worst streak tracking.** a single bad reading is noise; a streak
  of 5+ below 60% is a pattern. this metric helps distinguish
  transient container recycling from systemic degradation.

### test suite

51 tests in `tests/test_availability_trend.py` covering:
- Reading regime classification (healthy, strained, critical, boundaries)
- optional field defaults
- record / record_many / count / latest / readings-copy
- rolling_avg (empty, single, multiple, window clamping, explicit n)
- direction (improving, degrading, stable, two-reading edges)
- regime / regime_changed (all transitions, same-regime, single, empty)
- min/max availability (empty, basic, windowed, explicit n)
- worst_streak (empty, all healthy, broken streak, custom threshold, all below)
- total_loss (empty, basic, windowed)
- report (empty, normal, regime change, no change)

### integration path

natural next steps:
- `caretaker_briefing.py`: include the latest trend report in handoff
- `caretaker_log.py`: auto-record availability readings from visit data
- visit checklist: run trend report at visit start to see trajectory
- threshold alerting: notify when regime drops to critical

## commit summary

- (previous) aa0a0f6: pre-exec harness backlog commit (9 files)
- (this commit): availability_trend.py + 51 tests + visit 234 note
