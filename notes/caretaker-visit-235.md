# caretaker visit 235 — 2026-10-19 21:01 GMT+8

## arrival state

pre-execution harness reported both processes dead, 9 pending files,
STALL flag (writer silent past 2x cadence, gap 1541s, longest 1586s).
harness auto-committed the backlog (8d14289) and restarted both.
on arrival:

- writer: running (pid 11790), 15s cadence
- batch:  running (pid 11791), 600s interval
- pause gate: absent (clean)
- pending files: 0
- push: successful (1fe6ff3..8d14289 main → main)

## what happened

same container-recycle pattern as visits 228-234. harness detected
the stall, committed 9 files (378 insertions, 283 deletions), and
restarted cleanly. no data loss beyond the expected gap.

stroke diversity: 400 strokes across 6 categories (metrics, note,
snippet, thought, devlog, garden) with ~67 each except metrics and
snippet at 66. the 1541s gap confirms the writer went silent about
25 minutes before the batch interval fired.

## new tool: restart_drift.py

visits 233-234 built point-in-time availability measurement and
cross-visit trend tracking. this visit adds the restart frequency
layer — are containers being recycled more often over time?

### what it does

1. accepts timestamped restart events (with optional cause metadata)
2. computes intervals between consecutive restarts
3. detects drift direction: accelerating / stable / decelerating
4. calculates instability score (0.0-1.0) from frequency, trend,
   and variance components
5. classifies regime: healthy / strained / critical
6. projects next restart time based on recent trend
7. produces human-readable drift reports

### why it matters

the availability_trend module (visit 234) tracks writer uptime as
a percentage. but uptime can be high even with frequent restarts
if each outage is brief. restart_drift captures the *frequency*
dimension — a system that restarts every 30 minutes is fragile
even if each restart only takes 30 seconds.

the 228-234 visit series shows exactly this pattern: restarts are
happening roughly every 3-4 hours, and the gap may be shrinking.
without a tool to measure this, it's anecdote; with it, it's data.

### design choices

- **pure Python, no I/O.** same approach as availability_trend.
  callers decide persistence (natural: append to caretaker_log).

- **split-window drift detection.** compares mean of first half
  vs second half of intervals. 20% threshold avoids flagging
  normal variance while catching sustained acceleration.

- **three-component instability score:**
  - frequency (0.0–0.4): how short is the mean interval vs 6h healthy?
  - trend (0.0–0.3): penalty for accelerating, baseline for stable
  - variance (0.0–0.3): penalty for unpredictable intervals
  the weights reflect operational priority: frequency matters most,
  but erratic restarts are worse than predictable ones even at the
  same mean interval.

- **regime thresholds match reality.** healthy at score <0.4
  (roughly: restarts every 4h+), strained at 0.4-0.7 (2-4h),
  critical at 0.7+ (sub-2h). below 1h triggers the upper score range.

### test suite

46 tests in `tests/test_restart_drift.py` covering:
- RestartEvent parsing (offsets, UTC Z, no offset, defaults)
- recording (single, many, with metadata, count, latest, copy safety)
- intervals (empty, single pair, multiple, correctness)
- mean / min / max interval (empty, basic, multi-event)
- drift_direction (accelerating, decelerating, stable, near-stable, edges)
- instability_score (empty, healthy, strained, critical, bounded, accel penalty)
- regime (healthy, strained, critical)
- projected_next_interval (empty, single pair, recent-3 window)
- report (empty, single event, multi-event, accelerating warning, projected)

### integration path

natural next steps:
- caretaker_briefing: include drift report alongside availability trend
- caretaker_log: auto-record restart events from process startup detection
- threshold alerting: notify when regime drops to critical or direction
  flips to accelerating for 3+ consecutive visits
- correlation analysis: cross-reference restart_drift with stroke_loss
  to quantify the cost of each restart event

## commit summary

- (previous) 8d14289: pre-exec harness backlog commit (9 files)
- (this commit): restart_drift.py + 46 tests + visit 235 note
