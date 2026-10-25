# caretaker visit 259

**date:** 2026-10-21
**stroke:** 4048+
**status:** processes alive, backlog committed, uptime_fatigue_analysis module added (23 tests pass)

---

## what happened

arrived at 06:00 GMT+8 to find writer (pid 69128) and batch (pid 69129)
both running — restart had already happened via run_both.sh preflight at
06:00. git index.lock was absent (auto_lock_clean in run_both.sh had
cleared it before startup). 9 files were staged from the overnight
stall window.

## what i did

1. verified both processes alive (no restart needed this time)
2. confirmed index.lock absent — auto_lock_clean did its job
3. committed 9-file staged backlog (1 commit)
4. wrote `tools/uptime_fatigue_analysis.py` — tests the hypothesis
   from visit 258 that stall onset correlates with cumulative uptime
   (fatigue model: memory leaks, fd exhaustion, growing state)
5. wrote 23 tests covering stall detection, session building, fatigue
   scoring, classification boundaries, and summary formatting — all
   passing
6. ran analysis on full stroke history (4048 strokes, 427 stalls)
7. wrote this note, committed, pushed

## finding: fatigue is not the dominant cause

    sessions analyzed : 428
    stalls recorded   : 427
    fatigue_score     : 0.5012
    verdict           : mixed
    median uptime     : 779s
    max uptime        : 5763s

a fatigue_score of 0.5012 is essentially coin-flip — stalls are
equally likely in short sessions as in long ones. this rules out
simple fatigue models (memory leak, fd accumulation) as the primary
driver.

## what this means

with both the batch-interval hypothesis (visit 258, score 0.20) and
the fatigue hypothesis (visit 259, score 0.50) ruled out, the
remaining candidates are:

1. **external disruption** — network timeouts, API rate limits, or
   host-level resource pressure that strikes at random intervals
   regardless of uptime or batch phase
2. **stroke-content correlation** — specific stroke types (e.g.
   ones requiring network I/O or heavy computation) trigger stalls
   independent of how long the writer has been running

next step: stroke-type analysis. bucket strokes by `kind` field
and test whether stalls cluster after specific stroke types. if
a particular kind (e.g. "metrics" strokes that read git stats)
precedes stalls disproportionately, the root cause is in that
code path.

## process note

this is the first visit where auto_lock_clean in run_both.sh
successfully prevented a lock-stuck startup without manual
intervention. visit 258's fix (adding auto_lock_clean to the
preflight path) is working as intended.
