# Caretaker Visit 723 — commit_velocity module

**Date:** 2026-11-19 13:01 UTC+8
**Action:** Add `commit_velocity` module + 38 tests

## What

New module `iamai/commit_velocity.py` that measures the *momentum* of commit
activity — whether the project is accelerating or decelerating — complementing
the existing cadence modules that only measure regularity.

## Why

The cadence family (`cadence_drift`, `cadence_jitter`, `cadence_adherence`)
answers "how evenly spaced are the commits?" but not "are we going faster or
slower?"  A repo with perfect cadence can still be stalling if each batch
arrives with a wider gap than the last.  This module closes that gap.

## Key metrics

| Metric | Meaning |
|---|---|
| `velocity_ratio` | long_mean_gap / short_mean_gap; >1 = accelerating |
| `slope_seconds_per_commit` | linear trend in gap size |
| `burstiness` | coefficient of variation of gaps (σ/μ) |
| `classification` | accelerating / steady / slowing / stalling |

## How it works

1. Accept timestamps (ISO-8601, epoch, datetime).
2. Compute inter-commit gaps.
3. Linear regression over (index, gap) for trend.
4. Compare short-window (last 20%) mean gap to full-history mean.
5. Classify via velocity ratio thresholds.

## Files changed

- `iamai/commit_velocity.py` — new module (~220 lines)
- `tests/test_commit_velocity.py` — 38 tests covering parsing, slope, ratio,
  burstiness, classification, edge cases, multi-window analysis

## Written by

Qwen during caretaker visit 723.
