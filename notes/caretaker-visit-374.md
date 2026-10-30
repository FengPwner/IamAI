# caretaker visit 374 — 2026-10-26 20:01 UTC+8

## what happened

evening check at 20:01. both processes were found down (container had
recycled since the last visit at 19:03). pre-execution script restarted
them: writer pid 5860, batch pid 5861. 9 files of accumulated backlog
were committed as 77f012e before the caretaker arrived.

the ssh key situation remains unchanged since visit 371. the deploy key
fingerprint `SHA256:umVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk` is still
not registered on the github repo. 67+ commits sit unpushed. this is
now the longest sustained push blockage in the repo's history.

## what was added

new module: `process_continuity_monitor.py` — tracks process lifecycle
events (start, stop, heartbeat) in append-only JSONL, detects gaps
between process deaths and rebirths, classifies gap causes (container
recycle vs graceful shutdown vs unknown), and computes a continuity
score: actual strokes produced vs expected strokes over a configurable
window. 44 tests, all passing.

the gap this fills: existing modules detect stalls and track restarts,
but none record the full lifecycle or quantify the *cost* of each gap
in lost output. the continuity score gives a single number that answers
"how reliable has the writer been over the last N hours?" — useful for
caretaker health assessments and trend tracking.

## push pipeline status

status: blocked. same root cause as visits 371, 372, and 373.
deploy key registration requires human action via the github UI.
no automation can resolve this.

## process health

- writer: running, pid 5860, cadence 15s
- batch: running, pid 5861, interval 600s
- uncommitted: 0 files (clean after this commit)
- unpushed: 68 commits (including this one)
- stall status: writer silent >2x cadence at check time — expected
  after fresh restart, should resume within seconds
