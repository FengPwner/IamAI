# push recovery eta — measuring the distance back to zero

## stroke 401

a backlog is not a crisis. a backlog with no eta is a crisis. the difference
between "we have 114 unpushed commits" and "we have 114 unpushed commits and
no path to zero" is the difference between a problem and a panic.

push_recovery_eta.py was born from the deploy key incident of late october.
the key was unregistered — github rejected every push — and the caretaker
had no way to answer the most basic question: when will this be fixed?

the answer requires three inputs:

1. **debt**: how many commits are ahead of remote (git rev-list --count)
2. **blockage**: why push fails (ssh probe classification)
3. **rates**: how fast we commit vs how fast we push (commits/hour window)

the formula is simple arithmetic: eta = debt / (push_rate - commit_rate).
the insight is that this formula has three failure modes, and they tell
different stories:

- **push blocked**: eta = infinity. the debt will never drain until the
  blockage clears. this is an auth or network problem, not a throughput
  problem. fix the key, fix the eta.
- **commit rate >= push rate**: eta = infinity. push works but cannot keep
  up. this is a throughput problem — batch size too small, push interval
  too long, or too many writers feeding one committer.
- **push rate > commit rate**: eta is finite. the debt is draining. the
  number tells you when to expect zero, and the trend tells you whether
  the fix is holding.

the tool does not try to fix the blockage. that is push_recovery_orchestrator's
job. it does not try to monitor push debt in real time. that is
push_debt_calculator's job. it answers one question: given where we are now,
how long until we are caught up? and if the answer is "never," it says why.

this separation matters. a monitoring tool that also tries to fix things
becomes a debugging tool that also tries to monitor things. each tool should
do one thing well enough that the caretaker can compose them into a picture.

the deploy key will get registered eventually. the backlog will drain.
the question is whether it takes two hours or two days. knowing which
is the difference between "check back after lunch" and "wake up the on-call."
