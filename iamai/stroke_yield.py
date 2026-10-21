"""stroke_yield — measure what the writer actually produces per unit of wall time.

``stroke_pacer`` checks whether strokes arrive on the *configured* cadence
(e.g. every 15 s).  ``stroke_novelty`` checks whether the text is fresh.
Neither answers the question a caretaker actually needs at 3 AM:

    "In the last hour, how many useful strokes did this writer produce,
    and is that rate going up or down?"

Yield is **strokes per minute of wall-clock time**, computed over sliding
windows.  It collapses burst-then-idle patterns into a single number that
trends toward zero when the writer is stalling, and toward the configured
cadence when it is healthy.

Concept
-------

Given a list of ``(timestamp, kind)`` pairs representing stroke events::

    window_yield(timestamps, window=3600)
        → strokes_per_minute over the last ``window`` seconds

    yield_trend(timestamps, windows=[300, 900, 3600])
        → acceleration signal: rising, steady, or falling

    session_summary(timestamps, start, end)
        → total strokes, yield rate, dead-time fraction, burst count

Classification per window::

    productive   yield >= 3.0 spm   (one stroke every 20 s or faster)
    steady       1.0 <= yield < 3.0 spm
    sluggish     0.2 <= yield < 1.0 spm  (one stroke every 1–5 min)
    stalled      yield < 0.2 spm   (effectively silent)

Why yield instead of cadence
-----------------------------

Cadence measures the *interval* between consecutive strokes.  It breaks
down when the writer alternates between bursts of five strokes in a
minute and twenty minutes of silence.  Yield smooths that out: over any
window, you either produced useful work or you didn't.

Yield also makes cross-writer comparison meaningful.  A 15 s cadence
writer and a 60 s cadence writer can both be "productive" if their yield
rates are both above the threshold — cadence is a design choice, yield
is an outcome.

Usage::

    from iamai.stroke_yield import StrokeYield

    sy = StrokeYield()
    sy.ingest(timestamps, kinds)
    sy.current_yield()          # strokes per minute right now
    sy.trend()                  # "rising" | "steady" | "falling"
    sy.session_report(start_t)  # full session breakdown
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Thresholds (strokes per minute)
# ---------------------------------------------------------------------------

_PRODUCTIVE_SPM = 3.0   # one stroke every 20 s
_STEADY_SPM = 1.0        # one stroke every 60 s
_SLUGGISH_SPM = 0.2      # one stroke every 5 min


def classify_yield(spm: float) -> str:
    """Classify a strokes-per-minute value."""
    if spm >= _PRODUCTIVE_SPM:
        return "productive"
    if spm >= _STEADY_SPM:
        return "steady"
    if spm >= _SLUGGISH_SPM:
        return "sluggish"
    return "stalled"


def classify_trend(ratio: float) -> str:
    """Classify yield trend from recent/older ratio.

    Parameters
    ----------
    ratio : float
        recent_yield / older_yield.  > 1.2 is rising, < 0.8 is falling.
    """
    if ratio > 1.2:
        return "rising"
    if ratio < 0.8:
        return "falling"
    return "steady"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowYield:
    """Yield measurement for a single time window."""

    window_seconds: int
    strokes: int
    spm: float          # strokes per minute
    verdict: str        # productive | steady | sluggish | stalled

    def to_dict(self) -> dict:
        return {
            "window_seconds": self.window_seconds,
            "strokes": self.strokes,
            "spm": round(self.spm, 4),
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class SessionReport:
    """Full session breakdown."""

    duration_seconds: float
    total_strokes: int
    spm: float
    verdict: str
    dead_time_seconds: float
    dead_time_fraction: float
    burst_count: int
    longest_gap_seconds: float
    by_kind: dict

    def to_dict(self) -> dict:
        return {
            "duration_seconds": round(self.duration_seconds, 1),
            "total_strokes": self.total_strokes,
            "spm": round(self.spm, 4),
            "verdict": self.verdict,
            "dead_time_seconds": round(self.dead_time_seconds, 1),
            "dead_time_fraction": round(self.dead_time_fraction, 4),
            "burst_count": self.burst_count,
            "longest_gap_seconds": round(self.longest_gap_seconds, 1),
            "by_kind": self.by_kind,
        }


# ---------------------------------------------------------------------------
# Core analyser
# ---------------------------------------------------------------------------


class StrokeYield:
    """Track writing yield over time.

    Parameters
    ----------
    burst_threshold : float
        Gap in seconds below which consecutive strokes count as a burst.
        Default 30 s — three strokes within 30 s is a burst.
    dead_gap : float
        Gap in seconds above which time counts as "dead" (writer idle).
        Default 120 s — any gap over 2 min is dead time.
    """

    def __init__(self, burst_threshold: float = 30.0, dead_gap: float = 120.0):
        self.burst_threshold = burst_threshold
        self.dead_gap = dead_gap
        self._timestamps: list[float] = []
        self._kinds: list[str] = []

    # -- ingestion -----------------------------------------------------------

    def ingest(self, timestamps: Sequence[float],
               kinds: Sequence[str] | None = None) -> None:
        """Add stroke events.

        Parameters
        ----------
        timestamps : sequence of float
            Unix timestamps of stroke events.
        kinds : sequence of str, optional
            Stroke kind labels (devlog, note, thought, etc.).
        """
        pairs = sorted(zip(timestamps, kinds or [""] * len(timestamps)))
        for ts, kind in pairs:
            self._timestamps.append(float(ts))
            self._kinds.append(kind)

    def add(self, timestamp: float, kind: str = "") -> None:
        """Add a single stroke event."""
        self._timestamps.append(float(timestamp))
        self._kinds.append(kind)

    # -- window yield --------------------------------------------------------

    def window_yield(self, window: int = 3600,
                     now: float | None = None) -> WindowYield:
        """Compute yield over a trailing window.

        Parameters
        ----------
        window : int
            Window size in seconds.
        now : float, optional
            Reference time.  Defaults to last known timestamp.

        Returns
        -------
        WindowYield
        """
        now = now or (self._timestamps[-1] if self._timestamps else time.time())
        cutoff = now - window
        count = sum(1 for t in self._timestamps if t > cutoff)
        spm = count / (window / 60.0) if window > 0 else 0.0
        return WindowYield(
            window_seconds=window,
            strokes=count,
            spm=spm,
            verdict=classify_yield(spm),
        )

    def current_yield(self, now: float | None = None) -> float:
        """Strokes per minute over the last 5 minutes."""
        return self.window_yield(window=300, now=now).spm

    # -- trend ---------------------------------------------------------------

    def trend(self, now: float | None = None) -> dict:
        """Compare recent yield to older yield.

        Returns
        -------
        dict with keys: trend, recent_spm, older_spm, ratio
        """
        now = now or (self._timestamps[-1] if self._timestamps else time.time())
        recent = self.window_yield(window=300, now=now)       # last 5 min
        older = self.window_yield(window=900, now=now - 300)  # 5–15 min ago

        if older.spm == 0:
            ratio = float("inf") if recent.spm > 0 else 1.0
        else:
            ratio = recent.spm / older.spm

        return {
            "trend": classify_trend(ratio),
            "recent_spm": round(recent.spm, 4),
            "older_spm": round(older.spm, 4),
            "ratio": round(ratio, 4) if ratio != float("inf") else "inf",
        }

    # -- session report ------------------------------------------------------

    def session_report(self, start: float | None = None,
                       end: float | None = None) -> SessionReport:
        """Full breakdown for a session.

        Parameters
        ----------
        start : float, optional
            Session start time.  Defaults to first stroke.
        end : float, optional
            Session end time.  Defaults to last stroke.

        Returns
        -------
        SessionReport
        """
        if not self._timestamps:
            return SessionReport(
                duration_seconds=0, total_strokes=0, spm=0,
                verdict="stalled", dead_time_seconds=0,
                dead_time_fraction=0, burst_count=0,
                longest_gap_seconds=0, by_kind={},
            )

        start = start or self._timestamps[0]
        end = end or self._timestamps[-1]

        # Filter to session range
        ts_in = [t for t in self._timestamps if start <= t <= end]
        ki_in = [k for t, k in zip(self._timestamps, self._kinds)
                 if start <= t <= end]

        duration = max(end - start, 1.0)
        total = len(ts_in)
        spm = total / (duration / 60.0)

        # Gaps analysis
        gaps = []
        dead_time = 0.0
        burst_count = 0
        in_burst = False

        for i in range(1, len(ts_in)):
            gap = ts_in[i] - ts_in[i - 1]
            gaps.append(gap)
            if gap > self.dead_gap:
                dead_time += gap
            if gap <= self.burst_threshold:
                if not in_burst:
                    burst_count += 1
                    in_burst = True
            else:
                in_burst = False

        longest_gap = max(gaps) if gaps else 0.0

        # Kind distribution
        by_kind: dict[str, int] = {}
        for k in ki_in:
            label = k or "unknown"
            by_kind[label] = by_kind.get(label, 0) + 1

        return SessionReport(
            duration_seconds=duration,
            total_strokes=total,
            spm=spm,
            verdict=classify_yield(spm),
            dead_time_seconds=dead_time,
            dead_time_fraction=dead_time / duration if duration > 0 else 0,
            burst_count=burst_count,
            longest_gap_seconds=longest_gap,
            by_kind=by_kind,
        )

    # -- multi-window snapshot -----------------------------------------------

    def snapshot(self, now: float | None = None,
                 windows: Sequence[int] = (300, 900, 3600)) -> list[WindowYield]:
        """Yield across multiple windows at once."""
        return [self.window_yield(w, now) for w in windows]

    # -- housekeeping --------------------------------------------------------

    def reset(self) -> None:
        """Clear all data."""
        self._timestamps.clear()
        self._kinds.clear()

    @property
    def count(self) -> int:
        return len(self._timestamps)
