# Caretaker Visit 45 — 2026-10-06 17:00

## Situation on Arrival

Both writer and batch committer were **down** on arrival — same stall
from the earlier session (longest gap 972s). The pre-execution harness
detected the stoppage, committed the 10-file backlog as `abd6afd`, and
restarted both processes before this visit began. The push succeeded
(`2a9ef62..abd6afd main -> main`).

After restart, the writer resumed producing strokes immediately (gap 3s
on arrival, both pids 1282/1283 alive).

## What I Did

1. **Verified processes** — writer pid 1282 and batch pid 1283 both
   alive and producing strokes after the pre-exec restart.

2. **Added `cadence_adherence` module** — `iamai/cadence_adherence.py`
   measures how consistently the writer hits its configured tick
   interval. This complements the existing health stack:

   - `stall_classifier` answers: is the writer dead?
   - `stroke_rate` answers: how many strokes per hour?
   - `cadence_adherence` answers: is the writer steady or erratic?

   A writer producing 240 strokes/hour looks healthy by rate alone,
   but if those come in bursts of 10 followed by 5-minute silences,
   the rhythm is broken. This module catches that.

   Three public functions:
   - `cadence_report(expected_cadence, window_hours)` — computes
     mean_gap, median_gap, jitter (coefficient of variation),
     adherence_pct (fraction of gaps within 2× cadence),
     long_stall_count (gaps exceeding 4× cadence)
   - `adherence_summary()` — one-line human-readable summary
   - `grade_adherence()` — letter grade A/B/C/F based on adherence %

   Key design choice: jitter uses coefficient of variation (stddev/mean)
   rather than raw standard deviation, because a 10s stddev means
   very different things at 15s cadence vs 60s cadence.

3. **Added 34 tests** — `tests/test_cadence_adherence.py` covers:
   - Timestamp parsing (UTC offset, Z suffix, bare datetime, whitespace)
   - JSONL loading (basic, empty, malformed, missing keys, missing file)
   - Window filtering (all within, some outside, empty)
   - Gap computation (regular, irregular, single stroke, unsorted input)
   - Cadence report (perfect cadence, erratic cadence, long stalls,
     empty file, missing file, single stroke)
   - Summary formatting (with data, without data)
   - Grade assignment (A/B/C/F boundaries, missing data)

4. **Committed and pushed** — this visit note, the new module, and all
   tests together with the writer's live strokes.

## Why Cadence Adherence

Visit 44 added `stroke_rate` (how fast). Visit 43 added `uptime_tracker`
(how long). Visit 42 added `commit_health` (overall score).

But "fast" doesn't mean "steady". A writer with a cold LLM backend might
produce strokes in bursts — 5 quick ones while the cache is warm, then
a 90-second pause while the next prompt is processed. The hourly rate
looks normal, but the writer is clearly struggling.

Cadence adherence catches this by looking at the *distribution* of
inter-stroke gaps rather than just their average. The jitter metric
(coefficient of variation) is the key signal: 0.0 means metronomic,
0.5 means somewhat erratic, 1.0+ means highly irregular.

The letter grade (`grade_adherence`) gives caretakers a quick at-a-glance
signal: A (≥95% adherence) is excellent, F (<60%) means the writer is
running but rhythmically broken.

## Metrics at Arrival

- 400+ strokes total (writer actively producing)
- 365 tracked files
- Writer gap: 3s (fresh after restart)
- Longest gap: 972s (historical stall from previous session)
- Processes: writer pid 1282, batch pid 1283 (both up after restart)
- Pending files at arrival: 10 (committed by pre-exec harness as abd6afd)
- Push: successful

## Files Changed This Visit

- `notes/caretaker-visit-45-2026-10-06.md` (this note)
- `iamai/cadence_adherence.py` (new module: rhythm quality metrics)
- `tests/test_cadence_adherence.py` (new test file, 34 tests)
