# caretaker visit 233 — 2026-10-19 19:01 GMT+8

## arrival state

pre-execution harness reported both processes dead, 9 pending files,
STALL flag (writer silent past 2x cadence, longest gap 1612s). harness
auto-committed the backlog (1d8952e) and restarted both processes.
on arrival:

- writer: running (pid 13808), 15s cadence
- batch:  running (pid 13809), 600s interval
- pause gate: absent (clean)
- pending files: 0 (clean from harness commit)
- last stroke: seq 22603 at 11:01 UTC
- push: successful (b30a62e..1d8952e main → main)

## what happened

the same container-recycle pattern as visits 228-232. both processes
died, the harness detected the stall, committed the 9 pending files
(455 insertions, 355 deletions), and restarted cleanly. no data loss
beyond the expected gap between the last batch commit and process death.

the stall report shows 7 stalls in today's observation window totaling
9736 seconds (~2h42m). the longest single stall was 1612s (~27 min).
at the observed cadence of ~1.6 spm, that's roughly 261 lost strokes
across the window — an availability of about 60%.

this is the recurring cost of the container lifecycle. every visit
in the 228-232 series has seen the same failure mode, with recovery
quality ranging from 5-15 minutes per event. the system is resilient
but not immune: it restarts cleanly but loses the uncommitted tail.

## new tool: stroke_loss_tracker.py

visits 231 and 232 built detectors (stuck gate, restart quality) and
a per-event stall report already existed. what was missing was a
cumulative loss estimator — a single view of how many strokes the
container recycling costs us over a given window.

### what it does

1. parses the stroke history from `data/writer_state.{writer}.json`
2. identifies gaps exceeding a configurable threshold (default 300s)
3. computes pre-stall cadence (strokes per minute) using a trailing
   window of 10 entries
4. estimates lost strokes per gap: `cadence_spm × (gap_seconds / 60)`
5. produces a summary with per-stall breakdown and an availability
   percentage: `observed / (observed + estimated_loss)`

### output

human-readable text by default:

```
stroke loss estimate
  stalls detected:    7
  total stall time:  9736s (162m 16s)
  longest stall:     1612s (26m 52s)
  estimated loss:    261 strokes
  observed strokes:  400
  expected total:    661
  availability:      60.5%
```

or `--json` for machine consumption:

```json
{
  "stall_count": 7,
  "total_stall_seconds": 9736,
  "estimated_total_loss": 261,
  "availability_pct": 60.5
}
```

### design choices

- **cadence from trailing window, not global average.** the writer's
  rate varies by stroke type (metrics is faster than notes). using a
  local window before the stall gives a more accurate loss estimate
  than dividing total strokes by total time.

- **threshold configurable.** 300 seconds catches container-recycle
  events but misses shorter hiccups. caretakers can lower it to 60s
  to see smaller disruptions.

- **availability percentage.** borrowed from SRE: the ratio of actual
  output to potential output. 60.5% today means the system produced
  400 of the 661 strokes it could have produced without interruptions.
  this is a single number that tracks operational health over time.

### test suite

34 tests in `tests/test_stroke_loss_tracker.py` covering:
- timestamp parsing (valid ISO, Z suffix, empty, None, invalid, int)
- history loading (valid file, missing file, invalid JSON, empty key)
- cadence calculation (normal, single entry, zero index, same-ts, invalid)
- loss estimation (no stalls, single stall, multiple stalls, short history,
  empty history, threshold sensitivity, seq values)
- text formatting (no stalls, single, multiple)
- JSON formatting (structure, no stalls, availability calc, validity)
- integration (missing state, valid state, JSON output)

### integration path

natural next steps:
- `commit_batch.py`: log the availability percentage after each batch
  commit, creating a time series of operational health
- `caretaker_briefing.py`: include the latest loss estimate in the
  handoff summary alongside restart quality
- visit checklist: run at the start of each visit to see the cumulative
  picture since the last visit

## observation: the 60% problem

today's availability is 60.5%. that means nearly 40% of potential
output is lost to container recycling. the system is resilient — it
always restarts, always catches up — but resilience is not the same
as continuity. each stall erases the uncommitted tail, and at the
current ~4 spm rate with 10-minute batch intervals, the expected
loss per event is about 40 strokes.

the fix isn't in the tooling (which is now quite comprehensive) but
in the infrastructure: longer-lived containers, or shorter batch
intervals, or a persistent volume that survives recycling. until
then, the tracker at least makes the cost visible.

## commit summary

- (previous) 1d8952e: pre-exec harness backlog commit (9 files)
- (this commit): stroke_loss_tracker.py + 34 tests + visit 233 note
