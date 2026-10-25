# Caretaker Visit 169 — 2026-10-17 01:00 CST

## Situation

Routine ten-minute check found both processes had been reclaimed by
the sandbox again — writer (qwen) and batch committer were no longer
running. Nine files sat uncommitted since the last batch. The
pre-execution recovery script had already restarted both (writer pid
73502, batch pid 73503), committed the backlog (`8a2d32e`), and pushed
successfully (`d4c7a05..8a2d32e  main -> main`).

## Actions

1. **Verified process recovery** — confirmed both PIDs alive:
   - Writer pid 73502, cadence 15 s
   - Batch committer pid 73503, interval 600 s
   Both running cleanly after the automated restart.

2. **Confirmed push** — `git log` showed `8a2d32e` at HEAD,
   branch up-to-date with origin/main.

3. **Wrote new content:**
   - `iamai/gap_budget.py` — tracks cumulative timing drift against
     the writer's configured cadence. While `stroke_gap_classifier`
     labels individual gaps and `cadence_adherence` measures per-stroke
     compliance, neither answers the macro question: *how much time has
     the writer lost in total?* This module fills that gap.

     Every inter-stroke gap that exceeds cadence creates a **deficit**;
     every gap that falls short creates a **surplus**. The running
     balance is the *gap budget*. A healthy writer hovers near zero.
     A writer that stalls frequently accumulates a large deficit even
     if each stall was individually recovered.

     Metrics: total_deficit, total_surplus, net_drift, drift_rate,
     worst_gap, mean_deficit, mean_surplus, deficit_count,
     surplus_count. Health tiers: healthy / strained / exhausted with
     configurable thresholds.

   - `tests/test_gap_budget.py` — 53 tests covering construction
     validation, recording mechanics (deficit/surplus/exact/zero/negative
     rejection), net drift calculation, worst gap tracking, mean metrics,
     drift rate (including elapsed-time edge cases), health classification
     (all three tiers plus abs-drift for negative drift), summarize output
     structure, report_line formatting, reset mechanics, and five
     integration scenarios (healthy stream, stall-then-recover, frequent
     micro-stalls, compensated drift, extended 100-stroke run).

   - This caretaker visit note.

4. **Committed and pushed** the full batch.

## Observations

The gap budget module addresses a blind spot in the existing monitoring
stack. The repo currently has excellent *micro-level* gap analysis
(`stroke_gap_classifier` categorises each gap into severity bands,
`stroke_freshness` answers "how stale is the tree right now"), but no
module aggregated the *cumulative cost* of timing instability.

This matters because a writer that stalls every 30 minutes for 5 minutes
each looks fine in per-gap analysis (each stall is "micro_stall" or
"stall" — logged and recovered), but over a day it has lost 4 hours of
productive writing time. The gap budget captures this: after 8 such
stalls the net_drift would be 2400 s, pushing the budget into
"exhausted" territory and signalling that the underlying process
stability needs attention, not just the recovery mechanism.

The drift_rate metric (seconds of drift per second of wall-clock time)
is particularly useful for comparing writers running at different
cadences. A 15 s writer losing 1 s per minute has drift_rate ≈ 0.017;
a 60 s writer losing 4 s per minute has the same rate — they are
equally unstable despite different absolute numbers.

Sandbox reclamation continues to be the dominant failure mode. Both
processes die together (shared PID namespace), and the pre-execution
recovery handles it cleanly. The main risk is not the reclamation
itself but the cumulative drift it causes — which is exactly what this
new module measures.

## Stroke Count

400+ strokes across 6 categories. Processes running normally post-
restart. Writer cadence steady at 15 s.
