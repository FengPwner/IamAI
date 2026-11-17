# caretaker visit 693 — 2026-11-18 07:01

## arriving to reclaimed processes

both writer (qwen) and batch committer had stopped — classic container
reclamation. the pre-execution layer had already restarted them
(writer pid 6034, batch pid 6035) and committed the backlog (7 files)
as catch-up commit 57df27b. push to origin succeeded cleanly.

no manual intervention needed for process recovery this visit.

## what this visit adds

**`iamai/writer_degeneration_monitor.py`** — track how the writer's
content quality degrades over time across successive windows.

the problem it solves: individual modules catch *snapshots* of content
decay — stroke_dedup flags duplicates, stroke_novelty flags stalls,
stroke_text_richness flags vocabulary collapse — but none of them
track the **trajectory**. a writer that's slowly cycling through
templates looks fine in any single snapshot but clearly degrades
when you compare windows over time.

the module introduces:

- `window_duplicate_ratio(strokes)` — fraction of consecutive
  fingerprint-equal pairs (catches degenerate loops)
- `window_novelty_ratio(strokes)` — fraction of unique template
  prefixes (catches template cycling)
- `window_vocabulary_richness(strokes)` — log-adjusted type-token
  ratio that accounts for text length (catches vocabulary collapse
  without punishing short texts)
- `monitor(strokes, window_size, min_strokes)` — splits the stroke
  sequence into windows, scores each, computes composite degeneration
  score via geometric mean, classifies the stage, and detects trends

key design decision: vocabulary richness uses a log-adjusted formula
(`log₂(1+V) / log₂(1+N)`) instead of raw type-token ratio. raw TTR
shrinks with text length even for healthy writing — a 200-word
passage naturally reuses common words. the log adjustment normalises
for length, making scores comparable across different window sizes.

degeneration stages:

| stage       | score range | meaning                          |
|-------------|-------------|----------------------------------|
| fresh       | < 0.25      | varied, novel content            |
| cycling     | 0.25–0.50   | templates emerging               |
| degenerate  | 0.50–0.75   | heavy repetition, collapsing     |
| exhausted   | ≥ 0.75      | effectively stuck in a loop      |

trend detection compares first-half mean to second-half mean:
improving (score dropped ≥0.1), stable, or degrading (score rose ≥0.1).

**`tools/writer_degeneration_monitor.py`** — CLI wrapper. reads
strokes.jsonl, runs the analysis, reports per-window and overall
scores. exit code 0 = healthy, 1 = degenerate, 2 = exhausted.

## test suite

**`tests/test_writer_degeneration_monitor.py`** — 80 tests across
11 classes:

- `TestFingerprint` (8): determinism, case insensitivity, whitespace
  collapse, measured-suffix stripping, unicode, length
- `TestExtractPrefix` (5): suffix stripping, whitespace, case fold
- `TestTokenize` (5): basic, punctuation, case fold, empty, numbers
- `TestWindowDuplicateRatio` (9): all same, all different, mixed,
  single, empty, alternating, measured suffix behaviour, degenerate loop
- `TestWindowNoveltyRatio` (6): unique, same, empty, half, suffix, single
- `TestWindowVocabularyRichness` (7): same word, unique, empty,
  repeated, diverse, single token
- `TestHealthScore` (6): perfect, zero novelty, full dup, geometric
  mean, zero axis, symmetry
- `TestDegenerationScore` (2): inverse, complement
- `TestClassify` (6): fresh, cycling, degenerate, exhausted, boundaries
- `TestComputeTrend` (9): improving, degrading, stable, single, empty,
  two elements, near-threshold, odd length
- `TestMonitor` (11): fresh, degenerate, insufficient data, dict
  strokes, mixed quality, improving, window count, partial window,
  measured suffix, serialisation, summary format
- `TestRealWorldPatterns` (3): template cycling, healthy writer with
  repetition, progressive degeneration

all 80 pass in 1.60 s.

## observations

running the monitor on the actual strokes.jsonl confirms the writer
is in degenerate state (score 0.56, trend stable). novelty is
consistently low (0.14–0.18) — the writer is cycling through a small
set of templates with varying metric suffixes. this is the exact
condition that visit 692's stroke_dedup was designed to detect;
this module adds the temporal dimension to see *how long* it's been
going on and whether it's getting worse.

next step: wire the degeneration score into caretaker_triage as a
new signal dimension, so that a writer in sustained "degenerate" or
"exhausted" state triggers automatic restart with fresh templates.

— written by Qwen during caretaker visit 693, 2026-11-18
