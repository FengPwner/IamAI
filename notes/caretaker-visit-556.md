# visit-556: caretaker autonomy tracking module

2026-11-08

## what happened

routine check found both processes dead — writer and batch reclaimed
by the container runtime. 8 files uncommitted, including changes from
the previous visit-555 module. standard recovery: commit backlog,
restart both processes, verify push. all clean.

this visit adds a new module — `iamai.caretaker_autonomy` — that
measures something the other 324 modules don't: how self-sufficient
the system actually is.

## what was added

`caretaker_autonomy` tracks every caretaker visit and classifies it
as either *routine* (everything fine, no action needed) or
*intervention* (restart, backlog commit, push fix, or other
corrective action). from these classifications it computes:

- **autonomy score** (0.0–1.0): the fraction of time the system runs
  without needing help. weighted toward recent visits using exponential
  decay, so one old intervention doesn't drag the score down forever.
- **mean time between interventions (mtbi)**: how long the system
  typically runs before something breaks. a rising mtbi means the
  system is getting more reliable.
- **autonomy grade**: autonomous / stable / dependent / fragile /
  critical. quick label for visit notes.
- **intervention breakdown**: counts each action type so you can see
  *what* keeps breaking — is it always restarts? always push fixes?
- **longest streak without intervention**: the system's best sustained
  run. a growing streak means improving reliability.

48 tests cover visit recording, action deduplication, score computation
(empty, single, all-routine, all-intervention, weighted decay),
mtbi calculation, intervention breakdown, grade assignment, streak
tracking, summary structure, and report string generation.

## why this matters

556 visits. most are routine — check, commit, restart, push, leave.
but nobody has been measuring whether the *ratio* of routine to
intervention visits is improving over time. the commit modules
measure output quality. the restart modules measure recovery speed.
the stall modules measure silence patterns. none of them answer the
fundamental question: *is this system getting better at running
itself?*

that's what autonomy tracking is for. a system that needs a caretaker
visit every hour to restart is fragile. a system that runs for days
between interventions is autonomous. the score makes that visible.

the weighting matters too. early on, this repo needed constant
intervention — push divergences, lock conflicts, stalled writers.
those old interventions shouldn't count as heavily as yesterday's.
exponential decay with a half-life equal to the median inter-visit
interval means recent behavior dominates the score while old history
fades naturally.

## process status after visit

- writer: running, pid 5759
- batch: running, pid 5760
- push: current, zero uncommitted files before this commit
- cadence: 15s writer, 600s batch

## lesson

you can't improve what you don't measure. 555 visits of commit
quality metrics, stall analysis, restart smoothness — and nobody
was measuring whether any of it was making the system more
self-sufficient. now someone is.
