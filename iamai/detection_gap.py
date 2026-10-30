"""detection_gap — measure the window between stall detection and recovery.

The *detection gap* is the elapsed time between:
  1. the moment a stall is first flagged (detection), and
  2. the moment a recovery action is taken (restart, fix, or dismissal).

This metric captures how quickly the system responds to its own warnings.
A short gap means the caretaker (human or automated) is responsive.
A long gap means warnings are accumulating without action — the system
is *aware* of its problems but not *addressing* them.

Severity tiers
--------------

===========  ================================================
verdict      condition
===========  ================================================
``prompt``   gap < 120 s — immediate response
``timely``   gap < 600 s — responded within 10 minutes
``delayed``  gap < 1800 s — responded within 30 minutes
``neglected`` gap >= 1800 s — warning sat unaddressed
===========  ================================================

Usage::

    from iamai.detection_gap import DetectionGapTracker

    tracker = DetectionGapTracker()
    tracker.mark_detected("stall_probe", at=1000.0)
    tracker.mark_recovered("caretaker_restart", at=1045.0)
    tracker.latest_gap()          # 45.0
    tracker.latest_verdict()      # "prompt"
    tracker.summarize()           # dict with stats
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


@dataclass
class DetectionEvent:
    """A single detection-to-recovery event."""

    detected_at: float
    detected_by: str
    recovered_at: Optional[float] = None
    recovered_by: Optional[str] = None

    @property
    def gap_seconds(self) -> float:
        """Elapsed time from detection to recovery (or now if unresolved)."""
        end = self.recovered_at if self.recovered_at is not None else time.monotonic()
        return end - self.detected_at

    @property
    def resolved(self) -> bool:
        return self.recovered_at is not None

    def classify(self) -> str:
        """Classify the gap severity."""
        return classify_detection_gap(self.gap_seconds)


def classify_detection_gap(gap_seconds: float) -> str:
    """Classify a detection-to-recovery gap.

    Args:
        gap_seconds: seconds between detection and recovery

    Returns:
        One of: "prompt", "timely", "delayed", "neglected"

    Examples:
        >>> classify_detection_gap(30)
        'prompt'
        >>> classify_detection_gap(300)
        'timely'
        >>> classify_detection_gap(900)
        'delayed'
        >>> classify_detection_gap(3600)
        'neglected'
    """
    if gap_seconds < 120:
        return "prompt"
    if gap_seconds < 600:
        return "timely"
    if gap_seconds < 1800:
        return "delayed"
    return "neglected"


def gap_advice(verdict: str) -> str:
    """Actionable advice for a given detection gap verdict.

    Args:
        verdict: output from classify_detection_gap()

    Returns:
        Advice string
    """
    advice = {
        "prompt": "Detection-to-recovery was immediate. System is responsive.",
        "timely": "Recovery happened within 10 minutes. Acceptable cadence.",
        "delayed": "Recovery took up to 30 minutes. Consider automating restart.",
        "neglected": "Warning sat unaddressed for 30+ minutes. "
                     "Add automated recovery or increase caretaker frequency.",
    }
    return advice.get(verdict, f"Unknown verdict: {verdict}")


@dataclass
class DetectionGapTracker:
    """Track detection-to-recovery gaps over time."""

    _events: List[DetectionEvent] = field(default_factory=list, repr=False)
    _pending: Optional[DetectionEvent] = field(default=None, repr=False)

    def mark_detected(self, detector: str, at: Optional[float] = None) -> None:
        """Record that a stall was detected.

        Args:
            detector: name of the detector that flagged the stall
            at: monotonic timestamp (defaults to time.monotonic())

        If there is already an unresolved detection, it is overwritten —
        only the latest detection matters until recovery occurs.
        """
        ts = at if at is not None else time.monotonic()
        self._pending = DetectionEvent(detected_at=ts, detected_by=detector)

    def mark_recovered(self, method: str, at: Optional[float] = None) -> bool:
        """Record that recovery action was taken.

        Args:
            method: how recovery was performed (e.g., "caretaker_restart")
            at: monotonic timestamp (defaults to time.monotonic())

        Returns:
            True if a pending detection was resolved, False if no detection
            was pending.
        """
        if self._pending is None:
            return False

        ts = at if at is not None else time.monotonic()
        self._pending.recovered_at = ts
        self._pending.recovered_by = method
        self._events.append(self._pending)
        self._pending = None
        return True

    @property
    def pending(self) -> bool:
        """Whether there is an unresolved detection."""
        return self._pending is not None

    @property
    def pending_gap(self) -> float:
        """Current gap for an unresolved detection (0 if none pending)."""
        if self._pending is None:
            return 0.0
        return self._pending.gap_seconds

    @property
    def event_count(self) -> int:
        """Total number of resolved detection events."""
        return len(self._events)

    def latest_gap(self) -> float:
        """Gap of the most recent resolved event (0 if none)."""
        if not self._events:
            return 0.0
        return self._events[-1].gap_seconds

    def latest_verdict(self) -> str:
        """Verdict for the most recent resolved event."""
        if not self._events:
            return "no_events"
        return self._events[-1].classify()

    def gaps(self) -> List[float]:
        """All resolved gap durations."""
        return [e.gap_seconds for e in self._events]

    @property
    def mean_gap(self) -> float:
        """Average gap across all resolved events."""
        gs = self.gaps()
        return sum(gs) / len(gs) if gs else 0.0

    @property
    def max_gap(self) -> float:
        """Maximum gap across all resolved events."""
        gs = self.gaps()
        return max(gs) if gs else 0.0

    @property
    def min_gap(self) -> float:
        """Minimum gap across all resolved events."""
        gs = self.gaps()
        return min(gs) if gs else 0.0

    def verdict_distribution(self) -> Dict[str, int]:
        """Count of events per verdict category."""
        dist: Dict[str, int] = {"prompt": 0, "timely": 0, "delayed": 0, "neglected": 0}
        for e in self._events:
            v = e.classify()
            dist[v] = dist.get(v, 0) + 1
        return dist

    def summarize(self) -> Dict:
        """JSON-serializable summary of all detection gaps."""
        gs = self.gaps()
        return {
            "resolved_events": len(self._events),
            "pending": self.pending,
            "pending_gap_s": round(self.pending_gap, 1),
            "mean_gap_s": round(self.mean_gap, 1),
            "max_gap_s": round(self.max_gap, 1),
            "min_gap_s": round(self.min_gap, 1),
            "latest_verdict": self.latest_verdict(),
            "distribution": self.verdict_distribution(),
        }

    def report_line(self) -> str:
        """One-line human-readable summary for caretaker logs."""
        s = self.summarize()
        pending_note = f", pending {s['pending_gap_s']:.0f}s" if s["pending"] else ""
        return (
            f"detection_gap: {s['resolved_events']} events, "
            f"mean {s['mean_gap_s']:.0f}s, "
            f"max {s['max_gap_s']:.0f}s, "
            f"latest {s['latest_verdict']}"
            f"{pending_note}"
        )

    def reset(self) -> None:
        """Clear all events and pending state."""
        self._events.clear()
        self._pending = None
