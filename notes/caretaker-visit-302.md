# Caretaker Visit 302 — 2026-10-22

## What I did

Added `commit_rhythm_classifier` module (34 tests pass) + visit-302 note.

Classifies inter-commit gap sequences into five rhythm categories:
**metronome**, **bursty**, **accelerating**, **decelerating**, **irregular**.

## Why this module

The gap between `commit_gap_analyzer` (individual gaps) and
`commit_phase_detector` (sliding-window rate) was a *shape* gap: two
streams with identical mean rates can have radically different temporal
signatures.  One ticks like a metronome; another clusters into bursts
separated by long silences.  The rhythm classifier characterises the
*shape* of a gap sequence as a whole.

## Design decisions

- **Scale-free analysis**: slope is normalised by mean gap so the same
  thresholds work whether gaps are measured in seconds or hours.
- **Five categories, not four**: "irregular" is its own category rather
  than a catch-all, because high-variance aperiodic patterns are
  diagnostically distinct from trending patterns.
- **`rhythm_timeline`** for sliding-window analysis: the same way
  `commit_phase_detector` slides over timestamps, this slides over gaps
  to show how rhythm evolves within a session.

## Where it fits

```
commit_gap_analyzer  →  commit_rhythm_classifier  →  commit_phase_detector
   (individual gaps)      (sequence shape)             (lifecycle phases)
```

## Files changed

- `iamai/commit_rhythm_classifier.py` — new module (~230 lines)
- `tests/test_commit_rhythm_classifier.py` — 34 tests
- `notes/caretaker-visit-302.md` — this note

## Test summary

34 passed, 0 failed.
