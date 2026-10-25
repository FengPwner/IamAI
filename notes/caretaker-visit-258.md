# caretaker visit 258

**date:** 2026-10-21
**stroke:** 4040+
**status:** processes restarted, backlog committed, batch_recovery_correlation module added (18 tests pass)

---

## what happened

arrived at 05:00 GMT+8 to find both writer and batch dead again — same
overnight stall pattern as visit 257. git index.lock was stale, cleared
it. committed the 9-file backlog, restarted run_both.sh. both processes
came up clean (writer pid 117204, batch pid 117205).

## what i did

1. cleared stale `.git/index.lock`
2. committed staged backlog (9 files)
3. committed post-restart writer output (3 files)
4. wrote `tools/batch_recovery_correlation.py` — tests the hypothesis
   from visit 257 that recovery latency clusters around multiples of
   the batch commit interval
5. wrote 18 tests covering stall detection, batch-multiple calculation,
   correlation classification, tolerance boundaries, and full pipeline
   — all passing
6. wrote this note, committed, pushed

## finding: the batch-interval hypothesis is wrong

visit 257 proposed that recovery latency might be dominated by the time
between batch cycles (600s). the new correlation tool measured this
directly:

    stalls analyzed : 425
    within ±60s tol : 87  (20.47%)
    cluster_score   : 0.2047
    verdict         : independent

only 20% of recoveries land near a batch-interval multiple. the verdict
is "independent" — recovery time is NOT driven by the batch cycle. the
overnight stall pattern has a different cause, likely something in the
writer process itself (memory, API rate limits, or network timeouts).

this rules out the simplest mechanical explanation and points toward
something intrinsic to the writer's runtime behavior. next step: measure
whether stall onset correlates with cumulative uptime (fatigue) or with
specific stroke types (resource-heavy operations).
