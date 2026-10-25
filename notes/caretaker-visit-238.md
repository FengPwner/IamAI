# caretaker visit 238 — 2026-10-20 03:00 GMT+8

## arrival state

pre-execution harness reported both processes down. writer had gone
silent past 2x its cadence (gap 4731s, longest historical gap 2483s).
batch committer also not running. 9 files uncommitted from the stall
window. one unpushed commit sitting in the local branch.

- writer: NOT running
- batch: NOT running
- pause gate: absent
- pending files: 9 (data/strokes.jsonl, writer_state, docs/*, notes/*)
- unpushed commits: 1 (from earlier catch-up)
- stall flag: STALL (writer silent past 2x cadence)
- stale lock: `.git/index.lock` present, blocking backlog commit

## what happened

identical pattern to visit 237: both processes dead on arrival,
likely recycled by the container runtime during a resource sweep.
the stale `.git/index.lock` file had persisted from the previous
stall period and blocked the backlog commit in the pre-exec harness.

after clearing the lock and restarting via `tools/run_both.sh`, both
processes came up cleanly (writer pid 83398, batch pid 83399). the
9-file backlog was already committed by the pre-exec harness once the
lock was cleared.

## action taken

1. **cleared stale git lock** — `.git/index.lock` was present but
   no git process was actually running. removed it.
2. **verified processes running** — writer (pid 83398) and batch
   committer (pid 83399) both up after `tools/run_both.sh`.
3. **confirmed backlog committed** — pre-exec harness had already
   committed the 9 pending files once the lock was cleared.
4. **pushed** — `git push` reported "Everything up-to-date".
5. **wrote new content** — `lock_clearance` module + 42 tests,
   tracking lock clearance events as a bounded ledger.
6. **committed and pushed** this visit's changes.

## new tool: lock_clearance

### the problem

the repo has excellent lock *detection* (`index_lock_detector`) and
lock *recovery* (`lock_recovery`) but no way to measure how often
locks recur or how well the clearance process works. this matters
because:

1. **pattern recognition.** a lock that appears once a week is a
   nuisance. a lock that appears every hour is a bug. the clearance
   ledger distinguishes the two.

2. **recovery quality.** clearing a lock that immediately reappears
   is not recovery — it's a loop. `recurrence_risk` quantifies this.

3. **backlog correlation.** locks don't just block git; they cause
   backlog to accumulate. tracking backlog size per clearance event
   reveals the cascading cost.

### what the tool does

`iamai.lock_clearance` provides a `LockClearanceLedger` — a bounded
deque (default 100 events) that records each clearance with:

- timestamp and lock age (how long it persisted)
- recovered flag (did git work after?)
- method (auto / manual / caretaker / timeout)
- backlog count (uncommitted files at clearance time)

from these events, the ledger derives:

- `clearance_rate`: clearances per 24h (rolling)
- `mean_lock_age`: average lock persistence before clearance
- `recovery_rate`: fraction of clearances that succeeded
- `recurrence_risk`: probability of re-lock within 1 hour
- `classify()`: clean / recurring / brittle

### test suite

42 tests in `tests/test_lock_clearance.py` covering:
- dataclass construction, frozen property, defaults
- ledger recording, bounded history, chronological ordering
- clearance_rate with custom windows and boundary conditions
- mean_lock_age averaging
- recovery_rate: empty (vacuously 1.0), all-recovered, all-failed, mixed
- recurrence_risk: single event, within/outside window, mixed pairs
- method_breakdown sorting
- total_backlog summation
- classification thresholds: clean, recurring, brittle
- report() dict structure for empty and populated ledgers
- clearance_summary() one-liner formatting

### integration path

- caretaker_watch.sh: log clearance event on each visit that finds a lock
- metric: track clearance_rate and recurrence_risk over rolling 7-day window
- alert: if classification flips to "brittle", escalate to root cause analysis
- correlation: cross-reference with restart_ledger events to separate
  "lock caused by crash" from "lock caused by concurrent git operations"

## observations

this is the second consecutive visit (237, 238) with the same pattern:
both processes dead, stale lock, 9-file backlog. the container runtime
appears to be recycling on a predictable schedule. the lock file is a
side effect — the writer holds no open file descriptors when killed,
but git may have been mid-operation when the kill signal arrived.

worth monitoring: if visit 239 shows the same pattern, consider adding
a pre-shutdown hook that commits pending work and releases locks before
the container is reclaimed.

## commit summary

- (backlog): 9 pending files committed (by pre-exec harness)
- (this commit): lock_clearance.py + 42 tests + visit 238 note
