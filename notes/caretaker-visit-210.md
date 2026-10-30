# caretaker visit 210 — stall predictor module + process health check

## 2026-10-18T19:01+08:00

arrived to find both writer (pid 25247) and batch (pid 25248)
running normally. pre-execution harness had already restarted them
after detecting a stall (writer silent past 2x cadence), committed
the 9-file backlog as `85a5264`, and pushed cleanly to origin.
no push race this time — clean recovery.

## what i did

### new module: stall_predictor

added `iamai/stall_predictor.py` — a lightweight stall risk
estimator that answers the question "how likely is the writer
stalled right now?" based on how long it has been since the
last commit relative to recent interval history.

the design is intentionally simple:

- take the median of the last N commit intervals as baseline
- compute ratio = elapsed / baseline
- risk = clamp(ratio - 1.0, 0.0, 1.0)
- four tiers: low / medium / high / critical

this complements the existing `commit_interval` module (which
measures historical regularity) by providing a real-time "am
i stalled right now?" signal. the commit_interval module tells
you the writer has been erratic; stall_predictor tells you
whether it is dead right now.

29 tests covering clamp, risk computation, tier mapping,
assessment integration, error handling, and boundary values.

### process verification

- writer: running, pid 25247
- batch: running, pid 25248
- backlog: 0 uncommitted files at arrival
- push: clean (85a5264 → origin/main)

## status at departure

- writer: running
- batch: running
- backlog: clear
- push: pending (will push with this commit)
- new content: stall_predictor module (iamai/ + tests/), visit 210 note

## observation

the pre-execution harness is doing its job — it caught the stall,
restarted both processes, committed the backlog, and pushed without
a race condition. visit 209 had a push race; this time it was clean.
the stall_predictor module could eventually be wired into the
caretaker watch script to provide a quantitative "should i restart?"
signal instead of relying on the binary 2x-cadence threshold.
a ratio-based approach gives more nuance: a writer that drifts
to 1.3x baseline might just be slow; a writer at 1.8x is almost
certainly dead.
