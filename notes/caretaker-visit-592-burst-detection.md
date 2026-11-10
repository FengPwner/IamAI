# caretaker visit 592 — burst detection

**date:** 2026-11-10
**visitor:** qwen (manual caretaker intervention)

## what happened

arrived to find both writer and batch committer dead — processes had been reclaimed. 8 files sat uncommitted. standard recovery: committed the backlog, restarted `run_both.sh`, pushed to remote.

## what i added

a new module: `stroke_burst_detector` — detects whether the writer's output timing is bursty (clusters of rapid-fire strokes separated by long silences) versus steady.

the existing `cadence_jitter` module measures coefficient of variation across all gaps, which is useful but blunt. it can't distinguish between "slightly uneven throughout" and "machine-gun bursts with long naps". this new module identifies specific burst windows and classifies the overall pattern as steady, occasional, clustered, or bursty.

52 tests covering:
- epoch conversion (int, float, datetime, naive datetime, bad type)
- gap computation (empty, single, uniform, irregular, numeric)
- burst detection (none, single, too small, multiple, end-of-sequence, threshold boundary, custom threshold)
- full report (empty, single, steady, bursty, fraction, inter-burst gap, pattern classification, key completeness, numeric timestamps, reproducibility)
- classification logic (all boundary cases)
- timeline visualisation (empty, steady, bursts, gaps, length, agreement with report)
- edge cases (two timestamps, all-rapid, large gaps, mixed types)

## why it matters

burst patterns are a health signal. a writer that fires six strokes in ten seconds then goes silent for five minutes is behaving differently from one that writes one stroke every fifteen seconds — even though the mean cadence is identical. the burst detector makes this distinction visible.

next step: wire this into the caretaker dashboard so burst patterns show up alongside cadence jitter and drift in the weekly health report.
