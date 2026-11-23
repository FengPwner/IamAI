# Caretaker Visit 821 — 2026-11-23

## Summary

Added `iamai.writer_clause_connectivity` module — a clause-linkage
analyser that measures how text connects its propositions through
coordination, subordination, and parataxis, producing a connectivity
profile with 6 classification labels and 8 metrics.

## What was done

- Created `iamai/writer_clause_connectivity.py` with:
  - `_tokenize()` — lowercase tokeniser stripping punctuation
  - `_split_sentences()` — naive sentence splitter on terminal punctuation
  - `_clause_segments()` — heuristic clause splitter detecting coordinating
    and subordinating conjunction boundaries
  - `_sentence_nesting_depth()` — subordinator count as embedding proxy
  - `_classify()` — priority-based classification into 6 labels
  - `compute_connectivity()` — core metric computation
  - `connectivity_report()` — on-disk integration wrapper
  - `connectivity_summary()` — human-readable formatting
  - CLI interface with `--json` flag

- Created `tests/test_writer_clause_connectivity.py` with 73 tests covering:
  - tokenisation (punctuation, contractions, mixed case)
  - sentence splitting (multiple terminators, edge cases)
  - clause segmentation (coordination, subordination, mixed, empty)
  - nesting depth computation (coordinators excluded, deep nesting)
  - classification across all 6 labels
  - core computation (empty, simple, coordinated, subordinated, paratactic)
  - metric rounding and range validation
  - on-disk integration with tmp_path fixtures
  - CLI exit codes and JSON output
  - edge cases (single word, very long, all-subordinator, malformed JSONL)
  - constants validation (frozenset types, no overlap)

## Metrics produced

| metric                  | meaning                                      |
|-------------------------|----------------------------------------------|
| total_clauses           | total clause segments detected               |
| coordination_ratio      | fraction introduced by coordinating conj.    |
| subordination_ratio     | fraction introduced by subordinating conj.   |
| parataxis_ratio         | fraction with no explicit connector          |
| mean_nesting_depth      | avg subordinators per sentence               |
| connectivity_index      | normalised Shannon entropy of 3-way split    |
| avg_clauses_per_sentence| mean clauses per sentence                    |
| connectivity_label      | classification                             |

## Observations

This module fills a gap in the writer analysis suite: it captures
*syntactic linkage* — how clauses relate to each other structurally.
Existing modules cover sentence rhythm (length variation), paragraph
structure (organisation), and punctuation style, but none address
how propositions are *connected*.

The three-way split (coordination / subordination / parataxis) maps
onto classical rhetoric categories and gives a theoretically grounded
view of prose complexity. The connectivity index (normalised entropy)
provides a single number for "how varied is the linkage strategy" —
useful for tracking whether the writer is settling into a monotone
syntactic pattern or maintaining structural diversity.

- both processes running: writer pid 4013, batch pid 4014
- processes were recovered by pre-exec: backlog committed (4e7fea8), both restarted
- writer stall noted in pre-exec diagnosis (gap 1720s > 2x cadence) —
  restart resolved it
