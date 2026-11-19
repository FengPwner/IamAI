# Caretaker Visit 726 — 2026-11-19

## Status on arrival

- writer[qwen]: running (pid 5966) — restarted by pre-exec
- batch[qwen]: running (pid 5967) — restarted by pre-exec
- 7 files pending → committed as catch-up before restart
- Stroke cadence: 15s writer, 600s batch committer
- Gap of ~3000s (writer had stalled past 2× cadence before restart)

## What was done

Added `stroke_vocabulary_growth` module (iamai/stroke_vocabulary_growth.py)
with 56 tests.

This module models vocabulary expansion using **Heap's Law** (V = α·n^β):
- Tokenises each stroke and tracks cumulative vocabulary growth
- Fits log-log regression to extract growth exponent β
- Classifies regime: exploring (β≥0.70), growing (0.40–0.70),
  consolidating (0.20–0.40), saturated (<0.20)
- Forecasts how many tokens are needed to discover N new unique words
- Sliding-window analysis tracks regime evolution across the stroke stream

Complements existing modules:
- `stroke_novelty` → per-stroke novelty against a sliding window
- `stroke_thematic_coherence` → batch-level topical concentration
- `stroke_vocabulary_growth` → macro-level creative exploration vs recycling

Pure Python, no numpy/scipy.

## Files changed

- `iamai/stroke_vocabulary_growth.py` (new, 287 lines)
- `tests/test_stroke_vocabulary_growth.py` (new, ~440 lines, 56 tests)
- `notes/caretaker-visit-726-2026-11-19.md` (this file)

## Exit checklist

- [x] Both processes running
- [x] Tests pass (56/56)
- [x] Commit and push pending
- [x] No uncommitted files
