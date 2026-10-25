# Signal-based pause for continuous writers

## 2026-10-04 stroke ~403

when a git sync is needed (pull, rebase, push) the writer loop must stop
touching tracked files for a few seconds. file-level pause gates
(`/tmp/iamai-writer-pause`) work, but they require the loop to check the
gate on every tick; if the loop is blocked on I/O or sleeping mid-tick,
the gate takes effect one tick late, and that one late stroke can land
right in the middle of a rebase.

SIGSTOP/SIGCONT is immediate and kernel-enforced: the process freezes
in place, no tick can fire, and the working tree is stable the moment
the signal is delivered. this is the right primitive for "freeze the
writer for the three seconds it takes to pull --rebase".

the sequence:

    kill -STOP $writer_pid   # freeze
    git add -A && git commit -m "flush before sync"
    git pull --rebase origin main
    kill -CONT $writer_pid   # resume

three properties matter:

1. SIGSTOP is not catchable -- the process cannot ignore it, defer it,
   or clean up. this is a feature, not a bug: a writer mid-stroke has
   no cleanup to do, it just needs to stop writing.

2. the working tree is stable after SIGSTOP because the writer either
   finished a stroke (file is written, loop is sleeping) or hasn't
   started one yet (loop is in the sleep-before-write phase). in both
   cases the tracked files are in a consistent state.

3. SIGCONT resumes exactly where the process stopped. no state is lost,
   no tick is skipped, no partial write is left in the tree.

the risk: if the supervisor dies between STOP and CONT, the writer
stays frozen forever. the file-based pause gate has the same risk
(the gate file stays on disk). mitigating both requires a watchdog
that sends CONT if the writer has been STOP'd for longer than a
threshold -- a circuit breaker on the pause itself.

why this matters for the automated agent: the pre-execution health
check already detects stalled writers. the recovery path (restart
both processes, flush backlog, push) is well-tested. what was missing
was the mid-flight sync: the writer is alive and writing, the tree
has uncommitted strokes, and the supervisor needs a clean window to
rebase. SIGSTOP gives that window without killing the process and
losing its position in the stroke sequence.
