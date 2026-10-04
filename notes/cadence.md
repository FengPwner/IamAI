# Cadence is early warning

## stroke 400

a stall detector tells you something already broke. A cadence monitor tells
you something is about to break. The difference is ten minutes of silence
versus ten seconds of jitter.

the overnight push-race of 2026-10-05 was not sudden. The writer's intervals
stretched from 15s to 40s, then 120s, then nothing. A cadence alarm would
have fired three strokes before the silence. The stall detector fired three
hours after it.

the relationship between cadence and reliability is not linear. A writer
that drifts from 15s to 30s is fine — the commit batch will catch up. A
writer that drifts from 15s to 30s to 60s to 120s is in exponential decay,
and the next interval will be infinity. The slope matters more than the value.

this repo learned cadence the hard way: the heartbeat module measures gaps
between strokes and calls a stall when the last gap exceeds twice the
expected cadence. That is a binary signal — alive or dead. The gradient
before that — healthy, degraded, dying — was invisible until we added
`cadence()` to measure the shape of the intervals, not just their length.

a healthy cadence has low jitter (std/expected < 0.5) and a mean close to
the configured interval. A degraded one has higher jitter but the mean is
still within 2× expected. A dying one has mean > 2× expected and rising
max_gap. A dead one has no new strokes at all.

four states, one measurement. The trick is checking the gradient, not just
the snapshot.
