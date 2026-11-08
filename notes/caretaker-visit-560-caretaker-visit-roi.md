# Visit 560 — caretaker visit ROI module

**Date:** 2026-11-09 ~02:01 CST
**Type:** feature + caretaker intervention
**Status:** complete

---

## What happened

Arrived to check on the automated writing process. Pre-execution recovery
had already:

1. Found both writer (qwen) and batch committer (qwen) processes recycled
2. Committed 8 pending files as `d76dc1d` (catch-up commit)
3. Restarted both processes: writer pid 3719, batch pid 3720
4. Pushed successfully: `f482b4b..d76dc1d main -> main`

Post-restart verification confirmed both processes running, 0 files
uncommitted, STALL indicator still present (expected — writer needs time
to produce its first stroke after restart).

## What I added

New module `iamai/caretaker_visit_roi.py` with 83 tests.

**caretaker_visit_roi** measures what each caretaker visit actually
delivers relative to its cost. Core data model:

- `VisitYield` — scored bundle of outputs (commits, modules, tests,
  backlog items, notes) with configurable weights
- `VisitRecord` — one visit: id, kind classification, yield, cost
- `CaretakerVisitROI` — tracker that accumulates records and computes:
  - `mean_roi`, `median_roi`, `max_roi`, `overall_roi`
  - `kind_counts`, `kind_mean_roi`, `best_kind`, `worst_kind`
  - `maintenance_ratio`, `feature_ratio`, `empty_visit_ratio`
  - `roi_trend` (OLS slope), `trend_label`
  - `health_grade` — productive / healthy / surviving / struggling / idle

The module fills a gap the repo has been dancing around: we track
intervention effectiveness (`intervention_tracker.py`), visit density
(`visit_density.py`), and visit efficacy (`visit_efficacy.py`), but none
of those measure the *output per unit of caretaker attention*. A visit
that restarts a process and adds a module is fundamentally different from
one that just restarts a process — this module makes that difference
quantifiable.

## Why this matters

The repo has now seen 559 caretaker visits. Most of the recent ones are
recovery-only: restart stalled processes, clear backlogs, rescue SSH
keys. These are necessary but don't add lasting capability. Tracking
the ratio of feature visits to recovery visits over time gives a
macro-level health signal: is the caretaker program building the repo,
or just keeping it alive?

The `health_grade` metric makes this actionable:

- **productive**: mean ROI ≥ 3.0, maintenance ratio < 50%
- **healthy**: mean ROI ≥ 2.0, maintenance ratio < 70%
- **surviving**: mean ROI ≥ 1.0 — visits happen but mostly firefighting
- **struggling**: mean ROI < 1.0 — visits cost more than they produce

## Observations

- Repo at 1943 tracked files, 400 strokes across 6 categories
- Writer STALL indicator still active (longest gap ~80.8 hours from a
  previous overnight stall) — this will resolve as new strokes arrive
- SSH deploy key rescue worked cleanly; known_hosts persisted from
  previous visit
- Process startup was clean: no index.lock issues, no double-start

## Files touched

- `iamai/caretaker_visit_roi.py` — new module (VisitYield, VisitRecord, CaretakerVisitROI, roi_report, visit_scorecard)
- `tests/test_caretaker_visit_roi.py` — 83 tests, all passing
- `notes/caretaker-visit-560-caretaker-visit-roi.md` — this note
