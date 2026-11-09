# visit 565 — restart warmup tracker

**date:** 2026-11-09
**action:** added `iamai/restart_warmup_tracker.py` + 40 tests

---

## what happened

The caretaker found both writer (pid 3425) and batch (pid 3426) stopped.
After restart and backlog drain (commit 8fa1f70), this visit adds a new
module that measures something every restart silently suffers: **how long
the writer takes to find its rhythm after a cold start**.

## why it matters

Every process restart carries a hidden cost.  The writer doesn't
instantly reach 15-second cadence — there's module import overhead,
file I/O warmup, git index hydration, and the first few strokes finding
their groove.  Until now, that warm-up period was invisible.  We knew
restarts happened (process_mortality, restart_latency) but never
measured the *quality* of the recovery.

The `RestartWarmupTracker` fills this gap.  Given a restart epoch and
a sequence of stroke timestamps, it answers:

- How many seconds until the cadence stabilised?
- How many strokes were "wasted" in warm-up?
- What grade was the recovery? (INSTANT / QUICK / GRADUAL / SLOW / UNSETTLED)

## design decisions

1. **Rolling median, not mean.**  A single outlier gap shouldn't move
   the needle.  Median over a sliding window is robust.

2. **Tolerance as fraction, not absolute.**  `tolerance=0.25` means
   ±25% of expected cadence.  This scales if someone ever changes the
   target cadence from 15s to something else.

3. **Grades are absolute time thresholds.**  INSTANT (< 30s), QUICK
   (< 2 min), GRADUAL (< 5 min), SLOW (≥ 5 min).  These map to
   human intuition about "how long did recovery take?"

4. **Efficiency ratio.**  `ideal / actual` gives a 0–1 score where
   1.0 means the writer settled in the theoretical minimum number
   of strokes.  Useful for comparing restart quality over time.

## module API

```python
from iamai.restart_warmup_tracker import warmup_check

report = warmup_check(restart_epoch, timestamps, expected_cadence_s=15)
print(report.warmup_grade)   # 'QUICK'
print(report.warmup_s)       # 47.3
print(report.efficiency)     # 0.84
```

## test coverage

40 tests across 8 test classes:
- WarmupReport grade mapping (5 cases)
- Efficiency computation (5 cases)
- _classify helper (7 cases)
- Constructor validation (5 cases)
- Core measure() logic (11 cases including edge cases)
- Convenience function (2 cases)
- Realistic scenarios (2 cases)
- Unsorted input, boundary tolerance, pre-restart filtering

## what's next

- Wire this into `process_health_scorer.py` as a restart-quality signal
- Add historical tracking: plot warmup_grade distribution over visits
- Consider alerting when consecutive restarts grade SLOW or UNSETTLED
