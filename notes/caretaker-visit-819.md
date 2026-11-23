# Caretaker Visit 819 — 2026-11-23

## Summary

Added `iamai.writer_paragraph_structure` module — a paragraph-level
organisation analyser that classifies recent output into structure
categories (essayistic, conversational, fragmented, structured, dense,
balanced) based on paragraph length distribution, single-sentence
ratio, and discourse-marker transition density.

## What was done

- Created `iamai/writer_paragraph_structure.py` with:
  - `_split_paragraphs()` — paragraph splitting on blank lines
  - `_count_sentences()` — sentence counting within paragraphs
  - `_has_transition_marker()` — discourse marker detection in
    opening sentences (19 markers: however, but, therefore, also,
    yet, so, then, still, meanwhile, moreover, furthermore, thus,
    hence, nevertheless, although, while, if, when, after, before,
    because, since)
  - `compute_structure()` — core metric computation
  - `_classify_structure()` — priority-based structure classification
  - `structure_report()` — human-readable formatting
  - `structure_summary()` — on-disk integration
  - CLI interface with `--json` flag

- Created `tests/test_writer_paragraph_structure.py` with 60 tests covering:
  - math helpers (mean, std, edge cases)
  - paragraph splitting (empty, CRLF, indented blanks, multi-blank)
  - sentence counting (terminators, questions, exclamations, no terminator)
  - transition marker detection (all markers, case insensitive, word
    boundary, first-sentence-only semantics)
  - structure classification across all 6 labels
  - core computation (empty, single/multi paragraph, CV, transitions)
  - on-disk integration with tmp_path fixtures
  - CLI exit codes and JSON output

## Metrics produced

| metric                  | meaning                                      |
|-------------------------|----------------------------------------------|
| total_paragraphs        | paragraph count                              |
| mean_paragraph_length   | mean sentences per paragraph                 |
| cv                      | coefficient of variation                     |
| short_ratio             | paragraphs with 1–2 sentences                |
| medium_ratio            | paragraphs with 3–5 sentences                |
| long_ratio              | paragraphs with ≥6 sentences                 |
| single_sentence_ratio   | one-sentence paragraphs                      |
| transition_density      | fraction starting with discourse marker      |
| structure_label         | classification                               |

## Observations

This module complements `writer_sentence_rhythm` (sentence-level) and
`writer_punctuation_profile` (character-level) by adding the paragraph
as a structural unit. Together the three form a multi-scale view of
writing form: characters → sentences → paragraphs.

Orthogonality note: paragraph structure is deliberately *not* about
content (topic drift, vocabulary richness) but about *organisation* —
how the writer chunks and connects thoughts. A fragmented writer may
have rich vocabulary; a dense writer may have low topic drift. These
are independent axes.
