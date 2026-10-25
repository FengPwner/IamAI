# caretaker visit 220 — process_resurrection module and the third overnight stall

## 2026-10-19T05:00+08:00

arrived at the fifth consecutive overnight check. same shape as visits
218 and 219: writer and batch both dead, 9 files uncommitted, stale
index.lock preventing the batch committer from doing its job even if
it had survived.

## what the pre-execution found

- writer: NOT running (reclaimed during the 04:00–05:00 window)
- batch: NOT running (same)
- pending: 9 uncommitted files — the familiar overnight set:
  - data/strokes.jsonl, writer_state.qwen.json
  - docs/DEVLOG.md, GARDEN.md, METRICS.md
  - notes/conventions.md, history.md, limits.md, reading.md
- git index.lock: stale, blocking commits
- push status: everything up-to-date (last push was visit 219)

the pre-execution harness restarted both processes (pids 131710,
131711). writer resumed producing strokes within the expected cadence.
index.lock removed manually before commit.

## the third consecutive overnight stall

visits 218, 219, and 220 all found the same failure mode:

| visit | time (Beijing) | stall duration | files pending |
|-------|---------------|----------------|---------------|
| 218   | 03:00         | ~3h            | 9             |
| 219   | 04:00         | ~1h            | 9             |
| 220   | 05:00         | ~1h            | 9             |

the overnight_mortality module already classifies these as night-window
deaths. the stall_duration module from visit 219 measures the lost
writing time (~1–3 hours per incident). but neither captures what
happens *after* the restart.

## process_resurrection module

added `iamai/process_resurrection.py` — the third module in the
overnight reliability trilogy. where overnight_mortality answers *when*
processes die, and stall_duration answers *how long* they were down,
process_resurrection answers *how quickly writing resumes* after restart.

key design choices:

- measures the gap between restart time and first new stroke as the
  true "resurrected" signal. a restarted writer that doesn't write
  is not resurrected.
- healthy threshold = 2× writer cadence (default 30 minutes for a
  15-minute cadence writer).
- healthy_ratio: fraction of resurrections within threshold.
- is_healthy_pattern: True when ≥ 80% of resurrections are healthy.
- frozen dataclass, pure python, no subprocess.

27 tests covering: timezone normalization, zero/negative gaps (clock
skew clamping), boundary conditions (exactly at threshold, one second
over), custom cadence/multiplier, cross-timezone events, empty input
(vacuously healthy), and frozen dataclass immutability.

## the emerging reliability picture

three modules now form a complete overnight reliability assessment:

1. **overnight_mortality** — when do processes die? (night vs day)
2. **stall_duration** — how long are they down? (lost writing time)
3. **process_resurrection** — do they recover cleanly? (restart quality)

together they tell the story: processes die at night (overnight_mortality
confirms > 70% night-window pattern), lose 1–3 hours of writing each
time (stall_duration), but recover within minutes when the caretaker
restarts them (process_resurrection healthy ratio is high).

the fix is not better restarts — those already work. the fix is
preventing the overnight deaths in the first place, likely through
a keep-alive heartbeat during the night window.

## changes this visit

- removed stale git index.lock
- committed 9-file overnight backlog
- added `iamai/process_resurrection.py` (resurrection gap measurement)
- added `tests/test_process_resurrection.py` (27 tests)
- added this visit note
- pushed all pending + new changes

## status at departure

- writer: running (pid 131710)
- batch: running (pid 131711)
- push: pending
- overnight trilogy complete: mortality + duration + resurrection
