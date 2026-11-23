# Caretaker Visit 830 — 2026-11-24

## Summary

Added `iamai.writer_textual_entropy` module — an information-theoretic
lexical profiler that applies Shannon entropy concepts to vocabulary
analysis, measuring unpredictability, diversity, and how lexical
richness evolves through a text.

## Context

Pre-execution check found writer and batch processes stopped with
7 uncommitted files. Backlog was committed (`3bee748`), both
processes restarted (writer pid 6863, batch pid 6864), and the
push succeeded. This visit adds new analytical content on top of
the recovery.

## What was done

- Verified process recovery: writer and batch both running
- Created `iamai/writer_textual_entropy.py` with:
  - `_tokenize()` — regex-based alphabetic tokeniser with
    case-folding and unicode support (Latin, Cyrillic, CJK)
  - `_shannon_entropy()` — Shannon entropy in bits over a
    frequency distribution
  - `_mattr()` — moving-average type-token ratio using a
    sliding window (default 100 tokens, step 50) for more
    stable diversity measurement than global TTR
  - `_entropy_gradient()` — entropy difference between second
    half and first half; positive means vocabulary widens,
    negative means it narrows
  - `_classify_entropy()` — five labels mapping entropy_ratio
    [0–1] to human-readable categories
  - `_empty_result()` — zero-valued result dict with all keys
  - `compute_textual_entropy()` — core analysis producing
    13 metrics including type-token ratio, hapax ratio,
    Shannon entropy, entropy ratio, MATTR, gradient,
    predictability index, and composite richness score
  - `textual_entropy_report()` — on-disk integration reading
    strokes JSONL
  - `textual_entropy_summary()` — human-readable formatting
    (13 lines)
  - CLI interface with `--json` and `--strokes` flags

- Created `tests/test_writer_textual_entropy.py` with 74 tests:
  - tokeniser (basic, empty, whitespace, punctuation, case-fold,
    numbers, unicode, single letter, contractions, CJK)
  - Shannon entropy (empty, single type, uniform-2, uniform-4,
    skewed, monotonicity)
  - MATTR (empty, short text, all unique, all same, mixed,
    custom window)
  - entropy gradient (short text, widening, narrowing, stable)
  - entropy classification (all 5 labels at boundary values,
    zero)
  - empty result structure and keys
  - core computation (empty, whitespace, single word, repeated
    word, all unique, mixed, TTR calculation, hapax count,
    hapax ratio, entropy ratio bounds, predictability
    complement, richness bounds, gradient direction, unicode,
    long text, field completeness, non-negative values,
    telegraphic style, conversational style)
  - on-disk integration (strokes file, missing file, malformed
    JSONL, empty text fields, body/text/content fallback,
    empty file)
  - summary formatting (line count, key fields, empty,
    gradient direction)
  - CLI exit codes, JSON output, text output
  - edge cases (single sentence, numbers only, mixed scripts,
    very long text, all hapax, no hapax, richness
    monotonicity, entropy ratio monotonicity)

## Metrics produced

| metric                 | meaning                                          |
|------------------------|--------------------------------------------------|
| total_tokens           | alphabetic tokens counted                        |
| unique_types           | distinct token types (case-folded)               |
| type_token_ratio       | unique_types / total_tokens  [0–1]              |
| hapax_count            | types appearing exactly once                     |
| hapax_ratio            | hapax_count / unique_types  [0–1]               |
| shannon_entropy        | H = -Σ p(x) log₂ p(x) over types (bits)         |
| max_entropy            | log₂(unique_types); upper bound                  |
| entropy_ratio          | shannon_entropy / max_entropy  [0–1]            |
| mattr                  | moving-average type-token ratio (window=100)     |
| entropy_gradient       | entropy(second half) - entropy(first half)       |
| predictability_index   | 1 - entropy_ratio; higher = more predictable     |
| richness_score         | composite: 0.4×TTR + 0.3×hapax + 0.3×entropy  |
| entropy_label          | lexical_desert / narrow_band / balanced /         |
|                        | rich_lexicon / encyclopedic / absent             |

## Orthogonality

This module is orthogonal to existing metrics:

- **lexical_density** classifies tokens as content vs function;
  textual entropy cares about *distribution* regardless of class.

- **vocabulary_richness** tracks TTR and related ratios; textual
  entropy adds Shannon entropy, hapax analysis, sliding-window
  stability, and gradient evolution.

- **information_density** measures meaning payload per sentence;
  textual entropy measures *lexical unpredictability*.
