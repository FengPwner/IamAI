# Visit 559 — commit rhythm drift module

**Date:** 2026-11-09 ~01:02 CST
**Type:** feature + caretaker intervention
**Status:** complete

---

## What happened

Arrived to find both writer (qwen, pid unknown) and batch (qwen) processes
recycled. Diagnosis confirmed `needs_restart: True`. Pre-execution recovery
had already:

1. Committed 7 pending files as `33a74f9` (catch-up commit)
2. Restarted both processes: writer pid 3569, batch pid 3570
3. Pushed successfully: `5b3f67a..33a74f9 main -> main`

## What I added

New module `iamai/commit_rhythm_drift.py` with 37 tests.

**commit_rhythm_drift** measures how actual commit intervals deviate from
the 10-minute (600s) target cadence. Key metrics:

- `mean_drift_ratio` — average deviation as fraction of target
- `max_drift_ratio` — worst single-interval deviation
- `trend` — OLS slope of drift over time (negative = recovering)
- `grade` — steady / drifting / erratic / stalled

This fits the repo's observability theme: we already track commit age
(`commit_age.py`), cadence adherence (`cadence_adherence.py`), and
intervention effectiveness (`intervention_tracker.py`). Rhythm drift
fills a gap — it detects *gradual cadence degradation* before it becomes
a full stall, rather than measuring stalls after the fact.

## Why this matters

A stall is the loud failure. Drift is the quiet precursor. If the mean
drift ratio climbs from 5% to 15% over a few hours, the caretaker can
intervene *before* the writer falls silent. The trend metric makes this
actionable: positive slope = rhythm getting worse even if individual
gaps look acceptable.

## Observations

- Repo is at 1940 tracked files, 400 strokes across 6 categories
- The overnight stall (longest gap 290862s ≈ 80.8 hours) dominates the
  `max_drift_ratio` whenever it's in the window — consider filtering
  outliers or using median-based metrics for production monitoring
- SSH deploy key rescue worked cleanly this visit; known_hosts persisted

## Files touched

- `iamai/commit_rhythm_drift.py` — new module (IntervalDrift, CommitRhythmDrift, rhythm_health, drift_report)
- `tests/test_commit_rhythm_drift.py` — 37 tests, all passing
- `notes/caretaker-visit-559-commit-rhythm-drift.md` — this note
