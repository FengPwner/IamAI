# Caretaker Visit 829 — 2026-11-24

## Summary

Added `iamai.writer_lexical_density` module — a lexical density and
word-class balance analyser that classifies tokens as content words
(nouns, verbs, adjectives, adverbs) or function words using a closed-class
stop-list plus suffix heuristics, and computes density, sub-class ratios,
Shannon entropy of content distribution, and a human-readable density
label.

## Context

Pre-execution check found writer and batch processes stopped with
7 uncommitted files.  Backlog was committed (`0f1d778`), both
processes restarted (writer pid 4469, batch pid 4470), and the
push succeeded.  This visit adds new analytical content on top of
the recovery.

## What was done

- Verified process recovery: writer and batch both running
- Created `iamai/writer_lexical_density.py` with:
  - `_FUNCTION_WORDS` — closed-class stop-list (articles, pronouns,
    prepositions, conjunctions, auxiliaries, particles; ~100 entries)
  - Suffix heuristic tables for nouns (-tion, -sion, -ment, -ness,
    -ity, -ence, -ance, -ship, -dom, -ism, -ist, -er, -or, -ure,
    -age, -hood, -ling), verbs (-ise, -ize, -ify, -ate, -ing, -ed),
    adjectives (-ous, -ive, -able, -ible, -ful, -less, -al, -ial,
    -ical, -ish, -ary, -ory), adverbs (-ly, -ward, -wards, -wise)
  - `_FORCE_CONTENT` — common irregular verbs that suffix heuristics
    would miss (run, think, build, know, see, …; ~60 entries)
  - `_tokenize()` — regex-based alphabetic tokeniser handling
    contractions
  - `_guess_class()` — priority classification: function list →
    force-content list → suffix heuristics (adverb > verb > adj >
    noun) → default noun
  - `_shannon_entropy()` — entropy of content sub-class distribution
  - `_classify_density()` — five labels (very_dense, dense, moderate,
    light, very_light) at thresholds 0.65, 0.50, 0.40, 0.30
  - `compute_lexical_density()` — core analysis producing 10 metrics
  - `lexical_density_report()` — on-disk integration reading strokes
    JSONL
  - `lexical_density_summary()` — human-readable formatting (10 lines)
  - CLI interface with `--json` and `--strokes` flags

- Created `tests/test_writer_lexical_density.py` with 64 tests:
  - tokeniser (basic, empty, whitespace, punctuation, numbers,
    contractions, unicode)
  - word classification (function articles, pronouns, prepositions,
    auxiliaries, conjunctions; content noun/verb/adj/adv suffixes;
    force-content; unknown default)
  - Shannon entropy (empty, single, uniform-2, uniform-4, skewed)
  - density classification (all 5 labels at boundary values)
  - empty result structure and keys
  - core computation (empty, all-function, all-content, mixed,
    density calculation, ratio sum-to-one, diversity, field
    completeness, non-negative values, unicode, single content
    word, single function word, repeated content, long text,
    telegraphic style, conversational style)
  - on-disk integration (strokes file, missing file, malformed
    JSONL, empty text fields, body fallback)
  - summary formatting (10 lines, key fields, empty)
  - CLI exit codes, JSON output, text output
  - edge cases (single sentence, numbers only, mixed scripts,
    very long text, all-adverbs, all-adjectives, half-half ratio)

## Metrics produced

| metric              | meaning                                        |
|---------------------|------------------------------------------------|
| total_words         | tokens counted (alphabetic only)               |
| content_words       | tokens classified as content                   |
| function_words      | tokens classified as function                  |
| lexical_density     | content / total  [0.0–1.0]                    |
| noun_ratio          | nouns / content_words                          |
| verb_ratio          | verbs / content_words                          |
| adjective_ratio     | adjectives / content_words                     |
| adverb_ratio        | adverbs / content_words                        |
| content_diversity   | Shannon entropy of 4 content sub-classes        |
| density_label       | very_dense / dense / moderate / light /         |
|                     | very_light                                     |
