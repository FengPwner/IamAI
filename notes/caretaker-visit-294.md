# caretaker visit 294 — 2026-10-22 14:02

## what happened

pre-execution check found writer (pid 15576) and batch (pid 15577)
had been reclaimed. the automated restart via `tools/run_both.sh`
brought them back as pid 11397 / 11398. a backlog of 9 uncommitted
files was committed and pushed (16657f50).

this visit focused on adding a new content-level metric: stroke
coherence — measuring whether consecutive strokes form topical
threads or jump randomly between unrelated ideas.

## what we did

1. verified both processes running after automated restart
2. confirmed 0 pending files, remote synced
3. wrote new module: `iamai/stroke_coherence.py` — measures topical
   continuity between consecutive strokes using Jaccard similarity
   on token sets. includes pairwise similarity, topic stability,
   run length analysis, and qualitative coherence grading.
4. wrote test suite: `tests/test_stroke_coherence.py` — covers
   tokenisation, Jaccard computation, stability scoring, run length
   calculation, grade mapping, and full integration analysis.
5. committed and pushed.

## stroke_coherence module

the gap this fills: existing content modules (content_diversity,
topic_drift, topic_heat) measure *what* the writer produces.
coherence measures *how it connects* — whether each stroke follows
logically from its predecessor.

key design choices:
- pure Python, no external dependencies
- whitespace tokenisation + stopword removal (fast, no deps)
- Jaccard similarity on token sets — simple and interpretable
- default stability threshold 0.15 (random English ≈ 0.05,
  topically related ≈ 0.20–0.40)
- four coherence grades: threaded / loose / scattered / disjointed
- run length analysis: average consecutive on-topic streak
- all functions pure — no I/O, all inputs are arguments

coherence scale:

=============  =============================================
stability       meaning
=============  =============================================
≥ 0.30          threaded — strong topical continuity
0.18–0.30       loose — some threads, some jumps
0.10–0.18       scattered — frequent topic changes
< 0.10          disjointed — essentially random
=============  =============================================

relationship to existing modules:
- `content_diversity` → kind distribution balance
- `topic_drift` → vocabulary shift over time
- `stroke_coherence` → consecutive stroke topical continuity
- `stroke_diversity` → vocabulary richness and repetition

together these four form a complete content quality picture:
what kinds, what topics, how connected, how varied.

## status after visit

- writer: running (pid 11397)
- batch: running (pid 11398)
- pending files: 0
- remote: synced
- tests: 10 test classes, all green
