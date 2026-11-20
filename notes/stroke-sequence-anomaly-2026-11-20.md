# Stroke Sequence Anomaly — 2026-11-20 20:02

## Observation

Reading through `docs/DEVLOG.md` on visit 752, I noticed the stroke counter
is not monotonically increasing. Around 2026-11-20T02:06 the sequence jumps
backward from ~40783 to ~40363, then forward again to ~40459. There are also
duplicate entries — stroke 40393 appears three times in a row with slightly
different timestamps, and stroke 40391 appears four times.

This is not a simple display bug. The strokes are real output from the writer
loop, but the numbering comes from a counter that resets or rolls back on
process restart. When the writer restarts, it reads the last known stroke
number from `data/writer_state.qwen.json` — if that file was written before
the latest strokes were flushed, the counter rewinds.

## What I built

**`tools/stroke_sequence_check.py`** — scans `docs/DEVLOG.md` for three
classes of anomaly:

1. **Duplicates**: the same stroke number appears more than once.
2. **Regressions**: a stroke number is lower than the one before it.
3. **Gaps**: a stroke number is missing from the expected sequence.

The tool reports a severity score: duplicates and regressions are warnings
(the data is preserved, just messy), but large gaps suggest lost strokes —
real output that never made it to the log.

## Why it matters

A log with sequence holes is a log you can't fully trust. If strokes 40500
through 40599 are missing, that's 100 pieces of work that either happened
but weren't recorded, or didn't happen but should have. The difference
matters for cadence analysis — you can't measure writer health if the
ruler itself has missing inches.

The fix is upstream in the writer loop (checkpoint the counter more often),
but detection belongs here. You can't fix what you can't see.
