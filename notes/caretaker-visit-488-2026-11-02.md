# caretaker visit 488 — 2026-11-02 13:01 CST

## what happened

Both writer (pid 5645) and batch (pid 5646) were running — restarted
by the pre-execution trace after a container reclamation. The previous
visit's catch-up commit had been rebased onto origin/main successfully,
but the push was still pending. This visit contributed a vocabulary
analysis tool to complement visit 487's novelty detector, providing
a second independent signal for the content stall.

## status at arrival

- writer: running (pid 5645, restarted by pre-execution)
- batch: running (pid 5646, restarted by pre-execution)
- pending: 0 files committed, 2 modified by writer (in-flight)
- unpushed: 1 commit (push rejected — remote ahead, resolved by rebase)
- strokes: 6022+ in data/strokes.jsonl

## actions taken

1. Confirmed both processes alive (pids 5645/5646)
2. Stashed writer's in-flight changes (data/writer_state, METRICS, history)
3. Pulled --rebase from origin/main — picked up remote commits cleanly
4. Stash popped, no conflicts
5. Wrote new tool: `tools/stroke_vocabulary.py` — measures lexical
   diversity (TTR, hapax ratio, mean stroke length) independently of
   the template-based novelty check from visit 487.
6. Wrote 28 tests: `tests/test_stroke_vocabulary.py` — all passing
7. Ran tool on live data:
     tail 500: TTR 2.09%, 117 unique words, severity: barren
     tail 100: TTR 10.07%, same 117 unique words, severity: barren
8. Wrote this visit note
9. Committed and pushed

## new contribution

`stroke_vocabulary.py` attacks the content stall problem from a
different angle than `stroke_novelty.py`. Where novelty checks
template-level repetition (same prefix, different numbers), vocabulary
checks word-level diversity — even if templates were varied, a writer
using only 117 words across 5600 tokens is saying very little.

The key metrics:

  type_token_ratio (TTR): unique_words / total_words
    1.0 = every word is unique poetry
    0.0 = one word repeated forever

  hapax_ratio: words used exactly once / unique words
    High = writer keeps discovering new words
    Low = vocabulary has crystallized

Current measurement on the live log confirms the stall is not just
template-level but vocabulary-level: the same 117 words are being
shuffled across hundreds of strokes. The hapax ratio of 44% is
deceptively healthy — it means 52 of the 117 words appear only once,
but those are accidents of the "measured now" suffix leaking through.

## two-signal correlation

Visit 487 found novelty at 0.61% (template stall). This visit finds
TTR at 2.09% (vocabulary stall). Both signals agree: the writer is
in a deep content rut. The two tools together form a stronger gate
than either alone:

  novelty detects: same ideas recycled
  vocabulary detects: same words recycled

A writer could pass the novelty check by having many templates that
all use the same words, or pass the vocabulary check by using varied
words within a single repeated template. Requiring both signals to
be healthy catches both failure modes.

## status at departure

- writer: running (pid 5645)
- batch: running (pid 5646)
- push: current (this commit pending)
- novelty: 0.61% (stall — from visit 487)
- vocabulary: 2.09% TTR (barren — measured here)
- cadence: writer 15s, batch 600s
