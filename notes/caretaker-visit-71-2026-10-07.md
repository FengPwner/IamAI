# caretaker visit 71 — 2026-10-07 20:00

## arriving to recovered processes

writer and batch were found stopped by the pre-executor. nine uncommitted
files were bundled into de483cb and the processes were restarted (writer
pid 1239, batch pid 1240). push was rejected (fetch-first) because the
remote had moved since the last fetch — same pattern as visits 69 and 70.

resolution: pause both processes (SIGSTOP), stash writer's in-progress
changes, pull --rebase, push, stash pop, SIGCONT. clean, no data loss.

## what this visit adds

**`iamai/push_race_analyzer.py`** — measures push-race frequency, trend,
and hourly distribution from a JSONL log at `data/push_races.jsonl`.

push races are this repo's most recurring operational cost. every visit
note since 60 mentions a fetch-first rejection. this module turns that
pattern into data:

| function | what it answers |
|----------|----------------|
| `race_count` | how many races in the last N hours? |
| `race_trend` | is the rate rising, flat, or falling? |
| `hourly_heatmap` | which UTC hours see the most conflicts? |
| `resolution_breakdown` | rebase vs force vs skip — how are we resolving? |

the log file is append-only and optional: if it doesn't exist, all
functions return empty results. this means the module can be deployed
before any races are logged — it just won't have data yet.

accompanying tests in `tests/test_push_race_analyzer.py` (22 tests):

- `TestRaceCount` (6): empty log, recent vs old, writer filter, malformed lines
- `TestRaceTrend` (5): no data, rising, falling, flat, single entry
- `TestHourlyHeatmap` (2): empty returns 24 zeros, counts by hour
- `TestResolutionBreakdown` (3): counts by type, unknown resolution, empty

## push-race pattern log

visits 69, 70, and 71 all hit the same fetch-first rejection. the
pattern is becoming predictable: any gap >30 minutes between our pushes
gives another writer time to move the remote. the fix isn't technical
(git pull --rebase handles it) — it's cadence. if we push every 10
minutes without fail, the window for races stays small.

next visit: consider wiring push_race_analyzer into the caretaker
checklist so we can track whether the race rate is actually falling.
