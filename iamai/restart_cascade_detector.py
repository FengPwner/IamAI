#!/usr/bin/env python3
"""restart_cascade_detector — detect and measure restart cascade patterns.

When one process dies or restarts, it can trigger a chain reaction: the
writer stops, the batch notices and exits, the supervisor restarts both,
and then a cascade of recovery scripts runs.  This module records
timestamped restart events, groups them into *cascades* using a
configurable time window, and classifies each cascade by severity.

Metrics reported per detection pass
-----------------------------------

==========================  =================================================
metric                      meaning
==========================  =================================================
total_restarts              total number of restart events recorded
isolated_restarts           restarts that did NOT belong to any cascade
cascade_count               number of detected cascade groups
max_cascade_depth           largest cascade size (events in one window)
mean_cascade_depth          average cascade size (cascades only)
mean_cascade_duration       mean span from first to last event in a cascade
mean_time_between_cascades  mean gap between consecutive cascade starts
cascade_fraction            fraction of restarts that are part of cascades
coordination_score          100 × (1 − cascade_fraction); higher is better
==========================  =================================================

Cascade severity classification
-------------------------------

===========  ============  =================================================
label        depth         meaning
===========  ============  =================================================
clean        1 (isolated)  single restart, no cascade
minor        2–3           small cascade, normal recovery
major        4–5           significant cascade, investigate root cause
catastrophic 6+            systemic failure, multiple components affected
===========  ============  =================================================

Usage::

    from iamai.restart_cascade_detector import RestartCascadeDetector

    detector = RestartCascadeDetector(window_seconds=30.0)
    detector.record(0.0, "writer")
    detector.record(5.0, "batch")
    detector.record(60.0, "writer")        # isolated, outside cascade window
    report = detector.detect()
    print(report.cascade_count, report.coordination_score)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RestartEvent:
    """A single process restart observation."""

    timestamp: float
    process: str
    pid: Optional[int] = None


@dataclass
class RestartCascade:
    """A group of restarts that occurred within *window* seconds."""

    events: List[RestartEvent] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return len(self.events)

    @property
    def duration(self) -> float:
        if len(self.events) < 2:
            return 0.0
        return self.events[-1].timestamp - self.events[0].timestamp

    @property
    def processes(self) -> List[str]:
        return [e.process for e in self.events]

    @property
    def start_time(self) -> float:
        return self.events[0].timestamp if self.events else 0.0


@dataclass
class CascadeReport:
    """Result of a cascade detection pass."""

    total_restarts: int = 0
    isolated_restarts: int = 0
    cascade_count: int = 0
    max_cascade_depth: int = 0
    mean_cascade_depth: float = 0.0
    mean_cascade_duration: float = 0.0
    mean_time_between_cascades: float = 0.0
    cascade_fraction: float = 0.0
    coordination_score: float = 100.0
    largest_cascades: List[RestartCascade] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class RestartCascadeDetector:
    """Record restart events and detect cascade patterns.

    Parameters
    ----------
    window_seconds : float
        Maximum time span (last event − first event) for a group of
        restarts to be considered a single cascade.  Default 60 s.
    minor_threshold : int
        Minimum cascade depth to classify as *minor*.  Default 2.
    major_threshold : int
        Minimum cascade depth to classify as *major*.  Default 4.
    catastrophic_threshold : int
        Minimum cascade depth to classify as *catastrophic*.  Default 6.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        minor_threshold: int = 2,
        major_threshold: int = 4,
        catastrophic_threshold: int = 6,
    ):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window = window_seconds
        self.minor_threshold = minor_threshold
        self.major_threshold = major_threshold
        self.catastrophic_threshold = catastrophic_threshold
        self._events: List[RestartEvent] = []

    # -- mutators -----------------------------------------------------------

    def record(
        self,
        timestamp: float,
        process: str,
        pid: Optional[int] = None,
    ) -> RestartEvent:
        """Record a restart event (or pass a pre-built RestartEvent)."""
        if isinstance(timestamp, RestartEvent):
            self._events.append(timestamp)
            return timestamp
        event = RestartEvent(
            timestamp=timestamp, process=process, pid=pid,
        )
        self._events.append(event)
        return event

    def clear(self) -> None:
        """Remove all recorded events."""
        self._events.clear()

    # -- queries ------------------------------------------------------------

    @property
    def events(self) -> List[RestartEvent]:
        """Return a copy of the recorded events."""
        return list(self._events)

    @staticmethod
    def _find_cascades(
        events: List[RestartEvent], window: float,
    ) -> List[RestartCascade]:
        """Group sorted events into cascades by sliding window."""
        if not events:
            return []

        cascades: List[RestartCascade] = []
        current = RestartCascade(events=[events[0]])

        for event in events[1:]:
            if event.timestamp - current.events[0].timestamp <= window:
                current.events.append(event)
            else:
                cascades.append(current)
                current = RestartCascade(events=[event])

        cascades.append(current)
        return cascades

    def detect(self) -> CascadeReport:
        """Run cascade detection over all recorded events."""
        if not self._events:
            return CascadeReport()

        sorted_events = sorted(self._events, key=lambda e: e.timestamp)
        groups = self._find_cascades(sorted_events, self.window)

        cascades = [g for g in groups if g.depth >= self.minor_threshold]
        isolated = sum(1 for g in groups if g.depth < self.minor_threshold)
        cascaded_total = sum(g.depth for g in cascades)

        max_depth = max((g.depth for g in cascades), default=0)

        mean_depth = (
            sum(g.depth for g in cascades) / len(cascades)
            if cascades
            else 0.0
        )

        mean_dur = (
            sum(g.duration for g in cascades) / len(cascades)
            if cascades
            else 0.0
        )

        mean_between = 0.0
        if len(cascades) >= 2:
            gaps = [
                cascades[i + 1].start_time - cascades[i].start_time
                for i in range(len(cascades) - 1)
            ]
            mean_between = sum(gaps) / len(gaps)

        fraction = cascaded_total / len(sorted_events) if sorted_events else 0.0
        coord = 100.0 * (1.0 - fraction)

        top = sorted(cascades, key=lambda c: c.depth, reverse=True)[:3]

        return CascadeReport(
            total_restarts=len(sorted_events),
            isolated_restarts=isolated,
            cascade_count=len(cascades),
            max_cascade_depth=max_depth,
            mean_cascade_depth=round(mean_depth, 2),
            mean_cascade_duration=round(mean_dur, 2),
            mean_time_between_cascades=round(mean_between, 2),
            cascade_fraction=round(fraction, 4),
            coordination_score=round(coord, 2),
            largest_cascades=top,
        )

    @staticmethod
    def classify(
        depth: int,
        minor: int = 2,
        major: int = 4,
        catastrophic: int = 6,
    ) -> str:
        """Classify a cascade by depth.

        Returns one of ``clean``, ``minor``, ``major``, ``catastrophic``.
        """
        if depth >= catastrophic:
            return "catastrophic"
        if depth >= major:
            return "major"
        if depth >= minor:
            return "minor"
        return "clean"


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default = RestartCascadeDetector()


def record(timestamp: float, process: str, pid: Optional[int] = None):
    """Record a restart event on the module-level detector."""
    return _default.record(timestamp, process, pid)


def detect() -> CascadeReport:
    """Run detection on the module-level detector."""
    return _default.detect()


def classify(depth: int) -> str:
    """Classify a cascade depth using default thresholds."""
    return RestartCascadeDetector.classify(depth)


def clear() -> None:
    """Clear the module-level detector."""
    _default.clear()
