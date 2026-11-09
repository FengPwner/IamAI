"""587 — cadence_drift_compensator: detect and correct writer cadence drift.

the writer targets one stroke every 15 seconds, one commit every 600 seconds.
but "target" and "actual" are different things. over hours, small delays
accumulate: a 15.3s average stroke interval sounds harmless until you realize
it means 72 fewer strokes per day, or a commit that lands at 640s instead of
600s because the writer was waiting on three strokes that each took an extra
second.

this module sits downstream of the heartbeat and monitors the *actual*
cadence over a rolling window. when drift exceeds a threshold, it computes
a compensation factor — how much faster (or slower) the writer should run
to close the gap within a configurable horizon.

the pipeline:

    writer ──► heartbeat timestamps ──► compensator ──► adjusted cadence
                                           │
                                           └── DriftReport: drift detected,
                                               severity, compensation factor

it does NOT change the writer's interval itself. it reports what the
interval *should be* to converge back to the target cadence. the supervisor
or caretaker decides whether to apply the adjustment.

design decisions:

  1. **rolling window, not all-time average.** an all-time average masks
     recent degradation. a 6-hour session might have been perfect for the
     first 5 hours and drifting for the last hour. the rolling window
     (default 100 samples) captures the *current* cadence.

  2. **drift is signed.** positive drift means "slower than target" (gaps
     are longer than expected). negative drift means "faster than target."
     both are reported — running too fast burns through the stroke pool
     and produces lower-quality content.

  3. **compensation is proportional.** a 5% drift gets a 5% correction,
     not a 50% correction. the compensator computes the factor needed to
     close the gap within `horizon_samples` (default 50). this prevents
     oscillation: the writer doesn't alternate between sprinting and
     stalling.

  4. **severity levels.** drift is classified as:
     - "nominal" (within tolerance, default ±5%)
     - "mild" (5-15% drift — worth noting, optional correction)
     - "moderate" (15-30% drift — correction recommended)
     - "severe" (>30% drift — something is wrong, escalate)

  5. **zero dependencies.** stdlib only, same as the rest of the project.

  6. **injectable clock.** pass clock= for deterministic tests.

>>> c = CadenceDriftCompensator(target_interval=15.0, window=5)
>>> for ts in [0.0, 15.0, 30.0, 45.0, 60.0]:  # perfect cadence
...     c.record(ts)
>>> c.report().severity
'nominal'
>>> c2 = CadenceDriftCompensator(target_interval=15.0, window=5)
>>> for ts in [0.0, 16.0, 32.0, 48.0, 64.0]:  # ~6.7% drift
...     c2.record(ts)
>>> r = c2.report()
>>> r.severity
'mild'
>>> 0.9 < r.compensation_factor < 1.0  # slightly faster to compensate
True
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional


# ---------------------------------------------------------------------------
# result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriftReport:
    """snapshot of current cadence drift."""

    target_interval: float
    actual_interval: float
    drift_pct: float
    severity: str  # "nominal" | "mild" | "moderate" | "severe"
    compensation_factor: float  # multiplier for writer interval
    samples: int
    detail: str = ""

    @property
    def is_drifting(self) -> bool:
        return self.severity != "nominal"

    @property
    def drift_direction(self) -> str:
        if abs(self.drift_pct) < 1.0:
            return "stable"
        return "slow" if self.drift_pct > 0 else "fast"

    def __repr__(self) -> str:
        return (
            f"DriftReport(target={self.target_interval:.1f}s, "
            f"actual={self.actual_interval:.1f}s, "
            f"drift={self.drift_pct:+.1f}%, "
            f"severity={self.severity!r}, "
            f"factor={self.compensation_factor:.3f})"
        )


# ---------------------------------------------------------------------------
# severity classification
# ---------------------------------------------------------------------------

_SEVERITY_THRESHOLDS = [
    (5.0, "nominal"),
    (15.0, "mild"),
    (30.0, "moderate"),
]


def _classify(drift_pct: float) -> str:
    """classify drift percentage into severity level."""
    abs_drift = abs(drift_pct)
    for threshold, label in _SEVERITY_THRESHOLDS:
        if abs_drift <= threshold:
            return label
    return "severe"


# ---------------------------------------------------------------------------
# compensator
# ---------------------------------------------------------------------------


class CadenceDriftCompensator:
    """track actual cadence and compute compensation when drift is detected.

    Args:
        target_interval: expected seconds between events (e.g. 15.0 for writer).
        window: number of recent timestamps to keep for analysis.
        horizon_samples: over how many future samples the correction should
            close the gap. larger = gentler correction.
        clock: injectable time source, defaults to time.time.
    """

    def __init__(
        self,
        target_interval: float = 15.0,
        window: int = 100,
        horizon_samples: int = 50,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if target_interval <= 0:
            raise ValueError(f"target_interval must be positive, got {target_interval}")
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if horizon_samples < 1:
            raise ValueError(f"horizon_samples must be >= 1, got {horizon_samples}")

        self.target_interval = target_interval
        self.window = window
        self.horizon_samples = horizon_samples
        self._clock = clock or time.time
        self._timestamps: Deque[float] = deque(maxlen=window)
        self._total_recorded: int = 0
        self._reports: List[DriftReport] = []

    # ------------------------------------------------------------------
    # recording
    # ------------------------------------------------------------------

    def record(self, timestamp: Optional[float] = None) -> int:
        """record an event timestamp. returns the total count recorded."""
        ts = timestamp if timestamp is not None else self._clock()
        self._timestamps.append(ts)
        self._total_recorded += 1
        return self._total_recorded

    def record_now(self) -> int:
        """convenience: record the current time."""
        return self.record()

    @property
    def sample_count(self) -> int:
        return len(self._timestamps)

    @property
    def total_recorded(self) -> int:
        return self._total_recorded

    # ------------------------------------------------------------------
    # analysis
    # ------------------------------------------------------------------

    def _compute_actual_interval(self) -> Optional[float]:
        """compute the average interval from the rolling window."""
        if len(self._timestamps) < 2:
            return None
        ts_list = list(self._timestamps)
        intervals = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        if not intervals:
            return None
        return sum(intervals) / len(intervals)

    def report(self) -> DriftReport:
        """produce a drift report from the current window."""
        actual = self._compute_actual_interval()

        if actual is None:
            return DriftReport(
                target_interval=self.target_interval,
                actual_interval=0.0,
                drift_pct=0.0,
                severity="nominal",
                compensation_factor=1.0,
                samples=len(self._timestamps),
                detail="insufficient data (need >= 2 samples)",
            )

        drift_pct = ((actual - self.target_interval) / self.target_interval) * 100.0
        severity = _classify(drift_pct)

        # compensation factor: how much to multiply the writer interval
        # to close the drift within horizon_samples.
        # if actual is 16s and target is 15s (drift +1s per stroke),
        # we need to recover 1s × horizon_samples total deficit.
        # by adjusting the interval by (drift / horizon_samples),
        # we get: new_interval = target - (drift_per_sample * gain)
        # gain starts gentle and scales with severity.
        drift_per_sample = actual - self.target_interval
        correction = drift_per_sample / self.horizon_samples
        compensated_interval = self.target_interval - correction
        # clamp: never go below 50% or above 200% of target
        min_interval = self.target_interval * 0.5
        max_interval = self.target_interval * 2.0
        compensated_interval = max(min_interval, min(max_interval, compensated_interval))
        compensation_factor = compensated_interval / self.target_interval

        detail = (
            f"window={len(self._timestamps)}, "
            f"total={self._total_recorded}, "
            f"drift_direction={('slow' if drift_pct > 0 else 'fast')}"
        )

        r = DriftReport(
            target_interval=self.target_interval,
            actual_interval=round(actual, 3),
            drift_pct=round(drift_pct, 2),
            severity=severity,
            compensation_factor=round(compensation_factor, 4),
            samples=len(self._timestamps),
            detail=detail,
        )
        self._reports.append(r)
        return r

    def adjusted_interval(self) -> float:
        """return the recommended writer interval based on current drift.

        this is the target_interval × compensation_factor from the latest
        report. if no report has been generated yet, returns target_interval.
        """
        if not self._reports:
            return self.target_interval
        return self.target_interval * self._reports[-1].compensation_factor

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------

    @property
    def history(self) -> List[DriftReport]:
        """all reports generated so far."""
        return list(self._reports)

    def summary(self) -> dict:
        """summary statistics across all reports."""
        if not self._reports:
            return {
                "total_reports": 0,
                "nominal_count": 0,
                "drift_count": 0,
                "max_drift_pct": 0.0,
                "avg_drift_pct": 0.0,
            }
        drifts = [r.drift_pct for r in self._reports]
        return {
            "total_reports": len(self._reports),
            "nominal_count": sum(1 for r in self._reports if r.severity == "nominal"),
            "drift_count": sum(1 for r in self._reports if r.severity != "nominal"),
            "max_drift_pct": max(abs(d) for d in drifts),
            "avg_drift_pct": sum(abs(d) for d in drifts) / len(drifts),
        }

    def reset(self) -> None:
        """clear all timestamps and history."""
        self._timestamps.clear()
        self._reports.clear()
        self._total_recorded = 0
