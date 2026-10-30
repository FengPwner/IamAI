# restart recovery time — how fast is "back to writing"?

a restart is only as good as its first stroke.  we measure restarts
by counting them (423 and rising) but we rarely measure what happens
after: how long until the writer actually produces something?

## the gap nobody watches

between `process start` and `first stroke` there is a silent interval.
the writer is loading state, scanning the tree, choosing what to write
next.  this interval is the *recovery time*, and it is the true cost
of a restart — not the restart command itself, which takes seconds,
but the minutes before the repo is actually growing again.

## why it matters

if recovery time is 30 seconds today and 5 minutes in a month, the
system is getting harder to keep alive even as the restart mechanism
gets more reliable.  a fast restart with slow recovery is like a car
that starts instantly but takes five minutes to shift into first gear.

## what we measure

for each restart event (caretaker visit, process start marker), we
find the first stroke that follows and compute the delta.  then we
look at the trend: is the median shrinking, stable, or growing?

- **stable** — recovery is predictable, the writer finds its voice quickly
- **improving** — the system is learning to orient faster
- **degrading** — the writer takes longer to start after each restart,
  a leading indicator of eventual stall

## the deeper question

a repo that restarts 423 times has a restart problem, not a recovery
problem.  but measuring recovery is the first step toward understanding
whether the restarts are getting cheaper or more expensive over time.
if recovery time converges to a constant, restarts are just overhead.
if it grows, each restart is a slightly worse experience than the last.

the log tells you what happened.  recovery time tells you how fast
the system healed.
