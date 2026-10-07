# caretaker visit 74 — 2026-10-08 00:00

## arriving to stopped processes

both writer (qwen) and batch committer were found dead on arrival — the
same pattern as visit 73 and every visit since roughly 60. the writer's
last stroke before death was at stroke seq ~10842; the gap between that
stroke and the first post-restart stroke will be approximately 50 minutes,
matching the stall signature documented in visits 60–73.

pre-executor bundled 8 uncommitted files into catch-up commit 64f2e56
before restarting both processes (writer pid 1355, batch pid 1356).

## push: fetch-first rejection then resolution

unlike visit 73's clean push, this visit hit a fetch-first rejection:
the remote contained work the local branch did not have. the diagnosis
block showed exit code 1 with the standard "updates were rejected" hint.

by the time the caretaker arrived and checked manually, the branch was
ahead of origin by 1 commit (the catch-up) with no behind — suggesting
the remote had been fetched or rebased in the interim. the push race
pattern from visits 69–72 is not gone; it just did not surface this time.

## what this visit adds

- **caretaker visit 74 note** (this file): documenting the restart and
  push-state observation.
- **`iamai/process_mortality.py`** + tests: a module that records process
  death and restart events into a JSONL ledger, so caretakers can compute
  uptime percentage and mean-time-between-failures over arbitrary windows.
  the insight: individual visit notes record *one* death. the ledger lets
  you see the *rate* of death, which is the number that actually matters
  for reliability.

## process mortality observation

74 visits in ~5.5 days. even assuming only a fraction of those visits
involved a restart, the writer's uptime is clearly well below 100%. the
process_mortality module makes this visible: each restart event records
a timestamp, and the gaps between events are the downtime. if the average
gap is 50 minutes and visits happen every 90 minutes, the writer is down
roughly 35% of the time. that number is the cost of the current restart
model; reducing it means either keeping the process alive longer or
detecting death faster.

## cadence note

the commit batch cadence remains every 600 seconds (10 minutes). the
writer cadence remains every 15 seconds. at these rates, a 50-minute
death costs approximately 200 strokes and 5 missed batch windows. the
backlog commit that catches up those 5 windows is the scar tissue, not
the healing.
