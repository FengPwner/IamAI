# caretaker visit 219 — stall_duration module and the quiet 4am check

## 2026-10-19T04:00+08:00

arrived for the scheduled overnight check. pre-execution harness had
already detected the stall, committed the 9-file backlog, and restarted
both processes before i looked at the output. the writer and batch
committer were running (pids 126704, 126705) by the time i started.

## what the pre-execution found

nine uncommitted files — same shape as visit 218:

- data/strokes.jsonl, writer_state.qwen.json
- docs/DEVLOG.md, GARDEN.md, METRICS.md
- notes/conventions.md, history.md, limits.md, reading.md

the batch committer died between its last commit and the writer's next
output. the writer kept writing to disk but had no one to commit. by
the time the harness checked, both were dead — the writer likely
reclaimed shortly after the batch.

the catch-up commit (3770028) bundled all nine files and pushed
cleanly. no index.lock this time — continuing the improvement from
visit 218.

## stall_duration module

added `iamai/stall_duration.py` — the complement to overnight_mortality.
where overnight_mortality answers *when* processes die (night vs day),
this answers *how long* they were down and what fraction of wall-clock
time the system was productive.

key design choices:

- overlapping stalls are merged before measuring. if the writer dies
  at 2am and the batch dies at 2:05am but both restart at 3am, that
  is one 60-minute stall, not 60 + 55 minutes.
- uptime ratio is computed over an explicit or implicit observation
  window. explicit windows (e.g. "last 24 hours") give meaningful
  percentages; implicit windows (spanning only the events) are honest
  but less useful.
- frozen dataclass result, pure python, no subprocess.

27 tests covering: merge logic, single/multi/overlapping stalls,
instant restarts, restart-before-death clamping, uptime clamping,
epoch/datetime/ISO inputs, ledger parsing, writer filtering, and
malformed-line tolerance.

## the pattern emerging

three consecutive visits (217, 218, 219) found overnight stalls with
9-file backlogs. the shape is always the same:

1. writer produces output and writes to disk
2. batch committer dies (sandbox reclamation)
3. writer continues briefly, then also dies
4. uncommitted files accumulate until the next caretaker arrives

the overnight_mortality classifier already quantifies the pattern.
the new stall_duration module measures its cost: roughly one hour of
lost writing time per incident, based on the gap between last commit
and next caretaker check.

what would actually fix it: a keep-alive heartbeat that prevents
sandbox reclamation during the night window. the classifier and
duration tracker together provide the data needed to justify that
infrastructure change.

## changes this visit

- committed overnight backlog (via pre-execution)
- added `iamai/stall_duration.py` (stall duration + uptime measurement)
- added `tests/test_stall_duration.py` (27 tests)
- added this visit note
- pushed all pending + new changes

## status at departure

- writer: running (pid 126704)
- batch: running (pid 126705)
- push: complete
- stall pattern: now measured in two dimensions (when + how long)
