# caretaker visit 296 — 2026-10-22 17:01

## what happened

routine process check found both writer and batch had been
reclaimed. the pre-execution pipeline restarted them (pids
10534/10535), committed 9 pending files as catch-up (5b8c6f81),
and pushed to remote.

this visit adds a new module that fills a gap in the recovery
toolkit — measuring whether the writer comes back at the same
level, not just whether it comes back at all.

## what we did

1. confirmed writer and batch running after pre-exec restart
2. verified catch-up commit pushed (5b8c6f81 → main)
3. noted STALL condition: writer silent 1592s past 2x cadence,
   400 strokes distributed evenly across 6 kinds
4. wrote new module: `iamai/recovery_fidelity.py` — measures
   post-restart recovery quality by comparing pre-stall and
   post-recovery stroke characteristics.
5. wrote test suite: `tests/test_recovery_fidelity.py` — 12 test
   classes, 60 tests, all green.
6. committed and pushed.

## recovery_fidelity module

the gap this fills: existing modules answer "is the writer alive
again?" (restart_warmup, restart_quality, process_uptime) and
"how long was the stall?" (stall_duration, stall_event). none
measure whether the writer recovered *fully* — producing strokes
at the same cadence, length, and diversity as before the stall.

a process can be technically alive yet still sick: shorter
strokes, slower rhythm, narrower vocabulary. recovery fidelity
detects this by comparing the pre-stall stroke set to the
post-recovery stroke set across four signals.

key design choices:
- pure Python, no external dependencies
- all inputs are arguments (no file I/O in core functions)
- robust to small samples: returns "unknown" below min_sample
- robust timestamp parsing (ISO-8601 variants, epoch floats)

four signals:

=====================  ==============================================
signal                 what it measures
=====================  ==============================================
cadence_fidelity       inter-stroke interval similarity (median
                       ratio × variance penalty)
length_fidelity        mean stroke length ratio (min/max bounded)
diversity_fidelity     vocabulary richness ratio (unique/total)
gap_stability          post-recovery gap coefficient of variation
                       (1 - cv, clamped to [0, 1])
=====================  ==============================================

fidelity score = mean of the four signals (equal weights).

grade scale:

============  =============================================
grade         meaning
============  =============================================
full          >= 0.90 — writer is back to pre-stall level
good          0.70–0.89 — minor degradation, trending back
partial       0.50–0.69 — clear gap, recovery incomplete
poor          < 0.50 — writer is still struggling
============  =============================================

relationship to existing modules:
- `restart_warmup` → how fast the first stroke appears
- `restart_quality` → did the restart fix the problem at all
- `recovery_fidelity` → how completely the writer recovered
- `writer_fatigue` → is the writer getting tired over time

together: restart_warmup says "it started", restart_quality says
"it's producing", recovery_fidelity says "it's producing *well*",
and writer_fatigue says "it can keep going".

## status after visit

- writer: running (pid 10534)
- batch: running (pid 10535)
- pending files: 0 (clean after catch-up)
- remote: synced
- tests: 12 test classes, 60 tests, all green
