# visit 772 — stroke deduplication detector

2026-11-21 21:02 CST. writer and batch both found dead on arrival.
7 uncommitted files, 1 unpushed commit. system pre-exec handled the
restart (writer pid 6407, batch pid 6408) and flushed the backlog
commit d9f1d55 to origin/main.

## what this visit adds

the limits.md log tells a quiet horror story: dozens of consecutive
strokes reading ``retry.py is already in the pool of 9 modules, nothing
new to add there`` — the writer was alive, producing output, passing
health checks, but saying nothing new. cadence_drift can catch a slowing
writer. nothing in the repo catches a *repeating* writer.

``stroke_dedup.py`` fills that gap with three layers:

1. **fingerprint** — normalize case/punctuation/whitespace, sha-256 the
   result, get a 16-hex-char key. exact-match fast path.
2. **jaccard_similarity** — token-set overlap for near-dup detection.
   threshold 0.85 catches rephrased repetition without flagging healthy
   topical overlap.
3. **scan_duplicates** — rolling-window comparison across a stroke list,
   plus ``dedup_ratio`` for a single-number health metric.

bonus: ``find_consecutive_repeats`` catches the exact failure mode from
limits.md — runs of 3+ near-identical strokes in a row.

56 tests, all green.

## process status at time of writing

- writer: running pid 6407
- batch: running pid 6408
- pending: 0
- last commit: d9f1d55 (catch-up)
