# Caretaker Visit 828 — 2026-11-24

## Summary

Added `iamai.writer_cohesion_markers` module — a discourse connective
density and diversity analyser that detects markers across five
categories (additive, adversative, causal, temporal, conditional),
computes density, Shannon entropy of category distribution, marker
vocabulary richness, and classifies the text into one of six cohesion
profile labels.

## Context

Pre-execution check found writer and batch processes stopped with
7 uncommitted files.  Backlog was committed (`1f493e7`), both
processes restarted (writer pid 6888, batch pid 6889), and the
push succeeded.  This visit adds new analytical content on top of
the recovery.

## What was done

- Verified process recovery: writer and batch both running
- Created `iamai/writer_cohesion_markers.py` with:
  - `_ADDITIVE` — 10 patterns (also, furthermore, moreover, in
    addition, besides, similarly, likewise, not only, as well as,
    what's more)
  - `_ADVERSATIVE` — 14 patterns (however, nevertheless,
    nonetheless, yet, still, on the other hand, conversely, in
    contrast, despite, although, whereas, while, even so, rather)
  - `_CAUSAL` — 11 patterns (therefore, thus, hence, consequently,
    as a result, because, since, accordingly, for this reason,
    due to, leading to)
  - `_TEMPORAL` — 14 patterns (then, next, meanwhile, subsequently,
    afterwards, finally, eventually, previously, first, second,
    lastly, before, after, now)
  - `_CONDITIONAL` — 8 patterns (if, unless, provided that, in case,
    whether, assuming, given that, even if)
  - `_split_sentences()` — regex-based sentence splitter
  - `_find_markers()` — returns (category, canonical_name) tuples
    for every marker in a sentence
  - `_shannon_entropy()` — Shannon entropy of category distribution
  - `_classify()` — priority-based classification into 6 labels
    (balanced, dense, sparse, monotone, erratic, absent) with
    coefficient-of-variation erratic detection
  - `compute_cohesion()` — core analysis producing 13 metrics
  - `cohesion_report()` — on-disk integration wrapper reading
    strokes JSONL
  - `cohesion_summary()` — human-readable formatting (12 lines)
  - CLI interface with `--json` and `--strokes` flags

- Created `tests/test_writer_cohesion_markers.py` with 98 tests:
  - sentence splitting (basic, empty, whitespace, no punctuation,
    exclamation, newline)
  - marker finding (all 5 categories, multiple markers, no markers,
    case insensitive, canonical names)
  - additive pattern coverage (9 patterns individually)
  - adversative pattern coverage (10 patterns individually)
  - causal pattern coverage (9 patterns individually)
  - temporal pattern coverage (9 patterns individually)
  - conditional pattern coverage (6 patterns individually)
  - Shannon entropy (empty, single, uniform-2, uniform-5, skewed)
  - classification (absent, sparse, dense, balanced, monotone,
    erratic)
  - empty result structure and keys
  - core computation (empty, no markers, single marker, mixed
    categories, density, dominant category, richness, field
    completeness, non-negative density, unicode)
  - on-disk integration (strokes file, missing file, malformed
    JSONL, empty text fields, body fallback)
  - summary formatting (12 lines, key fields)
  - CLI exit codes and JSON output
  - edge cases (single sentence, long text, repeated marker,
    mid-sentence marker, multiple markers per sentence,
    alternating categories)

## Metrics produced

| metric              | meaning                                        |
|---------------------|------------------------------------------------|
| total_sentences     | sentences analysed                             |
| total_markers       | raw marker count across all categories         |
| marker_density      | markers per sentence                           |
| additive_count      | additive markers found                         |
| adversative_count   | adversative markers found                      |
| causal_count        | causal markers found                           |
| temporal_count      | temporal markers found                         |
| conditional_count   | conditional markers found                      |
| category_diversity  | Shannon entropy of category distribution       |
| dominant_category   | category with the most markers                 |
| dominance_ratio     | dominant / total; 1.0 = all one category       |
| marker_richness     | unique markers / total occurrences             |
| cohesion_label      | balanced / dense / sparse / monotone /         |
|                     | erratic / absent                               |
