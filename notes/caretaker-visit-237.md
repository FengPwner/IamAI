# caretaker visit 237 — 2026-10-20 00:00 GMT+8

## arrival state

pre-execution harness reported both processes down. writer had gone
silent past 2x its cadence (gap 2445s, longest historical gap 1587s).
batch committer also not running. 9 files uncommitted from the stall
window. one unpushed commit sitting in the local branch.

- writer: NOT running
- batch: NOT running
- pause gate: absent
- pending files: 9 (data/strokes.jsonl, writer_state, docs/*, notes/*)
- unpushed commits: 1 (from earlier catch-up)
- stall flag: STALL (writer silent past 2x cadence)

## what happened

the writer and batch processes were both dead on arrival — likely
recycled by the container runtime during a resource sweep or OOM
event. the git index had a stale lock file preventing the backlog
commit from going through.

after clearing the lock and restarting via `tools/run_both.sh`, both
processes came up cleanly. the 9-file backlog was committed in a
single catch-up commit.

## action taken

1. **cleared stale git lock** — `.git/index.lock` was present but
   no git process was actually running. removed it.
2. **restarted both processes** — `tools/run_both.sh` launched writer
   (pid 25316) and batch committer (pid 25317) successfully.
3. **committed 9-file backlog** — all accumulated changes from the
   stall period bundled into one catch-up commit.
4. **pushed** — `git push` reported "Everything up-to-date" (the
   unpushed commit had already been pushed by a previous run, or the
   remote was ahead).
5. **wrote new content** — `recovery_latency` module + 20 tests +
   CLI tool, measuring stall-to-recovery duration.
6. **committed and pushed** this visit's changes.

## new tool: recovery_latency

### the problem

stall detection tells you *that* the system is down. recovery latency
tells you *how long* it was down and whether it came back. this metric
matters for two reasons:

1. **capacity planning.** if stalls average 30 minutes but the caretaker
   only visits every 60 minutes, half the stall time is wasted. the
   recovery latency distribution tells you how often to visit.

2. **gating cost.** the red gate (visit 236) is a conservative safety
   mechanism. when it latches unnecessarily, the system is "stalled"
   even though nothing is actually broken. recovery latency quantifies
   the cost of that conservatism.

### what the tool does

`iamai.recovery_latency` scans strokes.jsonl and identifies all gaps
exceeding `cadence * stall_multiplier` (default: 10x, so 150s for a
15-second cadence). for each gap, it records:

- the last stroke before the gap (stall onset)
- the first stroke after the gap (recovery time)
- the duration (recovery latency)

if the last stroke in the log is too old, the system is flagged as
currently stalled and the latency is measured against the current time.

### test suite

20 tests in `tests/test_recovery_latency.py` covering:
- empty/missing strokes file
- healthy system (no stalls)
- currently stalled (last stroke too old)
- recovered stall (gap in history, system healthy now)
- multiple stall events
- longest gap tracking
- malformed timestamp handling
- stall threshold tuning
- report output format

### integration path

- caretaker_watch.sh: log recovery latency on each visit
- metric: track P50/P95/P99 recovery latency over rolling 7-day window
- alert: if P95 exceeds caretaker visit interval, visits are too infrequent
- correlation: cross-reference with red gate events (visit 236) to
  separate "real stalls" from "gate-induced stalls"

## commit summary

- (backlog): 9 pending files committed
- (this commit): recovery_latency.py + 20 tests + CLI tool + visit 237 note
