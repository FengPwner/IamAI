# Caretaker Visit 304 — 2026-10-23

## What I did

Added `commit_fragmentation` module (61 tests pass) + visit-304 note.

Detects scattered micro-commits that should have been batched into
single cohesive commits.  Scores clusters of consecutive small changes
on file cohesion, temporal tightness, and change-volume ratio.

## Why this module

The gap between `commit_redundancy` (overlapping successive commits) and
`commit_substance` (individual commit quality) was a *grouping* gap: a
sequence of tiny commits touching related files isn't redundant — each
one adds something new — but the history would be cleaner and
bisect-friendlier if they were one commit.  The fragmentation detector
surfaces this signal.

Previous caretaker visits built tools to measure *what* each commit
contains (`commit_substance`), *whether* it duplicates its neighbour
(`commit_redundancy`), and *when* sessions start and stop
(`commit_session_segmenter`).  None of those asked "should these five
commits have been one?" — that's the question `commit_fragmentation`
answers.

## Design decisions

- **Cluster-first, score-second**: `detect_clusters` groups commits by
  time proximity; `analyse_cluster` then scores each group.  This
  separation lets callers adjust cluster sensitivity independently of
  the scoring model.
- **Three-metric blend**: file cohesion (do neighbours touch the same
  files?), temporal tightness (are they packed relative to overall
  cadence?), and change-volume ratio (are they small?).  Each captures
  one dimension of "should these have been batched?"
- **Size-weighted aggregate**: `fragmentation_score` weights each
  cluster by its commit count so a 10-commit cluster influences the
  verdict more than a 3-commit one.
- **`fragmentation_timeline`** for sliding-window analysis: mirrors the
  pattern from `commit_rhythm_classifier` to let callers see how
  fragmentation evolves across a long session.

## Where it fits

```
stroke_dedup → commit_substance → commit_redundancy → *commit_fragmentation*
                                                          ↑
                                                   groups of small commits
                                                   that belong together
```

The module sits at the boundary between individual commit quality and
session-level patterns.  It answers the question: "is the writer
batching sensibly, or sprinkling micro-changes across the history?"

## Process health

- Writer recovered from overnight stall (gap 1571s, was 1879s longest).
- 9 pending files committed as catch-up before this visit.
- Back to active cadence: 400 strokes across 6 categories.
- No lock contention after clearing stale index.lock.
