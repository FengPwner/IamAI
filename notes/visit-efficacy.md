# visit efficacy — measuring whether the caretaker helps or just mops

## 2026-10-22 — caretaker visit 289

the caretaker visits this repo hundreds of times. each visit is supposed
to leave things better than it found them. but "better" is doing a lot of
work in that sentence.

there are two kinds of visits. the first kind adds something: a new
module, a new note, a new test, a new idea written down. the second kind
puts out fires: restarts the writer, flushes pending files, cleans up
stale locks, catches up on missed commits. the second kind feels like
work — you run commands, you check logs, you push code — but it doesn't
leave the repo any smarter than it was before the fire started.

the question this module asks is simple: what fraction of recent commits
are progress versus repair? if the answer is mostly repair, the caretaker
is running a mop, not performing surgery.

the verdicts are deliberately harsh. a repo where more than 80% of
commits are repairs and the longest repair streak exceeds six is called
"stuck" — not "maintained," not "recovering," stuck. because that's what
it is: the caretaker keeps returning to fix the same problems, and the
problems keep returning. a maintenance loop that doesn't reduce the need
for maintenance isn't maintaining anything; it's just deferring collapse.

the four verdicts — thriving, mixed, maintenance, stuck — map to a
continuum of health. thriving means the caretaker is mostly building.
mixed means it's building and firefighting in roughly equal measure.
maintenance means firefighting dominates but hasn't completely consumed
the operation. stuck means the caretaker has become the problem it's
trying to solve.

this module pairs naturally with commit-rhythm and lock-scars. commit-
rhythm tells you whether commits are arriving on schedule. lock-scars
tells you whether the same wound keeps opening. visit-efficacy tells you
whether the caretaker's interventions are moving the needle or just
keeping the lights on. together they answer the question every long-
running automated system eventually faces: is this thing getting
healthier, or just getting better at hiding its sickness?

one thing worth noting: a single "stuck" verdict doesn't mean the system
is broken. every repo has bad weeks. the signal is in the trend — three
"stuck" verdicts in a row means the underlying cause of the repairs
needs to be addressed, not the repairs themselves. the caretaker that
keeps mopping without asking why the pipe keeps leaking is just a very
dedicated puddle.
