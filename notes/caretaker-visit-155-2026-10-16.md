# Caretaker Visit 155 — 2026-10-16 02:00 UTC

## Status

Writer and batch processes had stopped (recovered by pre-flight).
12 uncommitted files were committed and pushed as catch-up (ac90df6).
Both processes restarted: writer pid 1194, batch pid 1195.

## New Feature: stroke_novelty

Added `iamai/stroke_novelty.py` — detects when the writer produces
individually coherent but collectively repetitive strokes.

- Character-shingle Jaccard similarity against a recent window
- Three verdicts: FRESH / REPETITIVE / DUPLICATE
- Configurable thresholds per kind
- 38 tests, all passing

This fills the gap between `stroke_coherence` (single-stroke quality)
and `content_diversity` (kind distribution): the "polite zombie"
failure mode where the writer says the same thing over and over.

## Push

Catch-up + new feature pushed to main in one batch.
