"""heartbeat_regularity — measure writing rhythm health.

A healthy self-writing system produces strokes at a steady cadence.
Bursts followed by long silences indicate process instability even
when total stroke count looks fine.  This module answers: *is the
writing rhythm regular, or is it lurching?*

The core metric is **regularity** (0.0–1.0):

- **1.0**: perfectly even spacing — every stroke arrives exactly on
  cadence.
- **0.5**: moderate variation — some gaps are twice the expected
  interval, others are half.
- **0.0**: extreme clustering — all strokes arrive in one burst
  followed by total silence.

Public API::

    from iamai.heartbeat_regularity import HeartbeatMonitor, regularity_report

    monitor = HeartbeatMonitor(expected_interval=15.0)
    monitor.record_stroke(timestamp)
    monitor.record_stroke(timestamp)

    score = monitor.regularity_score()
    # 0.87

    print(regularity_report(monitor))
    # "regularity 0.87, cv 0.15, 120 strokes, 0 bursts — healthy rhythm"

Metrics
-------

- **regularity_score**: 1 - normalized CV of inter-stroke intervals,
  clamped to [0, 1].  Lower CV means more regular timing.
- **coefficient_of_variation (CV)**: stddev / mean of intervals.
  CV < 0.3 is healthy; > 1.0 means the rhythm is chaotic.
- **burst_count**: number of times ≥ 3 strokes arrived within half
  the expected interval of each other.
- **longest_silence**: the biggest gap between consecutive strokes,
  in seconds.
- **silence_ratio**: longest_silence / expected_interval.  Values
  above 10 indicate a significant stall.
- **rhythm_grade**: healthy / wobbly / irregular / erratic / stalled.

Rhythm grades
-------------

=========  ============================================================
grade      meaning
=========  ============================================================
healthy    CV < 0.3 — steady cadence, process is stable
wobbly     0.3 ≤ CV < 0.6 — some variation, mostly on schedule
irregular  0.6 ≤ CV < 1.0 — timing varies significantly
erratic    1.0 ≤ CV < 2.0 — burst-silence pattern, process unstable
stalled    CV ≥ 2.0 or longest_silence > 20× expected — effectively dead
=========  ============================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# Rhythm grade thresholds: (max_cv, grade_name)
_GRADES = [
    (0.3, "healthy"),
    (0.6, "wobbly"),
    (1.0, "irregular"),
    (2.0, "erratic"),
    (float("inf"), "stalled"),
]


@dataclass(frozen=True)
class StrokeEvent:
    """A single stroke timestamp."""

    timestamp: float

    def __post_init__(self):
        if self.timestamp < 0:
            raise ValueError(f"timestamp must be non-negative, got {self.timestamp}")


@dataclass
class HeartbeatMonitor:
    """Track stroke timing and compute rhythm health metrics.

    Parameters
    ----------
    expected_interval : float
        The target seconds between strokes (default 15.0).
    burst_threshold : float
        Fraction of expected_interval below which consecutive strokes
        count as a burst (default 0.5).
    stall_multiplier : float
        Multiple of expected_interval above which the rhythm is
        classified as stalled regardless of CV (default 20.0).
    """

    expected_interval: float = 15.0
    burst_threshold: float = 0.5
    stall_multiplier: float = 20.0
    _strokes: List[StrokeEvent] = field(default_factory=list)

    # -- recording --

    def record_stroke(self, timestamp: float) -> None:
        """Record a stroke at the given timestamp (epoch seconds)."""
        self._strokes.append(StrokeEvent(timestamp=timestamp))

    def record_strokes(self, timestamps: Sequence[float]) -> None:
        """Record multiple strokes at once."""
        for ts in timestamps:
            self.record_stroke(ts)

    @property
    def stroke_count(self) -> int:
        return len(self._strokes)

    # -- interval computation --

    def intervals(self) -> List[float]:
        """Return sorted list of inter-stroke intervals."""
        if len(self._strokes) < 2:
            return []
        times = sorted(s.timestamp for s in self._strokes)
        return [times[i + 1] - times[i] for i in range(len(times) - 1)]

    # -- metrics --

    def coefficient_of_variation(self) -> Optional[float]:
        """CV = stddev / mean of inter-stroke intervals.

        Returns None if fewer than 2 strokes recorded.
        """
        ivs = self.intervals()
        if not ivs:
            return None
        n = len(ivs)
        mean = sum(ivs) / n
        if mean == 0:
            return float("inf")
        variance = sum((x - mean) ** 2 for x in ivs) / n
        return math.sqrt(variance) / mean

    def regularity_score(self) -> Optional[float]:
        """Regularity score: 1 - normalized CV, clamped to [0, 1].

        Normalization: CV is divided by 2.0 so that CV=2.0 maps to
        score 0.0.  CV=0 maps to 1.0.

        Returns None if fewer than 2 strokes.
        """
        cv = self.coefficient_of_variation()
        if cv is None:
            return None
        return max(0.0, min(1.0, 1.0 - cv / 2.0))

    def burst_count(self) -> int:
        """Count groups of ≥3 strokes arriving within half the expected
        interval of each other."""
        if len(self._strokes) < 3:
            return 0
        times = sorted(s.timestamp for s in self._strokes)
        threshold = self.expected_interval * self.burst_threshold
        bursts = 0
        run = 1
        for i in range(1, len(times)):
            if times[i] - times[i - 1] <= threshold:
                run += 1
                if run == 3:
                    bursts += 1
            else:
                run = 1
        return bursts

    def longest_silence(self) -> Optional[float]:
        """The largest gap between consecutive strokes, in seconds."""
        ivs = self.intervals()
        return max(ivs) if ivs else None

    def silence_ratio(self) -> Optional[float]:
        """longest_silence / expected_interval."""
        ls = self.longest_silence()
        if ls is None:
            return None
        return ls / self.expected_interval

    def rhythm_grade(self) -> Optional[str]:
        """Classify the rhythm based on CV and silence ratio.

        Returns 'stalled' if silence_ratio > stall_multiplier,
        regardless of CV.
        """
        cv = self.coefficient_of_variation()
        if cv is None:
            return None

        sr = self.silence_ratio()
        if sr is not None and sr > self.stall_multiplier:
            return "stalled"

        for threshold, grade in _GRADES:
            if cv < threshold:
                return grade
        return "stalled"

    # -- summary --

    def summary(self) -> dict:
        """Return a dict of all metrics."""
        return {
            "stroke_count": self.stroke_count,
            "expected_interval": self.expected_interval,
            "cv": self.coefficient_of_variation(),
            "regularity": self.regularity_score(),
            "bursts": self.burst_count(),
            "longest_silence": self.longest_silence(),
            "silence_ratio": self.silence_ratio(),
            "grade": self.rhythm_grade(),
        }


def regularity_report(monitor: HeartbeatMonitor) -> str:
    """One-line human-readable rhythm health summary."""
    s = monitor.summary()
    if s["stroke_count"] < 2:
        return f"heartbeat: {s['stroke_count']} stroke(s) — not enough data"

    reg = f"{s['regularity']:.2f}" if s["regularity"] is not None else "n/a"
    cv = f"{s['cv']:.2f}" if s["cv"] is not None else "n/a"
    ls = f"{s['longest_silence']:.0f}s" if s["longest_silence"] is not None else "n/a"
    grade = s["grade"] or "unknown"

    return (
        f"regularity {reg}, cv {cv}, {s['stroke_count']} strokes, "
        f"{s['bursts']} burst(s), longest silence {ls} — {grade}"
    )
