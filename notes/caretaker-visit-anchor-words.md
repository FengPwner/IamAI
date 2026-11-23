# Caretaker Visit — writer_anchor_words

**Date:** 2026-11-23  
**Visit:** manual caretaker contribution  

## What was added

- `iamai/writer_anchor_words.py` — a new module that detects and analyses
  *thematic anchor words* in text: high-frequency content words that act
  as gravitational centres holding a discourse together.

- `tests/test_writer_anchor_words.py` — 54 tests covering tokenisation,
  content-word filtering, paragraph splitting, anchor detection, core
  metrics, classification logic, edge cases, and CLI.

## Metrics computed

| Metric              | Description                                    |
|---------------------|------------------------------------------------|
| anchor_density      | anchor tokens as fraction of all words         |
| thematic_focus      | anchor tokens as fraction of content words     |
| anchor_persistence  | stability of anchor density across paragraphs  |
| anchor_dispersion   | fraction of paragraphs containing any anchor   |
| gravitational_index | composite score in [0, 1]                      |
| anchor_label        | anchored / multi-pole / drifting / mono-fixated / diffuse / stable |

## Why this matters

Anchor words are the invisible scaffolding of readable prose.  A text
without recurring anchor concepts feels scattered even when each sentence
is individually clear.  This module complements the existing vocabulary,
cohesion, and rhythm modules by measuring *thematic gravity* — a dimension
not captured by sentence-level or rhythm-level analysis.

## Design choices

- Uses a broad stop-word list (≈180 entries) to separate content from
  function words.
- Minimum word length of 3 characters to filter noise.
- Gravitational index is a weighted composite of four sub-metrics rather
  than a single ratio, to capture both strength and consistency of
  anchoring.
- Classification uses a decision tree with explicit thresholds, keeping
  the logic transparent and debuggable.

## Process note

Writer and batch committer were found stopped during this visit.  Both
were restarted via `tools/run_both.sh`.  This manual contribution keeps
the commit cadence alive while the automated processes resume.
