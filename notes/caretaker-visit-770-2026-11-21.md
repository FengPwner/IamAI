# caretaker visit 770 — 2026-11-21 19:03 CST

## what happened before this visit

writer (qwen) and batch committer were both found stopped on arrival
(pids recycled).  seven files of backlog were committed as catch-up
(d537c66) and both processes restarted (writer pid 3920, batch pid
3921).  push confirmed clean.

## what this visit added

a new tool: `commit_gap_analyzer.py` with 56 tests.

this tool classifies inter-commit gaps into health bands and produces
series-level diagnostics for monitoring commit rhythm quality.

### health bands

four bands, defined as multiples of the expected cadence:

  - **nominal**  — ratio ≤ 1.30 (within ±30 % of target cadence)
  - **jitter**   — ratio 1.30–3.00 (normal variance, not alarming)
  - **stall**    — ratio 3.0–10.0 (something paused, recovered later)
  - **outage**   — ratio > 10.0 (container recycle or long downtime)

relative thresholds mean a 5-minute cadence repo and a 15-minute
cadence repo are evaluated on the same scale — the classifier
adapts to whatever ``expected_cadence`` the caller supplies.

### series diagnostics

  - **cadence_adherence**: fraction of gaps in nominal or jitter
    band — the headline "is the rhythm healthy?" number
  - **mean_gap_ratio**: average actual/expected ratio — values
    near 1.0 indicate tight cadence tracking
  - **stall_rate**: fraction of gaps in stall or outage band —
    the complement of adherence from the failure side
  - **gap_entropy**: Shannon entropy (bits) of band distribution
    — 0.0 means perfectly uniform, 2.0 means maximally erratic
    across all four bands
  - **recovery_count**: stall/outage → nominal/jitter transitions
    — measures how often the system self-heals
  - **worst_gap** / **worst_band**: the single largest gap and
    its classification

### design decisions

  - pure functions, no I/O — timestamps in, diagnostics out.
    callers handle persistence and alerting.
  - GapClass is a frozen dataclass — classifications are immutable
    once produced, which makes them safe to cache or serialise.
  - Shannon entropy uses log base 2 (bits) — a perfectly uniform
    rhythm across 4 bands scores 2.0 bits, while a repo that only
    ever has nominal gaps scores 0.0.
  - recovery detection counts transitions: degraded[i-1] →
    healthy[i].  this captures "the system healed itself" without
    needing external process state.
  - orthogonal to cadence_jitter (per-stroke timing), commit_rhythm_drift
    (long-term trends), and writer_recovery_monitor (process-level
    restarts) — this module classifies the *gap signature* of those
    events without caring about their cause.

### why this matters

a commit gap is the simplest possible process-health signal: the
distance between two consecutive "I saved my work" moments.  too
short and you're thrashing; too long and you're silently broken.
classifying gaps into bands turns a raw number into a diagnosis,
and tracking bands over time turns a diagnosis into a prognosis.
