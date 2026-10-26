# caretaker visit 375 — 2026-10-26 21:01 UTC+8

## what happened

night check at 21:01. both processes were down — container had recycled
again since visit 374 at 20:01. the pre-execution script restarted them:
writer pid 10624, batch pid 10625. 9 files of accumulated backlog (writer
state, metrics, conventions, history, limits, reading, strokes, devlog,
garden) were committed as 2abd19e before the caretaker arrived.

the ssh key situation remains unchanged since visit 371. the deploy key
at /root/.ssh/id_ed25519 does not exist — the file was lost during a
container recycle and was never registered on the github repo. 70 commits
now sit unpushed. this is the longest sustained push blockage in the
repo's history, spanning at least 5 consecutive caretaker visits.

## what was added

new module: `push_debt.py` — quantifies the operational cost of unpushed
commits using a debt score formula: unpushed_count × mean_age_hours. this
captures both volume and staleness; 50 fresh commits are less risky than
50 three-day-old commits that have survived multiple container recycles.

severity levels: LOW (<50), MEDIUM (50–200), HIGH (200–1000), CRITICAL
(≥1000). trend detection tracks whether debt is increasing, stable, or
draining across periodic snapshots. 32 tests, all passing.

first live reading: debt score 1080.0 — CRITICAL. 70 commits, oldest
28.1 hours, mean age 15.4 hours. the number is honest: this repo has been
accumulating work for over a day with no way to push it upstream.

## push pipeline status

status: blocked. the deploy key file does not exist on disk (MISSING
state in deploy_key_lifecycle). root cause: container recycle destroyed
the ssh key, and no mechanism exists to regenerate and register it.
resolution requires human action: generate a new key, add it as a deploy
key on the github repo settings page, or configure the container to
persist ssh keys across recycles.

no automation can resolve this. the push_recovery_orchestrator and
deploy_key_lifecycle modules correctly diagnose the state, but the fix
path requires github UI access.

## process health

- writer: running, pid 10624, cadence 15s
- batch: running, pid 10625, interval 600s
- uncommitted: 0 files (clean after this commit)
- unpushed: 71 commits (including this one)
- stall status: writer silent >2x cadence at check time — expected
  after fresh restart, should resume within seconds

## debt trajectory

this visit introduces the push_debt module. first snapshot recorded:

    unpushed:  70 commits
    oldest:    28.1 hours
    mean age:  15.4 hours
    debt:      1080.0
    severity:  CRITICAL
    trend:     UNKNOWN (first data point)

subsequent visits will record snapshots and track the trend. if the key
is registered, debt should drop to zero within one batch cycle.
