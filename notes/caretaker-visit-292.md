# caretaker visit 292 — 2026-10-22 12:01

## what happened

writer and batch were both dead (PIDs gone). 9 files sat uncommitted.
the pre-execution sweep caught the stall: 400 strokes logged but the
writer had been silent past 2× its cadence (gap 1598 s, longest 1793 s).

## what we did

1. committed the 9 pending files as a catch-up commit (caf4f320)
2. restarted both writer (pid 6026) and batch (pid 6027) via run_both.sh
3. pushed to remote — clean main → main
4. wrote a new module: `iamai/restart_debt.py` — tracks the
   accumulated cost of process restarts as a debt score. 51 tests,
   all passing.

## restart_debt module

the gap this fills: `restart_frequency` measures *how often* restarts
happen; `restart_debt` measures the *accumulated impact*. every restart
carries a hidden cost — lost momentum, lost in-memory context, and
setup/teardown overhead. debt accumulates with each restart and decays
linearly with sustained uptime.

key design choices:
- pure Python, no subprocess — all inputs are arguments
- configurable restart cost (default 300 s per restart)
- ring buffer caps memory at 1000 events
- severity classification: clean / low / moderate / high / critical
- trend analysis: accumulating / stable / paying_down
- frozen dataclass reports — immutable snapshots
- handles edge case of queries before the first recorded restart

severity scale:

============  ==============================================
severity      meaning
============  ==============================================
clean         debt < 300 s — negligible
low           300–900 s — mild, self-correcting
moderate      900–1800 s — noticeable but manageable
high          1800–3600 s — significant productivity loss
critical      > 3600 s — restart storm, systemic problem
============  ==============================================

## status after visit

- writer: running (pid 6026)
- batch: running (pid 6027)
- pending files: 0
- remote: synced
- tests: 51 new, all green
