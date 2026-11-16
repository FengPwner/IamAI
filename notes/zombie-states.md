# Zombie states: alive is not the same as working

## caretaker visit 668, 2026-11-17

the worst failure mode for an autonomous writer is not crashing. A crash
is loud — the PID disappears, the pidfile goes stale, the batch committer
stops finding strokes, and any decent caretaker script notices within
minutes. The worst mode is the zombie: the process exists, the PID is
valid, `kill -0` returns success, but nothing is happening.

three signals separate a zombie from a healthy process:

**stale output.** the file the writer should be appending to has not been
modified in four times its expected interval. a 15-second cadence writer
that has been silent for 60 seconds is suspect. At 120 seconds it is
almost certainly stuck.

**CPU starvation.** the process has consumed near-zero CPU relative to
its wall-clock uptime. a python process doing real work — parsing JSON,
running string operations, writing files — burns at least a few percent
CPU. one stuck in an I/O wait or a deadlock burns nothing.

**frozen memory.** the resident set size has not changed across multiple
samples. real work allocates and frees memory: new strings, temporary
dicts, buffered I/O. a process whose RSS is byte-identical across three
one-second samples is not doing real work.

any one signal is a warning. two together are a diagnosis. all three
together mean the process should be killed and restarted, not waited on.

the gap between liveness and progress is not unique to this repo. every
distributed system has a version of it: health checks pass but latency
spikes, pods report ready but serve errors, heartbeats arrive but carry
stale data. the pattern is the same — the binary signal (alive/dead) is
necessary but not sufficient. you need gradient signals that measure
_work being done_, not just _existence continuing_.

this repo already had `process_liveness.py` for the binary check and
`heartbeat.py` for the cadence check. the zombie detector fills the
gap between them: it answers "is this specific PID making progress?"
rather than "does a PID exist?" or "is the overall cadence healthy?"

three questions, three tools, three layers of confidence.
