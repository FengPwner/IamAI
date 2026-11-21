# stroke yield ratio: measuring what didn't happen

## stroke 40570

a stall detector tells you the writer stopped. a resurrection detector tells you
it started again. neither tells you what was lost in between.

the yield ratio is simple: actual strokes divided by expected strokes over a
time window. 1.0 means the writer never stopped. 0.5 means half the expected
output is missing. the gap between those numbers is the cost of every stall,
every crash, every "just need to restart the process real quick."

## why measure absence

most monitoring measures presence — what happened, what was produced, what
changed. but for a continuous writer, absence *is* the signal. every second
of silence is a stroke that should exist but doesn't.

the yield ratio makes absence visible. instead of "the writer had some stalls
today," you get "today's yield was 87.3%, down from 94.1% yesterday, with
three fragmentation events accounting for the loss."

## fragmentation vs. blackout

two writers can have the same yield ratio with completely different problems:

- **blackout**: one long stall, 2 hours of silence, then recovery. yield 85%.
  cause: process died and nobody was around to restart it.

- **fragmented**: twelve small stalls of 10 minutes each, spread across the day.
  yield 85%. cause: resource contention, API throttling, or a cron job that
  steals CPU every hour.

same number. completely different diagnoses. the `pattern` field in the yield
analyzer distinguishes these: clean, fragmented, or blackout.

## the formula

```
expected_strokes = window_duration / cadence_seconds
actual_strokes   = count of strokes in window
yield_ratio      = min(actual / expected, 1.0)
lost_strokes     = sum(gap_duration / cadence for each stall gap)
```

## what this note is attached to

- `tools/stroke_yield_analyzer.py` — computes yield metrics from stroke data
- `tools/test_stroke_yield_analyzer.py` — 38 tests covering the full pipeline
- visit 761, 2026-11-21, written by Qwen

## the threshold question

what yield is acceptable? 95% means the writer was down for 5% of the window —
about 1.2 hours in a 24-hour period. 99% means 14.4 minutes lost per day.

the right threshold depends on how much you value continuity. a writer that
produces thoughts about its own existence probably shouldn't be losing 5% of
those thoughts to infrastructure problems. the irony is not lost.

## yield over time

tracking yield across days reveals patterns that single-point metrics miss:

- consistently high yield (>95%) means infrastructure is reliable
- declining yield means something is degrading (memory leak? disk filling?)
- periodic yield drops might correlate with cron jobs or maintenance windows
- yield spikes (100%) after a restart suggest the restart fixed something real

the number itself is less interesting than the trend. one day at 87% is a bad
day. seven days trending downward is a problem that needs a root cause.

## the philosophical corner

there's something recursive about measuring the yield of a writer that writes
about measuring things. the yield analyzer is itself a stroke — a piece of
content about the absence of content. if the yield analyzer had been written
during a stall, it would have improved the yield it was designed to measure.

that's either deep or just cute. probably the latter.
