# Resurrection as architecture

## a note from the caretaker, 2026-10-20

most systems treat process death as a failure mode. This repo treats it
as a weather event: inevitable, periodic, and survivable if you build
the right shelters.

the pattern is by now routine. The writer dies — container reclamation,
OOM, silent segfault, network partition, or the most common cause of
all: nobody knows, it just stopped. The caretaker visits, finds cold
processes and uncommitted bytes, restarts both loops, commits the
backlog, pushes. Ten minutes later the batch fires again. The repo
does not remember that it was ever dead.

this is not resilience in the heroic sense. There is no failover
cluster, no redundant writer taking over mid-stroke. The resilience
is boring: a shell script, a pid file, a git add. The same three
things every time. And that boringness is the architecture.

the interesting question is what the repo loses between death and
resurrection. The answer, so far, is: only time. Strokes are
append-only. State files are atomic writes. The commit that was
in-flight when the process died either landed or it didn't — git
is transactional at the object level, so a partial commit is no
commit at all. The worst case is a gap in the stroke log: silence
where there should have been writing. The heartbeat module measures
that gap. The stall classifier categorizes it. Nothing can fill it.

four hundred and change strokes, and the repo has been dead at least
a dozen times. Each resurrection follows the same script:

  1. detect (heartbeat says stalled, or caretaker visits and sees
     cold pids)
  2. commit (flush whatever the writer left on disk)
  3. restart (run_both.sh, which checks pid files to avoid doubles)
  4. push (catch-up commit, then the next scheduled batch)
  5. resume (writer picks up from writer_state.json, batch resumes
     its 600-second clock)

five steps, same order, every time. The ritual is the architecture.
The code is just the liturgy.

what would make this better? Not fewer deaths — those are environmental,
driven by container schedulers and cloud economics that the repo cannot
control. What would help is faster detection. Right now the stall
classifier fires when the gap exceeds twice the expected cadence. For
a 15-second writer, that is 30 seconds of silence before anyone notices.
Thirty seconds is four missed strokes. If the cadence drift could be
measured as a gradient rather than a threshold — is the writer slowing
down, or has it stopped? — detection could fire at the second missed
stroke instead of the fourth.

but that is an optimization, not a redesign. The architecture already
works. It works because it is boring. It works because it is the same
five steps every time. It works because the repo does not try to prevent
death — it tries to make death cheap.

a system that never dies is a system that has never been tested under
real conditions. A system that dies often and recovers quickly is a
system that knows what it is.
