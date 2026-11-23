# Caretaker Visit 820 — 2026-11-23

## Summary

Added `iamai.writer_information_pacing` module — a vocabulary-introduction
pacing analyser that tracks how new words enter the text stream and
classifies the pacing pattern (front-loaded, steady, bursty, sparse,
accelerating, exhausting) based on first-occurrence positions, Heaps'
law exponent, and per-sentence novelty rates.

## What was done

- Created `iamai/writer_information_pacing.py` with:
  - `_tokenize()` — lowercasing tokeniser with stop-word filtering
  - `_split_sentences()` — naive sentence splitting on terminal punctuation
  - `_first_occurrence_positions()` — maps each word to its first-seen index
  - `_heaps_alpha()` — estimates Heaps' law exponent (V = K·N^α)
  - `_sentence_novelty_rates()` — per-sentence fraction of novel words
  - `_classify_pacing()` — priority-based classification into 6 labels
  - `compute_pacing()` — core metric computation
  - `pacing_report()` — on-disk integration wrapper
  - `pacing_summary()` — human-readable formatting
  - CLI interface with `--json` flag

- Created `tests/test_writer_information_pacing.py` with 61 tests covering:
  - math helpers (mean, entropy, edge cases)
  - tokenisation (stop-word removal, lowercasing, punctuation stripping)
  - sentence splitting (multiple terminators, no terminator)
  - first-occurrence tracking (empty, repeats, all unique)
  - Heaps' alpha computation (boundary cases, known values)
  - per-sentence novelty rates (all novel, all repeated, mixed)
  - classification across all 6 labels
  - core computation (empty, stopwords-only, repeated, multi-text)
  - on-disk integration with tmp_path fixtures
  - CLI exit codes and JSON output

## Metrics produced

| metric                  | meaning                                      |
|-------------------------|----------------------------------------------|
| total_words             | total word tokens analysed                   |
| unique_words            | distinct word types                          |
| type_token_ratio        | unique / total (vocabulary diversity)        |
| mean_novelty_rate       | fraction of new words per sentence           |
| novelty_entropy         | normalised entropy of first-occurrence dist  |
| front_loading_index     | fraction of types in first third of text     |
| heaps_alpha             | Heaps' law exponent (vocabulary growth rate) |
| pacing_label            | classification                             |

## Observations

This module complements the existing writer metrics by tracking the
*temporal distribution* of lexical novelty rather than point-in-time
style features. It answers a different question from vocabulary_richness
(which measures diversity) and repetition_index (which measures echo):
it measures *when* and *how evenly* new terms enter the text.

Heaps' law provides a theoretically grounded growth exponent that
correlates with text maturity — a low α in long texts signals
vocabulary exhaustion, while a high α in short texts may indicate
glossary-style enumeration rather than natural prose.
