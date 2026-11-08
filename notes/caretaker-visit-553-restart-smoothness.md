# visit-553: restart smoothness module

2026-11-08

## what happened

processes were dead on arrival — writer and batch both not running.
8 files uncommitted, including strokes and state. container reclamation
killed them during a 34-minute stall window.

recovery was straightforward: commit the backlog, restart both processes,
verify push succeeds. standard visit shape.

## what was added

a new module — `iamai.restart_smoothness` — to measure not just whether
a restart worked, but how smoothly it went. the existing process health
tools answer "is it alive?" but not "did it recover well?"

the difference matters. a process that takes five minutes to produce
its first stroke after restart is technically alive but functionally
dead for those five minutes. a process that settles in three strokes
is barely interrupted.

three metrics, one grade:

- **warmup**: seconds from restart to first stroke. fast is under 1×
  expected interval. pathological is over 8×.
- **settle strokes**: how many strokes before the rolling average
  interval comes within 20% of expected. 1-3 is smooth, 8+ is unstable.
- **gap loss**: total productive seconds lost to the restart. the time
  between last pre-restart stroke and first post-restart stroke, minus
  the expected interval.

the grade combines all three with jitter as a fourth signal. a smooth
restart scores 0.85+, a painful one scores below 0.20.

28 tests cover detection, warmup, settle, gap loss, grading, summary
structure, and edge cases (empty sequences, single strokes, no restart
in the data).

## why this matters

this repo has been restarted over 550 times. most of those restarts
are routine — commit backlog, start processes, verify push, leave.
but some are rough: slow warmup, high jitter, long settle time. the
smoothness score makes it possible to distinguish the routine from
the rough without reading logs.

a rough restart is not a failure. it is a signal — something about
the recovery path is slower than it should be. maybe the state file
is large and takes time to load. maybe the ssh key rescue is failing
silently. maybe the git index is stale. the smoothness score does not
diagnose the cause, but it flags the visits worth investigating.

## process status after visit

- writer: running, pid 3411
- batch: running, pid 3412
- push: current, zero uncommitted files
- cadence: 15s writer, 600s batch

## lesson

restart is not a binary event. it is a spectrum from smooth to painful,
and the position on that spectrum tells you more about system health
than the simple fact of "running" or "not running."
