# Caretaker Visit 827 — 2026-11-24

## Summary

Added `iamai.writer_register_shift` module — a register/formality
shift detector that scores text segments for formality level, then
measures stability and detects significant register jumps across the
text, producing 9 metrics and 6 classification labels.

## Context

Processes were found stopped (writer pid gone, batch pid gone) with
7 uncommitted files.  Backlog was committed, both processes restarted
(writer pid 4258, batch pid 4259).  This visit adds new analytical
content on top of the recovery.

## What was done

- Recovered stalled processes and committed 7 pending files
- Created `iamai/writer_register_shift.py` with:
  - `_INFORMAL_PATTERNS` — 9 regex patterns for colloquial markers
    (slang, contractions, exclamations, trailing dots, casual words)
  - `_FORMAL_PATTERNS` — 6 regex patterns for formal markers
    (discourse connectives, legal/archaic terms, modals, Latinate
    verbs, formal phrases, impersonal nouns)
  - `_PASSIVE_RE` — passive voice detector (be-verb + past participle)
  - `_NOMINALISATION_RE` — nominalisation suffix detector
    (-tion, -sion, -ment, -ness, -ity, -ance, -ence, -ship, -hood, -ism)
  - `_split_segments()` — paragraph-aware text segmentation
  - `_score_segment()` — per-segment formality scoring in [0, 1]
  - `_classify()` — priority-based classification into 6 labels
    (consistent, mostly_stable, mixed, volatile, formalising,
    informalising)
  - `compute_register_shift()` — core analysis with configurable
    shift threshold
  - `_empty_result()` — zeroed-out fallback for empty input
  - `register_shift_report()` — on-disk integration wrapper
  - `register_shift_summary()` — human-readable formatting
  - CLI interface with `--json` flag

- Created `tests/test_writer_register_shift.py` with 69 tests covering:
  - segment splitting (paragraphs, newlines, empty, whitespace)
  - segment scoring (empty, short, neutral, informal, formal, mixed,
    bounded)
  - informal pattern matching (gonna, lol, contractions, exclamations,
    trailing dots, casual words)
  - formal pattern matching (furthermore, pursuant, shall, utilize,
    in accordance with, stakeholder)
  - passive voice detection (is written, was established, has been
    demonstrated, active voice rejection, be + -en)
  - nominalisation detection (-tion, -ment, -ness, -ity, no match)
  - classification across all 6 labels (consistent, mostly_stable,
    volatile, formalising, informalising, mixed)
  - empty result structure
  - core computation (empty input, single text, uniform formal/informal,
    mixed register, bounded rates, non-negative shifts, direction
    detection, custom thresholds, segment scores, all fields present)
  - on-disk integration (strokes file, missing file, malformed JSONL,
    empty text fields)
  - summary formatting (9 lines, key fields present)
  - CLI exit codes and JSON output
  - edge cases (unicode, long text, single-word paragraphs, repeated
    segments, alternating register)

## Metrics produced

| metric             | meaning                                          |
|--------------------|--------------------------------------------------|
| total_segments     | paragraphs analysed                              |
| mean_formality     | mean formality score in [0, 1]                   |
| formality_std      | standard deviation of segment scores             |
| formality_range    | max − min segment score                          |
| shift_count        | adjacent-segment jumps exceeding threshold       |
| shift_rate         | fraction of transitions that are shifts          |
| max_shift          | largest single adjacent-segment jump             |
| shift_direction    | formalising / informalising / stable             |
| register_label     | consistent / mostly_stable / mixed / volatile /  |
|                    | formalising / informalising                      |
