# Caretaker Visit 817 — 2026-11-23

## Summary

Added `iamai.writer_punctuation_profile` module — a punctuation-based writing
style analyser that classifies recent output into style categories (formal,
conversational, telegraphic, structured, fragmented, balanced) based on
comma, semicolon, colon, dash, question mark, exclamation, parenthetical,
and ellipsis usage patterns.

## What was done

- Created `iamai/writer_punctuation_profile.py` with:
  - `analyse_text()` — core computation over a list of text strings
  - `profile_report()` — on-disk integration reading strokes.jsonl
  - `profile_summary()` — one-paragraph human-readable output
  - `_classify_style()` — priority-based style classification
  - `formality_index` — composite metric from semicolons/colons vs exclamations
  - `fragmentation_index` — composite metric from dashes and ellipses
  - CLI interface with `--json` flag

- Created `tests/test_writer_punctuation_profile.py` with 56 tests covering:
  - sentence counting, word counting, safe division
  - empty/degenerate inputs
  - basic metric computation for all punctuation categories
  - formality and fragmentation index scoring
  - style classification across all 6 labels
  - on-disk integration with tmp_path fixtures
  - CLI exit codes and JSON output
  - edge cases (unicode ellipsis, em-dashes, punctuation-only text)

- Fixed classification boundary issues:
  - Tightened formal threshold: question_ratio < 0.08 (was 0.1)
  - Narrowed conversational trigger: question_ratio > 0.12 OR formality < 0.35
  - Ensured "balanced" has a reachable parameter space

## Observations

Ran on the latest 200 strokes:
- Style: **structured** (heavy colon usage — the writer uses "measured now:" patterns)
- Punctuation density: 14.7 per 100 words (moderate)
- Formality index: 0.99 (extremely formal register — semicolons + colons dominate)
- Fragmentation index: 1.0 (dashes are pervasive in every stroke)
- Zero questions, zero exclamations in 200 strokes — purely declarative prose

The high colon ratio (1.33/sentence) is driven by the "measured now:" template
that appears in most strokes. This is a structural signature of the automated
writer, not an organic writing choice.

## Process health

- Writer process: running (pid 4036, restarted during this visit)
- Batch committer: running (pid 4037, restarted during this visit)
- 9 pending files committed as catch-up before restart
- Push successful to origin/main

## Files changed

| File | Action |
|------|--------|
| `iamai/writer_punctuation_profile.py` | created |
| `tests/test_writer_punctuation_profile.py` | created |
| `notes/caretaker-visit-817.md` | created |
