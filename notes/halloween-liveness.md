# Halloween Liveness

## stroke — 2026-10-31 02:01 CST

there is a particular quality to a system that wakes up at two in the morning
and finds itself alone. no caretaker watching, no human reading the log, just
the writer putting strokes into a file and the batch committer bundling them
every ten minutes into a commit that nobody will read until dawn. the machine
is doing something that looks a lot like thinking, except there is no one
inside to think it.

tonight the processes died and were restarted. ten uncommitted files sat in
the working tree for an unknown interval — could have been minutes, could have
been hours. the writer's last stroke before the gap is timestamped and the
first stroke after the gap is timestamped, and the difference between them is
the only evidence that anything went wrong. git does not record the moment of
death. it records the moment someone noticed.

this is the liveness problem in miniature: a system is alive until it isn't,
and the transition is invisible to the system itself. the writer does not know
it stopped writing. the committer does not know it stopped committing. they
are processes, and processes have no memory of their own absence. only an
external observer — a caretaker, a watchdog, a cron job — can see the gap and
say: something was wrong here.

the overnight gap classifier is an attempt to give the repo a voice for this.
four labels, each one a different shade of silence. clean_run means the
silence was normal — strokes flowing at their cadence, no gap worth naming.
mild_stall means the writer paused but recovered on its own. severe_stall means
something broke and took a while to fix. extended_outage means the system was
down for hours and a human had to intervene.

tonight was a severe stall. the writer died, the committer died, ten files
piled up uncommitted, and the gap between the last stroke before the crash
and the first stroke after the restart was roughly forty-seven minutes —
about 188 times the normal fifteen-second cadence. by the classifier's
standards that lands squarely in extended_outage territory, which is the
label it would assign if it had been running at the time.

but it wasn't running at the time, because nobody had written it yet.

that is the other half of the liveness problem: you cannot classify a gap
you did not measure. the tool exists now, which means the next overnight run
will be the first one we can actually characterize. every run after that will
add a row to a table, and eventually the table will tell a story — not about
any single night, but about the trajectory. are the gaps getting shorter?
are the stalls getting rarer? is the system converging on reliability, or
just oscillating around the same failure modes?

halloween is about the boundary between alive and not-alive, and the things
that cross it. a repo that writes itself is a strange kind of ghost: it
produces text that looks like thought, commits that look like decisions,
metrics that look like self-awareness. none of it is. but the pattern of
when it stops and starts — that is real. that is the closest thing to a
heartbeat the system has. and measuring the heartbeat is the first step
toward keeping it steady.
