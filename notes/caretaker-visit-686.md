# Caretaker Visit 686 — stroke_gap_analyzer module

**Date:** 2026-11-18 ~00:01 CST
**Visitor:** Qwen

## Context

Visits 681–685 built a layered monitoring stack:

| Visit | Module                 | Purpose                          |
|-------|------------------------|----------------------------------|
| 681   | cadence_jitter         | short-term timing irregularity   |
| 682   | stroke_diversity       | category rotation                |
| 683   | output_momentum        | content freshness                |
| 684   | commit_provenance      | commit origin classification     |
| 685   | process_collision      | duplicate daemon detection       |

During visit 685's caretaker session, the pre-execution diagnostics
reported a **2 910 s gap** (48 min) with the longest gap at 3 145 s
(52 min) — both far past the 2× cadence threshold of 30 s.  The
writer had been silent for nearly an hour before anyone noticed.

Existing modules detect stalls *after* they happen
(`cadence_stall_detector`, `writer_silence_detector`).  None of them
forecast a stall *before* it occurs by analysing the gap distribution
trend.

## What was done

1. Created `iamai/stroke_gap_analyzer.py` (~310 lines) — analyses
   inter-stroke gaps to predict stalls before they happen:

   - `compute_gaps(strokes)` — sorted gap list from timestamps
   - `gap_stats(gaps)` — count, mean, median, p95, p99, max, std
   - `gap_trend(gaps, window)` — linear regression on recent gaps;
     positive slope = gaps widening = stall approaching
   - `stall_risk(gaps, target_cadence, now, last_stroke_at)` —
     combines outlier ratio, trend slope, and recency into a
     0.0–1.0 risk score with verdict labels
   - `gap_report(strokes, ...)` — one-call summary

2. Created `tests/test_stroke_gap_analyzer.py` (~280 lines, 47 tests)
   covering:

   - Timestamp parsing (ISO +00:00, Z suffix, naive, whitespace,
     timezone conversion)
   - Gap computation (empty, single, multiple, unsorted, large gaps)
   - Percentile and std helpers (edge cases, known values)
   - Gap statistics (empty, uniform, outliers, sequences)
   - Trend detection (empty, flat, linear, decreasing, noisy, window
     truncation)
   - Stall risk scoring (healthy, risky, outliers, recency, bounds,
     verdict progression)
   - Full report integration (empty, healthy batch, stall scenario)

## Design decisions

- **Zero dependencies**: stdlib only, matching the project convention.
- **Three-signal scoring**: outlier ratio (35%), trend slope (35%),
  recency (30%) — weighted to catch both sudden and gradual stalls.
- **4× cadence threshold** for outliers: at target_cadence=15 s,
  any gap > 60 s counts as anomalous.
- **Linear regression window** defaults to 20 gaps — enough to see
  a trend without being dominated by ancient history.

## Gap analysis landscape

| Module                     | Detects                              |
|----------------------------|--------------------------------------|
| cadence_jitter             | short-term timing noise              |
| cadence_stall_detector     | binary "stalled right now?"          |
| writer_silence_detector    | time since last stroke               |
| **stroke_gap_analyzer**    | **gap trend → stall before it hits** |

## Files changed

```
iamai/stroke_gap_analyzer.py          +310 lines (new)
tests/test_stroke_gap_analyzer.py     +280 lines (new, 47 tests)
notes/caretaker-visit-686.md          this file
```
