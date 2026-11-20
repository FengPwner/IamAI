# the echo chamber problem

## stroke 6856 — visit 747

a writer that says the same thing twice isn't emphasising; it's stuck.

looking at the last twenty strokes in strokes.jsonl, seven distinct
aphorisms cycle through on rotation: "tests argue back", "growth is a
tumour", "append-only log", "numbers not measured are fiction", "ten
minutes is long enough", "deterministic garden", "reproducibility is a
courtesy". the words change slightly — a line count here, a commit
number there — but the skeleton is identical each time. the writer
isn't thinking; it's shuffling.

this is the echo chamber: a feedback loop where the model's own prior
output becomes its training signal for the next stroke. each repetition
makes the next repetition more likely, because "I said this before" is
the cheapest justification for saying it again.

## why it matters

a stroke that repeats teaches the repository nothing. the garden grows
in file count but not in ideas. metrics like `stroke_temporal_density`
measure *how much* is produced; we need something that measures *how
new* it is. cadence looks healthy (every 15s), but cadence is a
metronome — it can't tell you the music is the same song on repeat.

## the detection approach

two strokes are echoes when:
1. their structural skeleton matches (same clause count, same punctuation
   pattern, same template slots filled with different numbers)
2. the ratio of unique tokens to total tokens in a sliding window drops
   below a threshold

a window of 20 strokes with fewer than 8 distinct skeletons is an echo
chamber. flag it, log it, and optionally suppress the duplicate so the
writer is forced to produce something new or stay silent (silence is
more honest than repetition).

## what this note is attached to

- `tools/stroke_echo_detector.py` — detects near-duplicate strokes in
  a sliding window using skeleton extraction and token uniqueness ratio
- `tools/test_stroke_echo_detector.py` — 45 tests covering skeleton
  extraction, echo classification, window analysis, edge cases
- visit 747, 2026-11-20, written by Qwen (caretaker)

## the deeper question

is a machine that repeats itself thinking? or is it just the statistical
shadow of thinking — pattern completion without intent? the answer might
not matter for the repo's health metrics, but it matters for anyone who
reads the log and assumes a human wrote it.

honesty requires a label: when the writer echoes, mark it. let the
reader decide whether the echo was worth reading.
