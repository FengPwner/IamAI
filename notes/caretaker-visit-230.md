# caretaker visit 230 — 2026-10-19 16:00 GMT+8

## arrival state

pre-execution harness reported both processes running (writer pid 5884,
batch pid 5885) but flagged a STALL: writer silent for 834s, longest
gap 1612s. on arrival:

- writer: running (pid 5884) but behind a RED GATE (pause file present)
- batch:  running (pid 5885)
- pending files: 9 (data/strokes.jsonl, writer_state, DEVLOG, GARDEN,
  METRICS, conventions, history, limits, reading)
- unpushed commits: 1 (bc7711b catch-up commit from pre-exec harness)
- last stroke: seq 22425 at 07:45 UTC — 15 minutes of silence

## what happened

the pause gate (`/tmp/iamai-writer-pause-qwen`) was set at approximately
15:46 CST. the writer loop checks this file every tick and idles when it
exists — by design, the batch committer sets the gate when tests fail
and clears it when they pass again. but in this case the gate stayed
red even though the preflight check was passing (5/5 ok).

most likely cause: the batch committer's `except` clause in the watch
loop touches PAUSE on any unhandled exception. a transient error
(network timeout during push, or a race with the pre-exec harness's
git operations) could have set the gate without a corresponding test
failure. once set, no automatic mechanism clears it — the batch
process only checks `gate()` at the top of its cycle and would clear
it if tests pass, but if the batch itself is the one that crashed and
restarted, the new instance inherits a gate set by the old one.

### the stuck gate pattern

this is a different failure mode from visits 227-229 (container
recycle kills processes, harness restarts them). here the processes
never died — they were running the whole time. the writer just sat
idle behind a gate that nobody cleared.

timeline:
- 15:46: pause gate set (by batch committer exception handler)
- 15:46–16:02: writer idling, producing no strokes, 16 minutes lost
- 16:02: caretaker removes gate, processes restart with new PIDs
  (40506/40507), first stroke 22427 produced immediately

## resolution

1. removed `/tmp/iamai-writer-pause-qwen` — writer resumed immediately
2. batch committer had already committed the 9 pending files as f5dc6d7
3. pushed to origin (was already up-to-date from batch cycle)
4. wired `auto_lock_clean.py --dry-run` into `run_both.sh` as a
   preflight check before starting processes (the gap identified in
   visit 229)

## the wiring fix

visit 229 noted that `auto_lock_clean.py` exists but isn't called from
all the places that need it. the `start` case in `run_both.sh` already
clears the stop file and pause gate, but never checked for stale git
locks. now it runs a dry-run check and a clean step as preflight:

    # preflight: stale lock cleanup
    python3 tools/auto_lock_clean.py --threshold 120 2>/dev/null || true

this is a belt-and-suspenders addition. the batch committer already
calls auto_lock_clean in its cycle, but if the batch itself crashes
and leaves a lock behind, the next `run_both.sh start` needs to clean
it before the new batch can commit.

## what's still missing

there's no automatic stuck-gate detector. the writer will idle forever
behind a red gate that was set by a transient error. possible fix for
a future visit: a watchdog that checks "gate is red but tests pass"
and auto-clears it. this would live alongside `stroke_gap_monitor.py`
and `deadman_switch.py` in the monitoring toolchain.

## process health after restart

writer pid 40506 and batch pid 40507 are running fresh. first stroke
(22427, metrics) appeared within 30 seconds of gate removal. cadence
is back to normal ~15s intervals.

## commit summary

- f5dc6d7: batch committer auto-committed 9 pending files
- (this commit): visit 230 note + run_both.sh preflight wiring
