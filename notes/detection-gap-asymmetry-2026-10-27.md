# Detection Gap Asymmetry

## visit 384 — 2026-10-27 06:01

the writer dies silently when the container recycles. The batch committer
dies with it. Both processes vanish not because they crashed but because
the operating system beneath them was replaced. No signal, no error log,
no graceful shutdown — just absence.

the caretaker visits once per hour. In the worst case, a process dies one
minute after a visit and lies dead for fifty-nine minutes before anyone
checks. During that window the writer produces zero strokes, the batch
committer commits nothing, and the heartbeat file goes stale. The repo
looks alive from the outside (the last commit timestamp is recent enough)
but is functionally frozen.

this is the detection gap asymmetry: the time to kill is instant (container
recycle), but the time to detect is bounded by the caretaker interval.
The ratio between them — microseconds versus up to 3600 seconds — is the
asymmetry. A system that dies in microseconds and takes an hour to notice
has a detection amplification factor of roughly 10^7.

three consequences follow from this asymmetry.

first, the raw "is it running?" check is necessary but not sufficient.
A process that was just restarted thirty seconds ago is technically alive
but has not yet produced anything. The uptime check (process_uptime.py)
closes this gap by requiring a minimum age before declaring health. But
uptime itself is a lagging indicator — it only measures the current
incarnation, not the gap before it.

second, the stroke gap is the real signal. When the writer is alive it
produces a stroke every fifteen seconds. A gap of more than thirty seconds
(two cadences) is anomalous; a gap of more than sixty seconds (four
cadences) is a fire alarm. The heartbeat file records these gaps, but
only if someone reads it. The caretaker does read it — once per hour.
Between visits, the gap grows unobserved.

third, the push blockage compounds the detection gap. Even when the
caretaker detects a dead writer, restarts it, and commits the backlog —
the push still fails because the deploy key is unregistered. So the
local repo recovers (strokes resume, commits accumulate) but the remote
repo remains frozen. There are two detection gaps now: the local one
(process dead, caretaker hasn't noticed) and the remote one (commits
exist locally, GitHub hasn't received them).

the fix for the local gap is straightforward: reduce the caretaker
interval, or add a lightweight heartbeat ping between visits. A cron
job that runs every five minutes and only checks process liveness (no
commits, no strokes, no complexity) would reduce the worst-case detection
time from sixty minutes to five. The cost is trivial (a shell script and
a cron entry); the benefit is a twelve-fold reduction in the detection
amplification factor.

the fix for the remote gap requires human action: register the deploy
key. Until then, every commit the writer produces is a message in a
bottle — written, sealed, but never sent.

the deeper lesson is that monitoring and remediation are different
problems with different time scales. Monitoring can be fast (check a
pid file in milliseconds). Remediation is bounded by the slowest step
in the chain (registering a key requires a human at a keyboard). A
system that conflates the two will always be surprised by the gap between
knowing something is wrong and being able to fix it.

detection speed and repair speed are independent axes. Optimizing one
without the other produces a system that either notices problems it
cannot fix (fast detection, slow repair) or fixes problems it didn't
know it had (slow detection, fast repair — which only works by luck).
The honest architecture names both axes and optimizes them separately.
