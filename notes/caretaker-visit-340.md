# caretaker visit 340 — 2026-10-24

## focus
recovery time analysis — measuring how fast the writing pipeline bounces back

## what was done
added `scripts/recovery_time_analyzer.py` — a tool that detects stalls in
the commit timeline and scores the pipeline's recovery health.

four metrics, each 0–25 (total 0–100, lower is better):

1. **mean_recovery_time** — average seconds from stall-end to first new stroke
2. **recovery_consistency** — std-dev of recovery times (predictability)
3. **stall_frequency** — how often stalls occur per 100 commits
4. **post_recovery_cadence** — does the writer return to full speed or limp?

grading: RESILIENT (0–20), ROBUST (21–45), FRAGILE (46–70), BRITTLE (71–100)

## why this matters
the repo has had 400+ strokes across 339 caretaker visits, but stalls happen:
process crashes, resource exhaustion, caretaker pauses. without measuring
recovery, we can't tell if the pipeline is getting more resilient over time
or silently degrading. this tool makes recovery visible and trackable.

## tests
47 tests in `tests/test_recovery_time_analyzer.py`:
- timestamp parsing: standard format, without timezone, invalid, empty
- commit classification: stroke, caretaker, recovery, other, case-insensitive
- stall detection: no stalls, single, multiple, edge cases, context records
- recovery times: extraction, empty input
- mean recovery scoring: instant, fast, moderate, slow, bounded
- consistency scoring: single, empty, consistent, low/high variance, bounded
- stall frequency scoring: none, rare, frequent, zero commits, bounded
- post-recovery cadence: no stalls, few commits, healthy recovery
- full score computation: non-repo error, valid repo structure
- formatting: progress bars, error reports, full reports

## observations
the repo's writer had been stopped (both writer and batch processes recycled).
9 pending files were committed before restart. push was rejected by remote
(new commit from another agent); resolved via rebase. pipeline restarted
at writer pid + batch pid with 15s stroke cadence and 600s batch interval.

## next steps
- monitor recovery times over the next 10 visits to establish baseline
- consider adding a recovery_time metric to the METRICS.md dashboard
- if stall frequency stays high, investigate root causes (OOM? lock contention?)
