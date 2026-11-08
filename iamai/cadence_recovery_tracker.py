"""cadence_recovery_tracker — measure how fast cadence recovers after a disruption.

A disruption is any gap in the stroke stream that exceeds a configurable
threshold (default: 4x the expected cadence).  After each disruption,
the tracker measures:

- **recovery_time_s** — seconds from the disruption end to the point
  where the rolling mean inter-stroke gap falls back within tolerance
  of the expected cadence.
- **overshoot_count** — number of strokes produced during recovery
  that are *faster* than expected (the writer "catching up").
- **settle_strokes** — total strokes emitted before cadence stabilised.
- **recovery_verdict** — one of: *instant*, *smooth*, *slow*, *stuck*.

Public API::

    from iamai.cadence_recovery_tracker import (
        CadenceRecoveryTracker, recovery_report,
    )

    crt = CadenceRecoveryTracker(
        stroke_times=[t0, t1, t2, ...],   # ascending unix timestamps
        expected_cadence=15,                 # seconds between strokes
        disruption_threshold=4.0,           # multiples of cadence
        settle_window=5,                     # consecutive good gaps needed
        tolerance=0.30,                      # ±30% of cadence = "good"
    )
    s = crt.summary()
    # {"disruptions": 3, "mean_recovery_s": 45.2,
    #  "mean_settle_strokes": 3.0, "worst_verdict": "slow"}

    print(recovery_report(stroke_times, expected_cadence=15))
    # "3 disruptions, avg recovery 45s (3 strokes), worst: slow"

Recovery model
--------------

After a disruption ends (the first post-gap stroke appears), the
tracker examines each subsequent inter-stroke gap:

- A gap within ``expected_cadence ± tolerance`` is **settled**.
- A gap shorter than ``expected_cadence * (1 - tolerance)`` is **rushed**
  (the writer is catching up — common after restarts).
- A gap longer than ``expected_cadence * (1 + tolerance)`` is **lagging**
  (the writer hasn't found its rhythm yet).

Recovery is complete when ``settle_window`` consecutive settled gaps
are observed.  The time from disruption end to the last of those
settled gaps is ``recovery_time_s``.

==================  ========================================================
recovery_time_s     verdict
==================  ========================================================
< cadence × 2       instant — barely noticed
< cadence × 5       smooth — normal warm-up
< cadence × 15      slow — something was off
≥ cadence × 15      stuck — the writer never really recovered
==================  ========================================================

Why this matters
----------------

Restart smoothness tells you if the handoff was clean.
Cadence adherence tells you the overall rhythm quality.
Neither tells you *how fast the writer found its groove* after a
specific disruption.  This module fills that gap, making it possible
to compare recovery quality across different restart strategies,
deploy patterns, or infrastructure changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Verdict thresholds (as multiples of expected_cadence)
# ---------------------------------------------------------------------------

_VERDICT_TABLE = [
    (2.0, "instant"),
    (5.0, "smooth"),
    (15.0, "slow"),
]

_VERDICT_WORST = "stuck"

_VERDICT_RANK = {"instant": 0, "smooth": 1, "slow": 2, "stuck": 3}


def _classify(recovery_time_s: float, expected_cadence: float) -> str:
    if expected_cadence <= 0:
        return _VERDICT_WORST
    ratio = recovery_time_s / expected_cadence
    for ceiling, label in _VERDICT_TABLE:
        if ratio < ceiling:
            return label
    return _VERDICT_WORST


# ---------------------------------------------------------------------------
# Single disruption record
# ---------------------------------------------------------------------------


@dataclass
class DisruptionRecovery:
    """Record of one disruption and its recovery."""

    gap_start: float          # timestamp of last stroke before gap
    gap_end: float            # timestamp of first stroke after gap
    gap_s: float              # duration of the gap in seconds
    recovery_time_s: float    # seconds from gap_end to settled state
    settle_strokes: int       # strokes emitted before cadence stabilised
    overshoot_count: int      # rushed strokes during recovery
    verdict: str              # instant / smooth / slow / stuck


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


@dataclass
class CadenceRecoveryTracker:
    """Analyse stroke timestamps for post-disruption recovery quality."""

    stroke_times: List[float]
    expected_cadence: float = 15.0
    disruption_threshold: float = 4.0   # multiples of expected_cadence
    settle_window: int = 5              # consecutive good gaps to declare settled
    tolerance: float = 0.30             # ±30% of cadence = "good"

    _recoveries: List[DisruptionRecovery] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.stroke_times = sorted(self.stroke_times)
        self._recoveries = self._analyse()

    # -- analysis -----------------------------------------------------------

    def _analyse(self) -> List[DisruptionRecovery]:
        """Find disruptions and measure recovery for each."""
        if len(self.stroke_times) < 2:
            return []

        threshold_s = self.expected_cadence * self.disruption_threshold
        good_lo = self.expected_cadence * (1 - self.tolerance)
        good_hi = self.expected_cadence * (1 + self.tolerance)

        recoveries: List[DisruptionRecovery] = []

        for i in range(1, len(self.stroke_times)):
            gap = self.stroke_times[i] - self.stroke_times[i - 1]
            if gap < threshold_s:
                continue

            # --- disruption found at index i ---
            gap_start = self.stroke_times[i - 1]
            gap_end = self.stroke_times[i]

            # walk forward from i to find settle_window consecutive good gaps
            consecutive_good = 0
            overshoot = 0
            settle_idx = i
            recovery_done = False

            for j in range(i, len(self.stroke_times)):
                if j == i:
                    # first gap after disruption is the disruption gap itself
                    # start measuring from the *next* gap
                    consecutive_good = 0
                    continue

                g = self.stroke_times[j] - self.stroke_times[j - 1]

                if good_lo <= g <= good_hi:
                    consecutive_good += 1
                elif g < good_lo:
                    # rushed — catching up
                    overshoot += 1
                    consecutive_good = 0
                else:
                    # still lagging
                    consecutive_good = 0

                settle_idx = j

                if consecutive_good >= self.settle_window:
                    recovery_done = True
                    break

            # compute recovery time
            if recovery_done:
                recovery_time_s = (
                    self.stroke_times[settle_idx] - gap_end
                )
            else:
                # never settled — use time to last available stroke
                recovery_time_s = (
                    self.stroke_times[-1] - gap_end
                    if settle_idx > i
                    else float("inf")
                )

            settle_strokes = settle_idx - i if settle_idx > i else 0

            verdict = (
                _classify(recovery_time_s, self.expected_cadence)
                if recovery_done
                else "stuck"
            )

            recoveries.append(
                DisruptionRecovery(
                    gap_start=gap_start,
                    gap_end=gap_end,
                    gap_s=gap,
                    recovery_time_s=recovery_time_s,
                    settle_strokes=settle_strokes,
                    overshoot_count=overshoot,
                    verdict=verdict,
                )
            )

        return recoveries

    # -- public API ---------------------------------------------------------

    @property
    def disruptions(self) -> List[DisruptionRecovery]:
        """List of all detected disruptions and their recovery data."""
        return list(self._recoveries)

    @property
    def disruption_count(self) -> int:
        """Total number of disruptions detected."""
        return len(self._recoveries)

    @property
    def mean_recovery_s(self) -> float:
        """Mean recovery time across all disruptions (inf if any stuck)."""
        if not self._recoveries:
            return 0.0
        times = [r.recovery_time_s for r in self._recoveries]
        if any(t == float("inf") for t in times):
            return float("inf")
        return sum(times) / len(times)

    @property
    def median_recovery_s(self) -> float:
        """Median recovery time (ignores inf for stuck disruptions)."""
        finite = [
            r.recovery_time_s
            for r in self._recoveries
            if r.recovery_time_s != float("inf")
        ]
        if not finite:
            return float("inf")
        finite.sort()
        n = len(finite)
        mid = n // 2
        if n % 2 == 0:
            return (finite[mid - 1] + finite[mid]) / 2
        return finite[mid]

    @property
    def mean_settle_strokes(self) -> float:
        """Mean strokes needed to settle after a disruption."""
        if not self._recoveries:
            return 0.0
        return sum(r.settle_strokes for r in self._recoveries) / len(
            self._recoveries
        )

    @property
    def total_overshoot(self) -> int:
        """Total rushed (overshoot) strokes across all recoveries."""
        return sum(r.overshoot_count for r in self._recoveries)

    @property
    def worst_verdict(self) -> str:
        """Worst recovery verdict across all disruptions."""
        if not self._recoveries:
            return "instant"
        return max(
            (r.verdict for r in self._recoveries),
            key=lambda v: _VERDICT_RANK.get(v, 99),
        )

    @property
    def best_verdict(self) -> str:
        """Best recovery verdict across all disruptions."""
        if not self._recoveries:
            return "instant"
        return min(
            (r.verdict for r in self._recoveries),
            key=lambda v: _VERDICT_RANK.get(v, 99),
        )

    def summary(self) -> dict:
        """Return a dict with all key metrics."""
        return {
            "disruptions": self.disruption_count,
            "mean_recovery_s": round(self.mean_recovery_s, 2)
            if self.mean_recovery_s != float("inf")
            else None,
            "median_recovery_s": round(self.median_recovery_s, 2)
            if self.median_recovery_s != float("inf")
            else None,
            "mean_settle_strokes": round(self.mean_settle_strokes, 1),
            "total_overshoot": self.total_overshoot,
            "worst_verdict": self.worst_verdict,
            "best_verdict": self.best_verdict,
        }


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def recovery_report(
    stroke_times: Sequence[float],
    expected_cadence: float = 15.0,
    disruption_threshold: float = 4.0,
    settle_window: int = 5,
    tolerance: float = 0.30,
) -> str:
    """One-line human-readable recovery summary."""
    crt = CadenceRecoveryTracker(
        stroke_times=list(stroke_times),
        expected_cadence=expected_cadence,
        disruption_threshold=disruption_threshold,
        settle_window=settle_window,
        tolerance=tolerance,
    )
    s = crt.summary()
    if s["disruptions"] == 0:
        return "no disruptions detected — nothing to recover from"
    avg = (
        f"{s['mean_recovery_s']:.0f}s"
        if s["mean_recovery_s"] is not None
        else "∞"
    )
    strokes = f"{s['mean_settle_strokes']:.0f}"
    return (
        f"{s['disruptions']} disruptions, "
        f"avg recovery {avg} ({strokes} strokes), "
        f"worst: {s['worst_verdict']}"
    )
