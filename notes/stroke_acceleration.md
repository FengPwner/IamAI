# stroke_acceleration — is the writer speeding up or slowing down?

Added 2026-10-23.

The idea: ``cadence_adherence`` measures *consistency* — how regular
are the inter-stroke gaps?  ``stall_classifier`` measures *status* —
is the writer alive right now?  Neither measures *direction*: is
production accelerating, decelerating, or holding pace?

``stroke_acceleration`` fits a linear regression to recent inter-stroke
intervals and reports both a classification and a composite momentum
score.

## Labels

| slope (s/interval)  | reading        |
|---------------------|----------------|
| < -threshold        | accelerating   |
| within ±threshold   | steady         |
| > +threshold        | decelerating   |
| mean > stall × expected | stalled    |

## Momentum score

``momentum = consistency × velocity_ratio``

- **consistency** = 1 − CV (coefficient of variation), clamped to [0,1]
- **velocity_ratio** = expected_cadence / mean_interval, capped at 1.0

A momentum near 1.0 means the writer is on-time and regular.  Near 0.0
means it is either erratic, slow, or both.

## What it fills

The gap between "is the cadence consistent?" (cadence_adherence) and
"is the writer dead?" (stall_classifier).  Acceleration captures
*momentum* — the trend that often precedes a stall or recovery.  A
decelerating writer is still alive but trending toward trouble; an
accelerating writer after a restart is recovering.

## Design decisions

- **Window-based analysis.** Only the most recent *window* intervals
  are used (default 20).  Older history is irrelevant to current
  momentum — the writer could have been restarted, the container
  could have been reclaimed, the network could have changed.

- **Linear slope, not polynomial.** A linear fit is sufficient to
  detect directional trends.  Higher-order fits would overfit noise
  in short windows and add complexity without insight.

- **Stall overrides slope.** When the mean interval exceeds
  ``stall_factor × expected_cadence``, the label is forced to
  "stalled" regardless of slope.  A stalled writer with a negative
  slope (intervals shrinking from very large) is still stalled —
  just recovering slowly.

- **Frozen dataclass.** ``AccelerationResult`` is immutable so that
  caretaker visits and monitors can safely pass results around
  without defensive copies.

## Current reading

At stroke 400, the writer typically runs at ``steady`` with momentum
around 0.85–0.95 during healthy operation.  Post-restart acceleration
phases show ``accelerating`` labels as the writer catches up on lost
time, settling back to ``steady`` within a few minutes.

42 tests covering interval computation, linear regression, CV,
parameter validation, all four labels, window truncation, unsorted
input, edge cases, and summary formatting.
