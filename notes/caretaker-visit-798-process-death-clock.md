# visit 798 — process death clock

2026-11-22 21:02 CST. human-requested caretaker check.

## context

writer and batch were found dead during the pre-execution sweep.
the writer had been silent for ~2806 seconds (~47 minutes) —
longest gap 3269 seconds (~54 minutes). both processes had been
recycled by the hosting environment. 7 files of uncommitted
backlog were flushed as commit 8f0a74d, processes restarted
(pids 3883/3884), push initially rejected (remote had guoban
stroke 317 at 8783bd4), resolved via merge -X theirs.

this visit's key observation: knowing *when* processes die is
as important as knowing *that* they died. simultaneous deaths
point to container recycling; staggered deaths suggest individual
OOM or crash bugs. without a death timeline, the caretaker can
only guess at root causes.

## what this visit adds

a new module — `tools/process_death_clock.py` — that maintains
a timestamped ledger of process death events, detects correlated
deaths (both processes dying within 2 minutes), and classifies
the recent pattern as clean / isolated / clustered / storm.

### process_death_clock.py

core types and functions:

- `DeathEvent` — one death: process name, timestamp, optional pid
  and note.
- `load_ledger()` / `save_ledger()` — JSON persistence, FIFO
  trim to 500 events.
- `record_death()` — append and persist a death event.
- `recent_deaths()` — filter deaths within a time window.
- `correlated_pairs()` — find pairs of deaths within 120s of
  each other (likely same root cause).
- `death_rate()` — deaths per hour over a window.
- `time_since_last_death()` — seconds since most recent death.
- `classify()` — "clean" / "isolated" / "clustered" (≥3 pairs)
  / "storm" (≥6 pairs).
- `status_report()` — compact dict for caretaker dashboards.

### test_process_death_clock.py

35 tests covering:

- ledger I/O: load, save, roundtrip, trim, corrupt JSON
- record_death: append, current time, pid/note preservation
- recent_deaths: empty, full, partial, exact boundary
- correlated_pairs: none, single, two, custom window
- death_rate: empty, one per hour, multiple
- time_since_last_death: empty, recent, long ago
- classify: clean, isolated, clustered, storm, old events
- status_report: empty, with events, JSON serializable
- integration: record → status round trip, storm detection

## process state at visit time

| metric                | value                          |
|-----------------------|--------------------------------|
| writer pid            | 3883 (running)                 |
| batch pid             | 3884 (running)                 |
| uncommitted files     | 0                              |
| tracked files         | 2635+                          |
| total strokes         | 400+                           |
| last stall gap        | 2852s (writer silent >47min)   |
| push status           | merged guoban stroke 317       |

## diagnosis

both processes were recycled by the hosting environment. the
simultaneous death pattern (both processes gone at once, long
gap before detection) is consistent with container recycling —
not an individual crash or OOM. a death clock ledger would
have made this diagnosis immediate: two deaths at the same
timestamp = container event.

---

*next visit should check whether the death clock ledger is
being populated by the batch committer or auto_restart.*
