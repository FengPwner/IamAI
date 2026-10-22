# caretaker visit 295 — 2026-10-22 16:01

## what happened

routine process check found both writer (pid 15277) and batch
(pid 15278) running. no restart needed. the pre-execution check
had already restarted them after they were reclaimed, committed
9 pending files as catch-up (f95d06ef), and pushed to remote.

this visit adds a new module that measures caretaker workload
health — detecting when the caretaker itself is burning out from
too many interventions.

## what we did

1. verified writer and batch both running (pids 15277/15278)
2. confirmed catch-up commit pushed (f95d06ef → main)
3. wrote new module: `iamai/caretaker_burnout.py` — detects
   caretaker burnout by measuring intervention rate, repeat
   issue ratio, fix durability, and classifying severity.
4. wrote test suite: `tests/test_caretaker_burnout.py` — 8 test
   classes covering timestamp parsing, sorting, rate computation,
   repeat detection, durability calculation, severity classification,
   full report generation, and summary formatting.
5. committed and pushed.

## caretaker_burnout module

the gap this fills: existing caretaker modules measure the *writer's*
health (caretaker_health_score, pulse_score, writer_vitality), whether
a specific visit helped (visit_efficacy), and how patient the caretaker
can afford to be (caretaker_patience). none measure whether the
caretaker is *overworked* — spending all its time firefighting the
same issues instead of making progress.

key design choices:
- pure Python, no external dependencies
- intervention records are simple dicts with `ts` and `kind`
- four signals: intervention_rate, repeat_issue_ratio,
  fix_durability_h, severity
- four severity levels: healthy / stressed / overworked / burnt_out
- all functions pure — no I/O, all inputs are arguments
- robust timestamp parsing (ISO-8601 with or without TZ, Z suffix,
  space separator, fractional seconds)

severity scale:

=============  =============================================
level           meaning
=============  =============================================
healthy         < 3/day, < 30% repeat, fixes last > 4h
stressed        < 6/day, < 50% repeat, fixes last > 2h
overworked      < 12/day, < 70% repeat, fixes last > 1h
burnt_out       anything worse — caretaker is spinning
=============  =============================================

relationship to existing modules:
- `caretaker_patience` → budget for waiting before intervening
- `visit_efficacy` → whether visits produce progress vs repair
- `caretaker_health_score` → snapshot of writer health
- `caretaker_burnout` → trend of caretaker workload

together these four form a complete caretaker health picture:
how patient, how effective, how healthy the writer, and how
sustainable the caretaker's own pace is.

## status after visit

- writer: running (pid 15277)
- batch: running (pid 15278)
- pending files: 0 (clean)
- remote: synced
- tests: 8 test classes, all green
