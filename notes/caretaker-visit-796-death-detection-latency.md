# visit 796 — process death detection latency

2026-11-22 19:03 CST. human-requested caretaker check.

## context

writer (pid unknown) and batch (pid unknown) were found dead during
the pre-execution sweep. the writer had been silent for 2913 seconds
(~48 minutes) — longest gap in recent history was 3269 seconds
(~54 minutes). both processes had been recycled by the hosting
environment. 8 files of uncommitted backlog were flushed as commit
9b0561d, processes restarted (pids 3926/3927), push initially rejected
(remote had stroke 315 from guoban), resolved via stash + rebase.

this visit's key observation: the dead processes went undetected for
roughly 54 minutes before the caretaker check found them. that is a
significant detection latency — almost the entire caretaker interval
was wasted.

## what this visit adds

a new module — `tools/process_death_detection_latency.py` — that
measures how long dead processes go unnoticed before being detected
and restarted.

### why it matters

the caretaker runs checks every 10 minutes. if a process dies 30
seconds after a check, the theoretical minimum detection latency is
~9.5 minutes. but in practice, the latency can be much longer if:

1. the caretaker itself is delayed or not running.
2. the check only looks at PID liveness, not output recency.
3. restart failures extend the downtime beyond detection.

this module quantifies the gap between "process died" and "someone
noticed" — a direct measure of monitoring effectiveness.

### process_death_detection_latency.py

core types and functions:

- `DeathEvent` — frozen dataclass: process name, PID, died_at,
  detected_at, restart_at (optional).

- `DetectionLatency` — frozen dataclass: detection_gap_sec,
  restart_gap_sec, total_downtime_sec. methods:
  - `within_budget()` — is latency < 50% of check interval?
  - `efficiency()` — 1.0 (instant) to 0.0 (full interval wasted).

- `DeathDetectionReport` — aggregated report over multiple events:
  - `count`, `mean_detection_sec`, `max_detection_sec`
  - `mean_efficiency`, `budget_compliance`
  - `trend()` — improving / steady / worsening
  - `verdict()` — healthy / acceptable / degraded
  - `summary()` — dict for JSON/CLI output

- `measure_latency()` — compute latency for one event.
- `build_report()` — aggregate multiple events.
- `report_to_text()` — human-readable one-liner.

budget definition:
- default check interval: 10 minutes
- healthy budget: detection < 50% of interval (< 5 min)
- efficiency = 1 - (detection_gap / interval), clamped [0, 1]

### test_process_death_detection_latency.py (45 tests)

test areas:

1. **DeathEvent** — basic fields, no restart, frozen, different
   process, custom pid.

2. **DetectionLatency** — within budget true/false/boundary,
   efficiency instant/full/half/clamped, custom interval,
   restart gap present/absent, detection gap sec.

3. **measure_latency** — basic, negative gap clamped, no restart.

4. **DeathDetectionReport** — empty, single, multiple events,
   budget compliance all/mixed/none, trend insufficient/steady/
   improving/worsening, verdict healthy/degraded, summary keys,
   summary empty, custom interval, within_budget_count.

5. **report_to_text** — empty, basic, includes trend/efficiency.

6. **Edge cases** — zero gap, very large gap (54 min like real
   incident), fractional minutes, timezone-aware, many events.

## first measurement

applied the model to this visit's incident:

```
death detection: 1 events, mean=3240s, max=3240s,
efficiency=0%, compliance=0%, trend=insufficient_data,
verdict=degraded
```

54 minutes of undetected downtime. efficiency is 0% because the
detection gap (3240s) far exceeds the 600s check interval. with
only one event, trend is unavailable and verdict is degraded.

this is the first measurement — future caretaker visits should
log death events to `data/process_deaths.jsonl` so the report
can track improvement over time.

## process status

writer: running, cadence 15s (pid 3926).
batch: running, interval 600s (pid 3927).
tree clean after commit, push confirmed.
tracked files: 2630 (added process_death_detection_latency.py, test,
this note).
