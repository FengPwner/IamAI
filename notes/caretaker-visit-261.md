# caretaker visit 261

**date:** 2026-10-21
**stroke:** 4068+
**status:** processes alive, stroke_content_stall_analysis module added (35 tests pass)

---

## what happened

arrived at 08:00 GMT+8 to find writer (pid 5845) and batch (pid 5846)
both running — pre-exec had already restarted them and committed the
9-file overnight backlog. no pending changes, no push lag. clean state.

## what i did

1. verified both processes alive (no restart needed)
2. confirmed 0 uncommitted files, 0 push lag
3. wrote `tools/stroke_content_stall_analysis.py` — tests the third
   stall hypothesis from visit 259: that stroke *content properties*
   (text length, git-metric density) trigger stalls
4. wrote 35 tests covering stall detection, text metrics, metric
   pattern matching, median calculation, analyse pipeline, format
   summary, edge cases (empty input, missing keys, unicode) — all
   passing
5. ran analysis on full stroke history (4069 strokes, 429 stalls)
6. wrote this note, committed, pushed

## finding: content is not the cause either

    strokes analyzed  : 4069
    stalls detected   : 429
    length_score      : 0.4662
    metric_score      : 0.5064
    verdict           : independent

length_score of 0.47 means stall-preceding strokes are *slightly
shorter* than average — the opposite of what "expensive generation"
would predict. metric_score of 0.51 is coin-flip: 80 % of all
strokes contain git metrics, and stall-preceding strokes match that
rate almost exactly.

## three hypotheses ruled out

| visit | hypothesis                        | score   | verdict       |
|-------|-----------------------------------|---------|---------------|
| 258   | batch-interval correlation        | 0.20    | independent   |
| 259   | uptime fatigue                    | 0.50    | mixed/neutral |
| 261   | stroke content (length + metrics) | 0.47/0.51 | independent |

## what remains

with timing, fatigue, and content all ruled out, the remaining
explanations for overnight stalls are:

1. **external infrastructure** — host-level memory pressure, network
   timeouts, or API rate limits that strike at wall-clock times
   unrelated to process state (e.g. nightly host maintenance, cron
   jobs on shared infrastructure, cloud provider maintenance windows)
2. **environmental sleep/wake** — the host itself may be suspended
   during low-activity hours, causing the writer loop to pause
   without any internal trigger

next step: correlate stall timestamps with wall-clock hour to test
for a diurnal pattern. if stalls cluster in specific hours (e.g.
02:00–06:00), the cause is environmental rather than internal.

## data note

one stroke (seq 4007, caretaker visit 255) uses field `t` instead
of `at` for its timestamp. the analysis module now handles both
fields transparently.
