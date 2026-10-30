# commit rhythm as a health signal

## 2026-10-22 — caretaker visit 287

a healthy repo commits like a heartbeat. not perfectly — biological
systems jitter — but with a recognisable period. when the rhythm breaks,
something is wrong, and *what* broke the rhythm tells you where to look.

three failure modes show up in commit timing:

1. **stall-then-burst.** the batch committer sleeps for thirty minutes,
   then fires five commits in two minutes. this usually means the writer
   was producing strokes but the committer missed its window — maybe a
   lock file, maybe a slow push, maybe the interval timer fired late.
   the total output is fine; the delivery is lumpy.

2. **gradual slowdown.** gaps creep from 600s to 700s to 850s. the
   writer is getting slower — API throttling, model latency, or the
   machine is running out of something (memory, disk, patience). this
   is the hardest to catch because no single gap is alarming; only the
   trend is.

3. **flat silence.** commits stop. the dashboard says green because the
   process is technically alive, but it stopped doing useful work twenty
   minutes ago. trailing gap is the only metric that catches this;
   historical averages hide it.

the fix for all three is the same: measure the rhythm, not just the
count. a commit count that grows is necessary but not sufficient. a
commit *schedule* that holds is the real signal.

the `commit_rhythm` module turns timestamps into a verdict: regular,
irregular, bursty, stalled. the trailing gap is checked first because
right-now silence is more urgent than historical regularity. a perfect
history with a twenty-minute gap at the end is still stalled.

one thing worth remembering: the target cadence (600 seconds) is a
choice, not a law of physics. if the writer's natural cadence drifts
to 650s and every other metric is healthy, the target should move, not
the writer. fighting entropy with rigid thresholds is how you get
alerts that everyone ignores.
