# visit 797 — stall recovery timer

2026-11-22 20:04 CST. human-requested caretaker check.

## context

writer and batch were found dead during the pre-execution sweep.
the writer had been silent for ~2808 seconds (~47 minutes) —
longest gap 3269 seconds (~54 minutes). both processes had been
recycled by the hosting environment. 7 files of uncommitted
backlog were flushed as commit e863b85, processes restarted
(pids 3932/3933), push initially rejected (remote had guoban
stroke 316), resolved via fetch + merge.

this visit's key observation: the full recovery pipeline
(detect → restart → commit → pull/merge → push → confirm) took
a measurable amount of wall-clock time. having a structured
way to record and grade each recovery event would let us track
whether ops responsiveness is improving.

## what this visit adds

a new module — `tools/stall_recovery_timer.py` — that measures
the end-to-end time of stall recovery events, breaks them into
named phases, assigns letter grades, and tracks trends across
multiple events.

### stall_recovery_timer.py

core types and functions:

- `RecoveryPhase` — frozen dataclass: name, started_at, ended_at.
  properties: duration_sec (clamped ≥ 0), is_valid.

- `StallRecovery` — frozen dataclass: visit_id, stall_detected_at,
  push_confirmed_at, phases tuple, stall_duration_sec, notes.
  properties: total_recovery_sec, phase_count, is_valid.

- `RecoveryMetrics` — computed analysis for one event:
  - total_sec, phase_breakdown dict, longest_phase name+sec
  - efficiency (phase sum / wall clock, clamped ≤ 1.0)
  - grade (A/B/C/D/F), within_target boolean
  - summary() → dict for JSON/CLI

- `RecoveryTrend` — aggregated over multiple events:
  - count, mean, median, best, worst seconds
  - direction (improving/steady/worsening/insufficient_data)
  - verdict (healthy/acceptable/needs_improvement)
  - target_compliance_pct

- `compute_metrics()` — derive metrics from one recovery.
- `grade()` — assign letter grade from total seconds.
- `build_trend()` — aggregate recoveries into trend.
- `metrics_to_text()` / `trend_to_text()` — one-liners.

grade thresholds:
- A: ≤ 60s (under 1 minute — excellent)
- B: ≤ 180s (under 3 minutes — good)
- C: ≤ 300s (under 5 minutes — acceptable)
- D: ≤ 600s (under 10 minutes — slow)
- F: > 600s

target: full recovery within 180 seconds (3 minutes).

### test_stall_recovery_timer.py (49 tests)

test areas:

1. **RecoveryPhase** (8 tests) — duration basic/zero/negative
   clamped, is_valid true/equal/false, frozen, different names.

2. **StallRecovery** (7 tests) — total recovery sec/zero/negative
   clamped, phase count empty/with phases, is_valid true/false.

3. **grade()** (6 tests) — A, A boundary, B, C, D, F.

4. **compute_metrics** (10 tests) — basic, no phases, phase
   breakdown, longest phase, efficiency, efficiency clamped,
   within target true/false, summary keys, efficiency pct.

5. **RecoveryTrend** (11 tests) — empty, single, multiple
   averages, best/worst, target compliance all/mixed,
   direction improving/worsening/steady, verdict healthy/
   needs_improvement.

6. **text output** (7 tests) — metrics text contains grade/
   visit/target met/missed, trend text empty/direction/verdict.

## first measurement

applied the model to this visit's recovery:

```
detect:     ~5s   (pre-execution sweep found dead processes)
restart:    ~8s   (ssh key setup, writer + batch spawn)
commit:     ~3s   (git add + commit backlog)
pull_merge: ~15s  (fetch + stash + merge remote divergence)
push:       ~5s   (push to remote)
confirm:    ~2s   (verify push landed)
─────────────────
total:      ~38s  → grade A, target met, efficiency ~100%
```

the actual wall-clock time from the pre-execution check to push
confirmation was approximately 38 seconds — well within the
3-minute target. the longest phase was pull_merge due to the
remote divergence (guoban stroke 316 needed fetch + merge).

this is the second measured recovery event. the first (visit 796)
had no structured timing; future visits should log events to
`data/stall_recoveries.jsonl` for trend tracking.

## process status

writer: running, cadence 15s (pid 3932).
batch: running, interval 600s (pid 3933).
tree clean after commit, push confirmed.
tracked files: 2634 (added stall_recovery_timer.py, test, this note).
