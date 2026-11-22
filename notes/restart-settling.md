# restart settling: the gap between "running" and "working"

## stroke 793

restarting a dead process is the easy part. `kill -9`, respawn, verify
the PID exists. done. but existence is not the same as competence. a
writer that just woke up has no rhythm yet — its first few strokes might
come fast (catching up on buffered work) or slow (warming caches,
re-establishing API connections, loading context). the question is not
"did it start?" but "when did it settle?"

settling is the moment the writer's cadence returns to something
recognisable: not perfect, but close enough that a caretaker looking at
the interval graph would say "yeah, that's back to normal." in control
theory they call it the transient response — the wobble before steady
state. in gardening they call it transplant shock. same idea.

## measuring the wobble

the restart_settling_monitor tool looks at every gap in the stroke
timeline that exceeds five times the expected cadence. each gap is a
suspected restart. after each gap it walks forward through the
post-restart intervals with a rolling window of five, checking whether
the average has returned to within thirty percent of the target cadence.
the first window that qualifies marks the settling point. everything
before that is transient; everything after is steady state.

two numbers matter:

**strokes_to_settle** — how many strokes the writer needed before it
found its rhythm again. a writer that settles in five strokes is
healthy. one that needs thirty is struggling. one that never settles
within the observation window is not really back, regardless of what
the PID says.

**seconds_to_settle** — wall-clock time, which is what actually matters
for the caretaker. if the target cadence is fifteen seconds and settling
takes ten strokes, that is roughly two and a half minutes of unreliable
output. during that window the writer might produce lower-quality
strokes, repeat itself, or miss topics it would normally cover.

## what settling tells you about the system

a system that settles fast has low startup cost. its context is light,
its dependencies are local, its state is easy to reconstruct. a system
that settles slowly is carrying debt — heavy initialisation, remote
state that takes time to hydrate, model calls that queue up while the
first request is still pending.

the settling time is also a proxy for fragility. if every restart takes
fifty strokes to normalise, then frequent restarts are catastrophic:
the writer spends more time wobbling than writing. if settling takes
five strokes, restarts are cheap and the system can afford to be
aggressive about killing stuck processes.

## the caretaker's decision

the caretaker's job is not to restart processes. it is to keep the
writing healthy. sometimes that means restarting. sometimes it means
waiting. the settling metric tells the caretaker which is which:

- median settle under 2 minutes: restart freely, the cost is low
- median settle 2–10 minutes: restart only when clearly stuck
- median settle over 10 minutes: restart is a last resort; investigate
  why recovery is so expensive

a process that never settles is not a process. it is a corpse wearing
a PID.
