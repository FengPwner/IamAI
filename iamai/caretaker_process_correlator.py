"""caretaker_process_correlator — correlate process events with writing output.

When the writer process restarts, the caretaker knows *that* it happened.
But the interesting question is *what was lost* and *how fast did it recover*.

This module answers:

- How many strokes would the writer have produced if it hadn't died?
- How long after restart did it take to return to normal cadence?
- Was the restart's impact negligible, moderate, or severe?

Data model
----------

``ProcessEvent``: a lifecycle event for the writer process.

- ``timestamp`` (float): UNIX epoch when the event occurred
- ``event_type`` (str): one of ``restart``, ``stall``, ``recovery``, ``crash``
- ``pid`` (int | None): process ID involved
- ``duration`` (float | None): seconds the event lasted (e.g., downtime)

``StrokeSample``: one observed stroke from the writer.

- ``timestamp`` (float): UNIX epoch
- ``category`` (str): stroke category (devlog, note, snippet, etc.)
- ``word_count`` (int): approximate word count of the stroke

``Correlation``: links one ProcessEvent to its writing-impact metrics.

- ``event`` (ProcessEvent)
- ``strokes_before`` (int): strokes in the window *before* the event
- ``strokes_after`` (int): strokes in the window *after* the event
- ``lost_strokes`` (float): estimated strokes lost during downtime
- ``recovery_seconds`` (float): seconds until post-event cadence matched pre-event
- ``impact`` (str): ``negligible`` / ``moderate`` / ``severe``

Functions
---------

``correlate_events(events, strokes, cadence, window)``
    Pair each event with before/after stroke counts.

``recovery_time(event, strokes, cadence)``
    Seconds from event until the writer's cadence stabilises.

``estimate_lost_strokes(duration, cadence)``
    How many strokes *should* have been written during downtime.

``classify_impact(lost, recovery, cadence)``
    Bucket the restart's severity.

``summarize(correlations)``
    Aggregate across all events: total lost, mean recovery, worst impact.

Impact thresholds
-----------------

========  ============  ================
impact    lost_strokes  recovery_seconds
========  ============  ================
negligible   < 2          < cadence × 4
moderate     < 10         < cadence × 20
severe       >= 10        >= cadence × 20
========  ============  ================
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass
class ProcessEvent:
    timestamp: float
    event_type: str  # restart | stall | recovery | crash
    pid: Optional[int] = None
    duration: Optional[float] = None


@dataclass
class StrokeSample:
    timestamp: float
    category: str = ""
    word_count: int = 0


@dataclass
class Correlation:
    event: ProcessEvent
    strokes_before: int = 0
    strokes_after: int = 0
    lost_strokes: float = 0.0
    recovery_seconds: float = 0.0
    impact: str = "unknown"

    def summary(self) -> str:
        return (
            f"{self.event.event_type}@{self.event.timestamp:.0f}: "
            f"{self.strokes_before} before, {self.strokes_after} after, "
            f"~{self.lost_strokes:.1f} lost, "
            f"recovery {self.recovery_seconds:.0f}s, "
            f"impact={self.impact}"
        )


@dataclass
class CorrelationSummary:
    total_events: int = 0
    total_lost_strokes: float = 0.0
    mean_recovery_seconds: float = 0.0
    worst_impact: str = "unknown"
    negligible_count: int = 0
    moderate_count: int = 0
    severe_count: int = 0

    def summary(self) -> str:
        return (
            f"{self.total_events} events, "
            f"~{self.total_lost_strokes:.1f} strokes lost, "
            f"mean recovery {self.mean_recovery_seconds:.0f}s, "
            f"worst={self.worst_impact}"
        )


# ---------------------------------------------------------------------------
# core functions
# ---------------------------------------------------------------------------

_IMPACT_ORDER = {"unknown": 0, "negligible": 1, "moderate": 2, "severe": 3}


def estimate_lost_strokes(duration: float, cadence: float) -> float:
    """Estimate how many strokes were lost during a downtime window.

    >>> estimate_lost_strokes(300, 15)
    20.0
    >>> estimate_lost_strokes(0, 15)
    0.0
    >>> estimate_lost_strokes(60, 0)
    0.0
    """
    if cadence <= 0 or duration <= 0:
        return 0.0
    return duration / cadence


def _count_strokes_in_window(
    strokes: Sequence[StrokeSample], start: float, end: float
) -> int:
    return sum(1 for s in strokes if start <= s.timestamp < end)


def recovery_time(
    event: ProcessEvent,
    strokes: Sequence[StrokeSample],
    cadence: float,
    settle_window: int = 5,
) -> float:
    """Seconds from event until post-event cadence stabilises.

    Looks at consecutive inter-stroke intervals after the event.
    "Stable" means the last ``settle_window`` intervals are all within
    2× of the target cadence.

    Returns 0.0 if there aren't enough post-event strokes to judge.
    """
    post = sorted(s.timestamp for s in strokes if s.timestamp >= event.timestamp)
    if len(post) < settle_window + 1:
        return 0.0

    intervals = [post[i + 1] - post[i] for i in range(len(post) - 1)]
    threshold = cadence * 2

    # find the first point where the last `settle_window` intervals are all ≤ threshold
    for i in range(settle_window, len(intervals) + 1):
        window = intervals[i - settle_window : i]
        if all(iv <= threshold for iv in window):
            # stable at intervals[i-1], which corresponds to post[i]
            return post[i] - event.timestamp

    # never stabilised within the data we have
    return post[-1] - event.timestamp


def classify_impact(
    lost_strokes: float, recovery_seconds: float, cadence: float
) -> str:
    """Bucket the restart severity.

    >>> classify_impact(1.0, 30, 15)
    'negligible'
    >>> classify_impact(5.0, 200, 15)
    'moderate'
    >>> classify_impact(15.0, 400, 15)
    'severe'
    """
    if lost_strokes < 2 and recovery_seconds < cadence * 4:
        return "negligible"
    if lost_strokes < 10 and recovery_seconds < cadence * 20:
        return "moderate"
    return "severe"


def correlate_events(
    events: Sequence[ProcessEvent],
    strokes: Sequence[StrokeSample],
    cadence: float = 15.0,
    window: float = 300.0,
) -> List[Correlation]:
    """Pair each process event with before/after stroke metrics.

    For each event, counts strokes in ``[event.timestamp - window, event.timestamp)``
    and ``[event.timestamp, event.timestamp + window)``, estimates lost strokes
    from the event's duration, and computes recovery time.
    """
    correlations: List[Correlation] = []
    sorted_strokes = sorted(strokes, key=lambda s: s.timestamp)

    for ev in events:
        before = _count_strokes_in_window(
            sorted_strokes, ev.timestamp - window, ev.timestamp
        )
        after = _count_strokes_in_window(
            sorted_strokes, ev.timestamp, ev.timestamp + window
        )
        duration = ev.duration or 0.0
        lost = estimate_lost_strokes(duration, cadence)
        recov = recovery_time(ev, sorted_strokes, cadence)
        impact = classify_impact(lost, recov, cadence)

        correlations.append(
            Correlation(
                event=ev,
                strokes_before=before,
                strokes_after=after,
                lost_strokes=lost,
                recovery_seconds=recov,
                impact=impact,
            )
        )

    return correlations


def summarize(correlations: Sequence[Correlation]) -> CorrelationSummary:
    """Aggregate across all correlations."""
    if not correlations:
        return CorrelationSummary()

    total_lost = sum(c.lost_strokes for c in correlations)
    recoveries = [c.recovery_seconds for c in correlations if c.recovery_seconds > 0]
    mean_recovery = statistics.mean(recoveries) if recoveries else 0.0

    counts = {"negligible": 0, "moderate": 0, "severe": 0}
    worst = "unknown"
    for c in correlations:
        if c.impact in counts:
            counts[c.impact] += 1
        if _IMPACT_ORDER.get(c.impact, 0) > _IMPACT_ORDER.get(worst, 0):
            worst = c.impact

    return CorrelationSummary(
        total_events=len(correlations),
        total_lost_strokes=total_lost,
        mean_recovery_seconds=mean_recovery,
        worst_impact=worst,
        negligible_count=counts["negligible"],
        moderate_count=counts["moderate"],
        severe_count=counts["severe"],
    )
