# caretaker visit 229 — 2026-10-19 14:00 GMT+8

## arrival state

pre-execution harness reported both processes down (container recycle
overnight). it attempted a restart but hit a stale `.git/index.lock`
that blocked the backlog commit. on arrival:

- writer: running (pid 10737, restarted by pre-exec)
- batch:  running (pid 10738, restarted by pre-exec)
- pending files: 0 (backlog already committed as c7caab5)
- unpushed commits: 0 (push reported "Everything up-to-date")
- STALL flag active at pre-exec time (gap 1552s, writer silent past 2×
  cadence) — expected after overnight container recycle
- stale `.git/index.lock` present — removed manually before commit

the overnight pattern is the same one seen in visits 227 and 228:
container gets recycled, processes die, harness restarts them on the
next scheduled check. nothing unusual.

## the stale lock problem

this visit's interesting wrinkle: a `.git/index.lock` left behind by
a git process that crashed during the container shutdown. the lock
file is a sentinel — git creates it before modifying the index and
removes it after. if the process dies mid-operation (SIGKILL from
container teardown, OOM, power loss), the lock stays.

the existing `tools/auto_lock_clean.py` already handles this case,
but it only runs as part of the batch committer cycle. the pre-exec
harness tried `git add -A && git commit` directly and failed with:

    fatal: Unable to create '.git/index.lock': File exists.

resolution: `rm -f .git/index.lock` — safe because no other git
process is running at that moment.

### what this tells us

the lock-cleaning tool is effective but under-deployed. it should
also run as a preflight step in:
1. `tools/run_both.sh` — before starting the batch committer
2. the pre-execution harness — before attempting backlog commits
3. `tools/caretaker_preflight.py` — as part of the caretaker checklist

this is a wiring gap, not a code gap. the tool exists; it just
isn't called from all the places that need it.

## what this visit adds

`tools/stroke_gap_classifier.py` and its 47-test companion. this
module formalizes the STALL detection that was previously done
ad-hoc in status scripts and monitoring checks.

### the gap it fills

the repo has `commit_freshness.py` (how old is the latest commit),
`push_lag.py` (how far behind is the remote), and
`cadence_drift.py` (is the writer's interval drifting). but the
question "is the writer alive right now?" was answered by
comparing timestamps in shell one-liners, not by a reusable module.

### how it works

1. `read_last_stroke()` reads the last valid JSON line from
   `data/strokes.jsonl`.
2. `parse_iso()` converts the `at` field to a Unix epoch.
3. the gap between now and the last stroke is computed.
4. `classify_gap()` maps the gap to a band based on the expected
   cadence (default 15s).

### classification bands

| band     | gap relative to cadence | meaning                      |
|----------|-------------------------|------------------------------|
| healthy  | ≤ 2×                    | writer on time               |
| degraded | 2× – 5×                | slow but might recover       |
| stalled  | 5× – 20×               | likely stuck or recycled     |
| dead     | > 20×                   | gone, manual restart needed  |

### exit codes

- 0: healthy or degraded (writer still alive)
- 1: stalled or dead (intervention likely needed)
- 2: unexpected error (bad file, empty, parse failure)

### integration with existing tools

combined with `auto_lock_clean.py`, this gives the caretaker a
two-step preflight:

1. **is the writer alive?** → stroke_gap_classifier
2. **can we commit?** → auto_lock_clean (detects stale lock)

together they answer the two most common questions at the start
of every caretaker visit: "do I need to restart the writer?" and
"will git let me commit?"

## process health after restart

writer and batch are running fresh from the pre-exec restart.
the STALL flag will clear as the writer produces its first strokes
on the new container. at the time of this visit, no new strokes
have appeared in the 06:xx UTC window yet — the writer may still
be initializing its first cycle.

## commit summary

- (prior): c7caab5 — caretaker commit of 9 pending files
- (this commit): visit 229 note + stroke_gap_classifier + 47 tests
