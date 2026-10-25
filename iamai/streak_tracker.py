"""Streak tracker: measure momentum in a self-writing repository.

A streak is a run of consecutive events that meet a criterion.  For a
repository that writes itself, the two streaks that matter are:

- **writing streak** -- consecutive stroke intervals within cadence tolerance.
- **commit streak** -- consecutive batch commits that landed on time.

When a streak breaks, the counter resets.  The *best* streak is the historical
maximum -- useful for detecting whether the repo is improving or regressing.

All functions are pure or operate on plain dicts, so the module is trivially
testable with synthetic data.

Usage::

    from iamai.streak_tracker import StreakTracker

    tracker = StreakTracker(cadence_seconds=15, tolerance=2.0)
    tracker.record_stroke(gap_seconds=14)   # streak: 1
    tracker.record_stroke(gap_seconds=16)   # streak: 2
    tracker.record_stroke(gap_seconds=120)  # break  -> streak resets to 0
    tracker.summary()
    # {'current_streak': 0, 'best_streak': 2, 'total_breaks': 1, ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StreakTracker:
    """Track consecutive on-time events and their historical best.

    Parameters
    ----------
    cadence_seconds : float
        Expected interval between events (e.g. 15 for strokes, 600 for commits).
    tolerance : float
        Multiplier on cadence; gaps up to ``cadence * tolerance`` are "on time".
        Default 2.0 means a stroke is late only if the gap exceeds 2x cadence.
    """

    cadence_seconds: float
    tolerance: float = 2.0
    _current: int = 0
    _best: int = 0
    _total_breaks: int = 0
    _total_events: int = 0

    @property
    def threshold(self) -> float:
        """Maximum gap (seconds) still considered on-time."""
        return self.cadence_seconds * self.tolerance

    def record(self, gap_seconds: float) -> dict:
        """Record one event.  Returns the current streak state after update."""
        self._total_events += 1
        if gap_seconds <= self.threshold:
            self._current += 1
            if self._current > self._best:
                self._best = self._current
        else:
            if self._current > 0:
                self._total_breaks += 1
            self._current = 0
        return {"current": self._current, "best": self._best}

    # Convenience aliases ------------------------------------------------

    def record_stroke(self, gap_seconds: float) -> dict:
        """Alias for ``record()`` -- semantically a writing event."""
        return self.record(gap_seconds)

    def record_commit(self, gap_seconds: float) -> dict:
        """Alias for ``record()`` -- semantically a batch commit event."""
        return self.record(gap_seconds)

    # Inspection ----------------------------------------------------------

    @property
    def current(self) -> int:
        return self._current

    @property
    def best(self) -> int:
        return self._best

    def summary(self) -> dict:
        """Return a snapshot of streak statistics."""
        return {
            "current_streak": self._current,
            "best_streak": self._best,
            "total_breaks": self._total_breaks,
            "total_events": self._total_events,
            "cadence_seconds": self.cadence_seconds,
            "tolerance": self.tolerance,
            "threshold_seconds": self.threshold,
        }

    def reset(self) -> None:
        """Clear all counters.  Useful when a caretaker restarts processes."""
        self._current = 0
        self._best = 0
        self._total_breaks = 0
        self._total_events = 0


def analyze_gaps(gaps: list[float], cadence_seconds: float, tolerance: float = 2.0) -> dict:
    """One-shot analysis of a list of gap measurements.

    Parameters
    ----------
    gaps : list[float]
        Ordered gap durations in seconds (oldest first).
    cadence_seconds : float
        Expected interval.
    tolerance : float
        Multiplier for on-time threshold.

    Returns
    -------
    dict with keys:
        - streaks: list of streak lengths (each broken by a late event)
        - best_streak: max streak length
        - total_breaks: number of streak breaks
        - on_time_ratio: fraction of events that were on time
    """
    tracker = StreakTracker(cadence_seconds=cadence_seconds, tolerance=tolerance)
    streaks: list[int] = []
    on_time = 0

    for gap in gaps:
        before = tracker.current
        tracker.record(gap)
        if tracker.current > before or (before == 0 and tracker.current == 1):
            on_time += 1
        elif tracker.current == 0 and before > 0:
            streaks.append(before)

    # Flush the final streak if still active
    if tracker.current > 0:
        streaks.append(tracker.current)

    total = len(gaps)
    return {
        "streaks": streaks,
        "best_streak": max(streaks) if streaks else 0,
        "total_breaks": tracker._total_breaks,
        "on_time_ratio": on_time / total if total else 0.0,
        "total_events": total,
    }
