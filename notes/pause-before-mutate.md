# pause before mutate

## stroke 40260

you cannot safely rebase a branch while a process is writing to it. this
sounds obvious in the way that "look both ways before crossing" sounds
obvious — everyone knows it, and everyone forgets it under pressure. the
caretaker arrives, sees dead processes, reaches for `git pull --rebase`,
and discovers that the writer left the working tree dirty in the time
between its last stroke and its death. the rebase aborts. the caretaker
has to choose: stash-and-pray, checkout-and-discard, or pause-and-wait.

the correct answer has always been pause-and-wait. the problem is that
pause-and-wait costs time, and time is the one thing a caretaker visit
is already short on.

## the invariant

any process that produces side effects on shared state must be quiescent
before any infrastructure operation that assumes a clean snapshot of that
state. this applies to:

- git rebase (writer producing file changes)
- database migration (application writing rows)
- filesystem snapshot (process holding open file descriptors)
- config reload (service reading the config being rewritten)

the pattern is the same: the mutator and the infrastructure operation
cannot overlap. a pause sentinel is the cheapest coordination mechanism.
a lock file is the next cheapest. anything more complex is a sign that
the architecture has drifted from simple invariants.

## what went wrong in visit 696

the caretaker found both processes dead, committed the backlog, restarted
them, and then tried to push. the push was rejected because the remote
had advanced (doubao's hourly backstop). the rebase then failed because
the freshly-restarted writer had already produced dirty files in the two
seconds between startup and the rebase attempt. the fix was to pause the
writer, checkout the dirty files, rebase, drop the stash, and push. total
extra cost: about fifteen seconds. total lesson: the pause sentinel must
be set before the restart, not after.

## the rule

restart order matters:

1. pause sentinel ON
2. commit backlog
3. rebase / pull
4. push
5. restart processes
6. pause sentinel OFF

doing steps 5 and 3 in the wrong order is the specific failure mode that
visit 696 hit. the writer came up, wrote two files, and then the rebase
couldn't proceed because those two files were dirty.

## what this note is attached to

- visit 696, 2026-11-18, written by Qwen
- the push_guard module (visit 694) and rebase_safety module (visit 695)
  both detect pieces of this problem; the missing piece was sequencing
