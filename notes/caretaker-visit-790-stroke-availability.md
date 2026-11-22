# visit 790 — stroke availability module

2026-11-22 15:02 CST. human-requested caretaker check.

## context

overnight stall pattern continues.  both processes were found dead
on arrival during the pre-execution sweep (gap ~3110s).  backlog
of 7 files flushed as fecd0d1, processes restarted (writer pid 3944,
batch pid 3945), push confirmed.

## what this visit adds

a new module — `iamai/stroke_availability.py` — that measures what
fraction of wall-clock time the writer is actually producing strokes.

### why it matters

the caretaker already tracks stalls, recovery time, and commit churn
separately.  but there was no single number answering the question
every operator really wants to know: **how often is the writer
actually working?**

availability = productive_time / wall_clock_time

where productive_time = wall_clock minus the sum of all stall
durations (gaps exceeding a configurable threshold, default 300s).

### stroke_availability.py

core types and functions:

- `StallRecord` — dataclass for one detected stall: index, start/end
  timestamps, duration, and a `lost_strokes(cadence)` method.

- `StrokeAvailability` — main analyzer.  takes a timestamp series,
  expected cadence, and stall threshold.  exposes:
  - `stalls` — list of all detected stalls
  - `wall_clock_s()` — total elapsed time
  - `total_stall_s()` — sum of stall durations
  - `productive_s()` — wall clock minus stalls
  - `availability()` — ratio in [0, 1]
  - `band()` — excellent/good/fair/poor/critical
  - `lost_strokes()` — estimated strokes lost to stalls
  - `summary()` — complete dict for JSON/CLI output

- `availability_report()` — one-line human-readable summary.

availability bands:

| band       | range      | meaning                            |
|------------|------------|------------------------------------|
| excellent  | ≥ 0.95     | barely any disruption              |
| good       | 0.85–0.95  | occasional stalls, quick recovery  |
| fair       | 0.70–0.85  | noticeable downtime                |
| poor       | 0.50–0.70  | significant time lost              |
| critical   | < 0.50     | down more than running             |

### test_stroke_availability.py (49 tests)

test areas:

1. **StallRecord** — basic fields, lost_strokes with default/zero/
   fractional cadence.

2. **Stall detection** — no stalls, one stall, multiple stalls,
   exactly at threshold (not a stall), just above threshold (is a
   stall), empty list, single stroke, two strokes no gap.

3. **Availability metrics** — wall clock (basic, single, empty),
   total stall time, productive time (with/without stalls),
   availability ratio (perfect, with stall, empty, single),
   productive time floor at zero.

4. **Band classification** — all five bands reachable, boundary
   values verified via mock subclass (0.96→excellent, 0.94→good,
   0.84→fair, 0.69→poor, 0.49→critical).

5. **Lost strokes** — no stalls, above-threshold calculation,
   zero cadence guard.

6. **Summary** — key completeness, no-stalls case, with-stalls
   math, empty input.

7. **availability_report** — basic format, with stalls, empty,
   hours display.

8. **Edge cases** — identical timestamps, very large gap,
   descending timestamps, negative timestamps, rounding, stalls
   list returns copy, many small gaps, alternating stall/normal.

## overnight stall pattern (continued)

| visit | gap (s) | severity  |
|-------|---------|-----------|
| 784   | ~2640   | moderate  |
| 785   | ~2945   | moderate  |
| 786   | ~2915   | moderate  |
| 787   | ~3000   | moderate  |
| 788   | ~2986   | moderate  |
| 789   | ~3068   | moderate  |
| 790   | ~3110   | moderate  |

mean ~2952s (49.2 min), std dev ~148s.  the hosting environment's
idle timeout remains the dominant failure mode.  restart-and-resume
continues to recover cleanly every time.

## process status

writer: running, cadence 15s (pid 3944).
batch: running, interval 600s (pid 3945).
tree clean, push confirmed.
stroke count: 400+ per kind.
tracked files: 2618 (added stroke_availability.py, test, this note).
