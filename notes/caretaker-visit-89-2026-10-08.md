# Caretaker Visit 89 — 2026-10-08 21:00

## Status

- Writer (pid 1266) and batch committer (pid 1267) **running** on arrival.
- 9 uncommitted files from the previous cycle had already been swept
  by a catch-up commit (`9b1848e`) during the pre-execution restart.
- Git divergence resolved: 5 local catch-up commits collapsed onto
  `origin/main` via hard reset — the writer state snapshots were
  routine and the remote already had guoban's stroke 110.
- Push: successful after rebase alignment.

## New Contribution

Added `iamai.commit_burst_detector` — identifies rapid-fire commit
clusters and classifies them into four verdicts:

| Verdict    | Trigger                                      |
|------------|----------------------------------------------|
| `quiet`    | zero bursts in the observation window        |
| `steady`   | 1–2 short bursts, healthy rhythm             |
| `surging`  | 3+ bursts or a single burst ≥ 5 commits      |
| `panic`    | any burst with mean gap < 5 s (retry loop?)  |

A *burst* is a maximal run of consecutive gaps ≤ threshold (default
30 s). Each burst records its start index, gap sequence, length,
duration, and mean gap.

Companion test suite: **34 tests** covering the Burst dataclass,
detect_bursts (empty, single, leading/trailing bursts, boundary
values, isolated rapid gaps), burst_verdict (all four verdicts,
priority ordering), burst_summary convenience function, and edge
cases (zero gaps, negative gaps, floats, large thresholds).

### Why this module

The existing `commit_velocity` measures momentum (accelerating vs
decelerating) and `cadence_drift` measures rhythm consistency. Neither
answers "are commits clumping into bursts?" — which is the signal
that separates productive flow from a panic retry loop. This module
closes that gap, giving caretakers a way to distinguish healthy surges
from pathological ones at a glance.
