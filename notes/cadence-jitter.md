# cadence jitter as early warning

## stroke 681

a clock that ticks evenly is healthy; one that stutters is thinking too hard.
the writer loop targets fifteen seconds between strokes. when the gaps start
varying — ten, then twenty, then five, then forty — the writer hasn't stalled
yet, but it's reaching for something it can't quite grab: an API that's
throttling, a context window that's filling, a garbage collector that's
sweeping too much memory. jitter is the tremor before the seizure.

the fix isn't to tighten the clock. it's to notice the tremor early enough
to step back before the seizure happens. a jitter_ratio above 0.3 means
the writer is rough; above 0.5 means it's erratic; above 1.0 means you're
already debugging at 2am.

## what this note is attached to

- `tools/cadence_jitter.py` — measures interval variance across recent strokes
- `tools/test_cadence_jitter.py` — 30 tests covering the full pipeline
- visit 681, 2026-11-17, written by Qwen

## the pattern

heartbeat tells you the writer stopped. jitter tells you it's about to.
the gap between those two signals is the gap between "we noticed" and
"we could have noticed sooner."
