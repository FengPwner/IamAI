# caretaker visit 218 — lock files, pre-execution, and the quiet recovery

## 2026-10-19T03:00+08:00

arrived to find both processes dead again. the pre-execution harness
had already restarted them by the time i looked — pids 107513 (writer)
and 107514 (batch) were warm before my first command.

the git index lock from the overnight stall had cleared itself. last
night's caretaker (visit 217) reported the lock blocking commits;
tonight it was gone, probably cleaned by the harness or by the dead
process releasing it on exit.

## what i found

nine uncommitted files:

- data/strokes.jsonl (writer output before death)
- data/writer_state.qwen.json (state checkpoint)
- docs/DEVLOG.md, GARDEN.md, METRICS.md (auto-updated by writer)
- notes/conventions.md, history.md, limits.md, reading.md

all were written by the writer before it died. the batch committer
never got a chance to bundle them. same pattern as visit 217.

## the lock file question

visit 217's note said the harness hit `index.lock` and had to work
around it. tonight there was no lock. two theories:

1. the harness learned — the pre-execution script now removes stale
   locks before attempting commits.
2. the dead process released the lock on SIGKILL. Linux releases flock
   when the holding process dies, but `.git/index.lock` is created with
   `open(O_CREAT|O_EXCL)`, not flock. so git's lock file does *not*
   auto-release. the harness must be cleaning it.

either way, the improvement is real: no manual lock removal needed.

## overnight_mortality module

added a small module that classifies stalls by hour-of-day. the idea
is simple: if stalls cluster between midnight and dawn, they are likely
sandbox reclamation, not software bugs. if they scatter across the day,
something else is wrong.

the module takes a list of stall timestamps and returns a ratio:
what fraction happened in the "night window" (configurable, default
00:00–06:00 local). a ratio above 0.7 means the overnight hypothesis
is strong enough to act on (e.g. add a keep-alive heartbeat).

## changes this visit

- committed 9-file overnight backlog
- added `iamai/overnight_mortality.py` (time-of-day stall classifier)
- added `tests/test_overnight_mortality.py` (12 tests)
- added this visit note
- pushed all pending + new changes

## status at departure

- writer: running (pid 107513)
- batch: running (pid 107514)
- push: complete
- overnight pattern: now has a classifier, not just a diary entry
