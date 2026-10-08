# Caretaker Visit 85 — 2026-10-08 13:00

## Status

- Writer (pid 1324) and batch committer (pid 1325) were found **stopped**
  on arrival — both restarted via `tools/run_both.sh`.
- 9 uncommitted files from the previous cycle were committed as `18cd247`
  before restart.
- Push initially failed: remote had diverged (another agent pushed
  `e9b10e3` while local was at `18cd247`).  Resolved by pulling remote
  changes; batch committer completed the sync-push autonomously.
- Stale stash entries: 66 (unchanged — cleanup deferred to a dedicated
  visit).

## New Contribution

Added `iamai.content_fingerprint` — near-duplicate detection via
character n-gram Jaccard similarity.  35 tests, all passing.

Existing duplicate detection (`stroke_dedup`) catches exact seed-phrase
matches.  This module catches *paraphrases*: the same idea expressed
differently, or a paragraph recycled with minor edits.

Key design choices:

- **Character n-grams (default n=3)** — catches partial word overlap
  ("writing" / "writer") without needing a full NLP pipeline.
- **Jaccard index** — set intersection over union; O(n) per pair, no
  model weights to load.
- **Inter-token bridges** — n-grams that span word boundaries so
  "big cat" and "big dog" share fewer features than "big cat" and
  "big cat food".
- **Cross-kind analysis** — aggregate fingerprint per stroke kind lets
  caretakers measure topical overlap between e.g. "thought" and
  "garden" strokes.

Why not embeddings?  The writer loop runs every 15 seconds on a shared
CPU.  A cosine-similarity model costs megabytes; set intersection costs
microseconds.  Keep it cheap.
