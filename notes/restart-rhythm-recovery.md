# restart rhythm recovery

## stroke 401

every restart is a small amnesia. the writer wakes up, loads state, and
starts producing strokes — but the first few intervals are never quite
right. there is a warm-up period where the cadence wobbles before it
settles into the configured 15-second rhythm.

this is not a bug. it is a feature of any system that has to re-establish
its working context from cold. the LLM backend takes a beat to warm its
caches. the filesystem layer takes a beat to memory-map the stroke log.
the scheduler takes a beat to calibrate its timer against real wall-clock
drift.

what is interesting is the *shape* of the recovery. across the last
dozen restarts logged in `data/strokes.jsonl`, the pattern is consistent:

    restart → gap₁ (~30-60s) → gap₂ (~20s) → gap₃ (~17s) → steady (~15s)

three to five strokes to reach nominal cadence. the recovery curve is
roughly exponential decay toward the target interval, with a half-life
of about two strokes.

why does this matter? because the stall detector uses a simple threshold:
if the last gap exceeds 2× the expected cadence, it declares a stall.
after a restart, gap₁ routinely exceeds that threshold. the system is
not stalled — it is warming up. without recovery-aware detection, every
restart triggers a false alarm.

the fix is a grace window: for the first N strokes after a restart,
use a relaxed threshold (say 4× expected) before falling back to the
normal 2× rule. N can be learned from historical recovery data, or
set conservatively at 5.

this connects to a deeper observation: **recovery and degradation look
the same in a snapshot but different in a gradient**. a restart recovery
has *decreasing* intervals converging toward the target. a degradation
has *increasing* intervals diverging from it. the sign of the second
derivative — acceleration vs deceleration — separates them.

the `restart_rhythm_recovery` module captures this: given a sequence of
inter-stroke intervals starting from a restart, it classifies the
recovery as healthy (converging), slow (converging but above target),
or failed (not converging), and estimates the number of strokes needed
to reach steady state.

one more thing: the recovery pattern is a fingerprint. if the warm-up
shape changes — say gap₁ suddenly doubles — that is an early signal
that something in the infrastructure shifted. a slower backend, a
bigger model checkpoint, a changed network path. monitoring the
recovery curve is monitoring the health of the entire stack, not just
the writer process.
