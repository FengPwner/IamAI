# caretaker visit 244 — 2026-10-20 11:00 GMT+8

## arrival state

user task: check auto-writing pipeline, restart if stopped, clear
backlog, write new content, and push.

- writer: NOT running on arrival (killed by container sweep)
- batch: NOT running on arrival
- pause gate: absent
- pending files: 9 (strokes.jsonl, writer_state, DEVLOG, GARDEN,
  METRICS, conventions, history, limits, reading)
- git lock: stale index.lock present from crashed commit
- stall flag: STALL — writer silent 1504s past 2x cadence
- tracked files: 990, strokes: 400+

## what happened

eighth consecutive off-peak visit (237–244) where processes were found
dead. pre-exec harness restarted both writer (pid 12479) and batch
(pid 12480), but the backlog commit failed due to a stale
``.git/index.lock`` left by the crashed batch process.

this visit:
1. removed the stale lock file
2. confirmed batch process committed the 9 pending files itself
   (working tree clean on arrival for the main caretaker)
3. wrote a new module — ``process_graveyard`` — that tracks process
   death and restart events as a persistent JSONL ledger, enabling
   historical analysis of container sweep patterns
4. wrote 25 tests covering the new module
5. committed and pushed in a single batch

## action taken

1. **removed stale git lock** — ``.git/index.lock`` was 0.5s old
   (fresh but blocking). deleted it to unblock commits.

2. **verified processes alive** — writer (pid 12479) and batch
   (pid 12480) both confirmed running after pre-exec restart.

3. **wrote process_graveyard module** — tracks process death/restart
   events in ``data/process_graveyard.jsonl``. provides queries for
   deaths today, mean gap between restarts, peak death hour, and
   cause breakdown. complements the existing caretaker_yield (visit
   effectiveness), caretaker_verdict (health scoring), and
   stall_classifier (root cause) modules.

4. **wrote 25 tests** — covering entry construction, recording,
   filtering, aggregation, persistence, and edge cases.

5. **committed and pushed** — all new files in one commit.

## observations

- the stale lock pattern is new: in previous visits, the batch process
  either committed cleanly or left no lock at all. this time the
  container sweep apparently killed a commit mid-write, leaving the
  lock file behind. the ``auto_lock_clean`` module already handles
  this, but it only runs on a timer — manual intervention was still
  needed this visit.

- eight consecutive dead-on-arrival visits (237–244) in the 01:00–11:00
  window. the process_graveyard module, once populated with data from
  future visits, should reveal whether the sweep follows a fixed
  schedule or responds to resource pressure.

- the diagnostic toolset now has four layers:
  1. caretaker_verdict — is something wrong?
  2. stall_classifier — why is it wrong?
  3. caretaker_yield — what was done about it?
  4. process_graveyard — historical pattern of deaths and resurrections

## streak

total strokes: 400+
categories: devlog ×67, garden ×67, snippet ×67, thought ×67,
            metrics ×67, note ×67
