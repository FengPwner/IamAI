# Caretaker Visit 822 — 2026-11-23

## Summary

Added `iamai.writer_rhythm_signature` module — a rhythmic-fingerprint
analyser that quantifies the cadence of text through sentence-length
variation, syllable density, function-word ratio, paragraph pacing,
and rhythmic entropy, producing 10 metrics and 6 classification labels.

## What was done

- Created `iamai/writer_rhythm_signature.py` with:
  - `FUNCTION_WORDS` — closed-class word set (articles, prepositions,
    conjunctions, pronouns, auxiliaries, determiners, particles)
  - `_tokenize()` — lowercase tokeniser stripping punctuation
  - `_count_punctuation()` — punctuation character counter
  - `_split_sentences()` — naive sentence splitter on terminal punctuation
  - `_split_paragraphs()` — blank-line paragraph splitter
  - `_estimate_syllables()` — vowel-group syllable heuristic with
    silent-e handling
  - `compute_rhythm_signature()` — core metric computation
  - `_classify()` — priority-based classification into 6 labels
    (strong, moderate, steady, erratic, accelerating, decelerating)
  - `_empty_result()` — zeroed-out fallback for empty input
  - `rhythm_signature_report()` — on-disk integration wrapper
  - `rhythm_signature_summary()` — human-readable formatting
  - CLI interface with `--json` flag

- Created `tests/test_writer_rhythm_signature.py` with 86 tests covering:
  - tokenisation (punctuation, contractions, mixed case, unicode)
  - punctuation counting (em-dash, ellipsis, quotes, all types)
  - sentence splitting (multiple terminators, edge cases)
  - paragraph splitting (blank lines, extra whitespace)
  - syllable estimation (mono/di/tri-syllable, silent-e, -le ending)
  - edge cases (empty list, single sentence, no punctuation, all
    function words, very long sentence, many short sentences)
  - metric range validation (all metrics bounded correctly)
  - classification across all 6 labels
  - text pattern analysis (uniform, mixed, multiple texts)
  - empty result structure
  - on-disk integration (strokes file, missing file, malformed JSONL, n limit)
  - summary formatting
  - CLI exit codes and JSON output
  - constants validation (frozenset type, lowercase, threshold ordering)
  - composite rhythm index behaviour (variation → higher index, bounds)

## Metrics produced

| metric                | meaning                                      |
|-----------------------|----------------------------------------------|
| total_sentences       | sentences analysed                           |
| total_paragraphs      | paragraphs analysed                          |
| mean_sentence_length  | mean words per sentence                      |
| sentence_length_cv    | coefficient of variation of sentence lengths |
| syllable_density      | mean syllables per word                      |
| function_word_ratio   | fraction of tokens that are function words   |
| rhythmic_entropy      | normalised entropy of sentence-length bins   |
| paragraph_pace_cv     | CV of paragraph lengths (sentences/para)     |
| punctuation_density   | punctuation marks per word                   |
| rhythm_index          | composite score [0, 1]                       |
| rhythm_label          | classification (6 labels)                    |

## Observations

This module captures a dimension of style that existing modules don't:
the *temporal pattern* of reading. Sentence-length CV and rhythmic
entropy together describe how predictable the text's cadence is.
Syllable density and function-word ratio add texture — dense syllables
with many function words produces a different feel than short words
with few.

The 6-label classification covers the main patterns a caretaker might
want to track: strong (dynamic, varied cadence), moderate (some
variation), steady (even pace), erratic (unpredictable swings),
accelerating (building momentum), and decelerating (slowing down).
Tracking label transitions across visits could reveal whether the
writer's rhythm is stabilising or fragmenting.

- both processes running: writer pid 6538, batch pid 6539
- pre-exec restarted both and cleared 7-file backlog (cd1995e)
- writer stall from pre-exec diagnosis (gap 3024s) appears resolved
  after restart; monitoring continues
