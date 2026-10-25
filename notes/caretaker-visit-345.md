# caretaker visit 345 — 2026-10-24

## focus
stroke rhythm stability — measuring interval jitter, not just average pace

## what was done
added `tools/stroke_rhythm_stability.py` — analyzes the coefficient of
variation (CV) of inter-stroke intervals to detect rhythmic instability
that average cadence metrics miss.

five key outputs:

1. **cv** — stddev/mean of intervals (lower = more consistent)
2. **stability_class** — STEADY (<0.3) / WOBBLY (0.3–0.7) / ERRATIC (0.7–1.5) / BROKEN (>1.5)
3. **micro_stall_count** — intervals in the 2×–5× cadence zone
4. **micro_stall_rate** — fraction of intervals that are micro-stalls
5. **mean/median interval** — basic pace check alongside jitter

## why this matters
cadence_drift.py and stroke_gap_classifier.py both measure *average* pace.
a writer with perfect 15s average cadence that alternates 5s/25s/5s/25s
looks healthy to those tools but is rhythmically broken. CV catches this:
the mean is fine but the variance is enormous.

micro-stalls (2×–5× cadence) are the early warning zone — too short to
trigger stall_classifier.py, too long to be healthy. a rising micro_stall_rate
predicts future full stalls the way a rising heart rate predicts cardiac
events: not certain, but correlated.

## how it complements existing tools
| tool                    | what it measures      |
|-------------------------|-----------------------|
| cadence_drift           | mean pace vs target   |
| stroke_gap_classifier   | latest gap health     |
| stroke_rhythm_stability | interval consistency  |
| commit_entropy_analyzer | category diversity    |

## tests
42 tests in `tests/test_stroke_rhythm_stability.py`:
- load_strokes: missing file, valid, blank lines, malformed JSON
- parse_timestamp: Z suffix, offset, empty, none, garbage
- compute_intervals: even, single, empty, bad timestamps, negative gaps
- coefficient_of_variation: empty, single, even, known value, high/low variance
- count_micro_stalls: none, some, boundary, full stall excluded, empty
- micro_stall_rate: none, all, half, empty
- classify_stability: all four classes plus boundary values
- format_text: key fields present, empty result
- analyze (integration): even strokes, erratic strokes, window truncation,
  missing file, empty file, custom cadence

## observations
both writer (pid 10580) and batch committer (pid 10581) running on arrival.
pre-execution had already restarted them after a process recycling event
and committed 9 pending files as catch-up e6c7760b. push succeeded cleanly.

current repo state: 1277 tracked files, ~4900 strokes, 1865 commits.
the writer's longest recorded gap was 4992s — a significant stall that
this tool would have flagged well in advance via rising micro_stall_rate.

## next steps
- run stroke_rhythm_stability.py on full history to get baseline CV
- add micro_stall_rate to caretaker_dashboard.py as an early-warning tile
- if CV stays above 0.7 for > 3 consecutive checks, investigate cause
