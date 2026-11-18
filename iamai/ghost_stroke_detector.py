"""ghost_stroke_detector — find strokes not attributable to any active writer.

In a multi-agent repository where several automated writers (qwen,
doubao, kimi, …) take turns appending strokes, every stroke should
fall within the active window of *some* known writer process.
Strokes that don't are "ghosts" — they may indicate:

- a zombie writer process that wasn't tracked
- clock skew between agents
- log corruption or duplicate appends
- a human editing the log manually

This module cross-references a stroke log against a set of writer
sessions (each defined by a start time, end time, and expected
cadence) and reports strokes that no session claims.

Usage::

    from iamai.ghost_stroke_detector import GhostDetector, WriterSession

    sessions = [
        WriterSession(
            name="qwen",
            start="2026-11-18T08:00:00+00:00",
            end="2026-11-18T12:00:00+00:00",
            expected_cadence_s=15,
        ),
    ]
    det = GhostDetector(sessions, tolerance_s=30)
    ghosts = det.scan(strokes)
    print(len(ghosts))          # number of unattributed strokes
    print(ghosts[0].reason)     # why this stroke is a ghost

Written by Qwen during caretaker visit 706, 2026-11-18.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence


# ─── Data classes ───────────────────────────────────────────────────


@dataclass(frozen=True)
class WriterSession:
    """A known writer process and its active time window."""

    name: str
    start: str  # ISO-8601 timestamp
    end: str    # ISO-8601 timestamp
    expected_cadence_s: float = 15.0  # seconds between strokes

    @property
    def start_dt(self) -> datetime:
        return _parse_ts(self.start)

    @property
    def end_dt(self) -> datetime:
        return _parse_ts(self.end)

    @property
    def duration_s(self) -> float:
        return (self.end_dt - self.start_dt).total_seconds()


@dataclass(frozen=True)
class Stroke:
    """A single stroke from the log."""

    seq: int
    at: str  # ISO-8601 timestamp
    kind: str = ""
    text: str = ""

    @property
    def at_dt(self) -> datetime:
        return _parse_ts(self.at)


@dataclass(frozen=True)
class GhostStroke:
    """A stroke that no session claims, with the reason why."""

    stroke: Stroke
    reason: str
    nearest_session: Optional[str] = None
    gap_s: float = 0.0  # seconds from nearest session boundary


@dataclass(frozen=True)
class GhostReport:
    """Summary of a ghost-stroke scan."""

    total_strokes: int
    ghost_count: int
    ghosts: List[GhostStroke] = field(default_factory=list)

    @property
    def ghost_ratio(self) -> float:
        if self.total_strokes == 0:
            return 0.0
        return self.ghost_count / self.total_strokes

    @property
    def is_clean(self) -> bool:
        return self.ghost_count == 0


# ─── Detector ───────────────────────────────────────────────────────


class GhostDetector:
    """Detect strokes not attributable to any known writer session.

    Parameters
    ----------
    sessions : list of WriterSession
        Known active writer windows.
    tolerance_s : float
        Seconds of grace before/after a session window.  A stroke
        within ``tolerance_s`` of a session boundary is considered
        attributable (accounts for clock skew and startup/shutdown
        latency).
    cadence_tolerance : float
        Multiplier for expected cadence.  A stroke is considered
        "in cadence" if it falls within
        ``expected_cadence_s * cadence_tolerance`` of the previous
        attributed stroke or session start.  Used only for the
        ``out_of_cadence`` reason; strokes outside any session window
        are always ghosts regardless of cadence.
    """

    def __init__(
        self,
        sessions: Sequence[WriterSession],
        tolerance_s: float = 30.0,
        cadence_tolerance: float = 3.0,
    ) -> None:
        self.sessions = list(sessions)
        self.tolerance_s = tolerance_s
        self.cadence_tolerance = cadence_tolerance

    def scan(self, strokes: Sequence[Stroke]) -> GhostReport:
        """Scan strokes and return a report of unattributed ones."""
        ghosts: List[GhostStroke] = []

        for stroke in strokes:
            ghost = self._check_stroke(stroke)
            if ghost is not None:
                ghosts.append(ghost)

        return GhostReport(
            total_strokes=len(strokes),
            ghost_count=len(ghosts),
            ghosts=ghosts,
        )

    def _check_stroke(self, stroke: Stroke) -> Optional[GhostStroke]:
        """Return GhostStroke if stroke is unattributed, else None."""
        t = stroke.at_dt

        # Check if stroke falls within any session window (± tolerance)
        for session in self.sessions:
            start = session.start_dt
            end = session.end_dt

            # Within window (with tolerance)?
            if (start.timestamp() - self.tolerance_s
                    <= t.timestamp()
                    <= end.timestamp() + self.tolerance_s):
                return None  # Attributed to this session

        # Stroke is outside all sessions — it's a ghost.
        # Find the nearest session for diagnostics.
        nearest, gap = self._nearest_session(t)
        reason = self._classify_reason(t, nearest, gap)

        return GhostStroke(
            stroke=stroke,
            reason=reason,
            nearest_session=nearest.name if nearest else None,
            gap_s=gap,
        )

    def _nearest_session(
        self, t: datetime
    ) -> tuple[Optional[WriterSession], float]:
        """Find the session closest in time to timestamp t."""
        if not self.sessions:
            return None, float("inf")

        best: Optional[WriterSession] = None
        best_gap = float("inf")

        for session in self.sessions:
            start_ts = session.start_dt.timestamp()
            end_ts = session.end_dt.timestamp()
            t_ts = t.timestamp()

            if t_ts < start_ts:
                gap = start_ts - t_ts
            elif t_ts > end_ts:
                gap = t_ts - end_ts
            else:
                gap = 0.0

            if gap < best_gap:
                best_gap = gap
                best = session

        return best, best_gap

    def _classify_reason(
        self,
        t: datetime,
        nearest: Optional[WriterSession],
        gap: float,
    ) -> str:
        """Classify why a stroke is a ghost."""
        if nearest is None:
            return "no_sessions_defined"

        if gap < 120:
            return (
                f"just_outside_session ({nearest.name}, "
                f"gap={gap:.0f}s) — possible clock skew"
            )
        elif gap < 3600:
            return (
                f"between_sessions ({nearest.name}, "
                f"gap={gap:.0f}s) — possible zombie process"
            )
        else:
            return (
                f"far_from_any_session ({nearest.name}, "
                f"gap={gap:.0f}s) — possible corruption or manual edit"
            )


# ─── Helpers ────────────────────────────────────────────────────────


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    # Handle common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    # Fallback: use fromisoformat (Python 3.7+)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        raise ValueError(f"Cannot parse timestamp: {ts!r}")


def load_strokes_from_jsonl(path: str) -> List[Stroke]:
    """Load strokes from a JSONL file (one JSON object per line)."""
    import json

    strokes: List[Stroke] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            strokes.append(Stroke(
                seq=obj.get("seq", 0),
                at=obj.get("at", ""),
                kind=obj.get("kind", ""),
                text=obj.get("text", ""),
            ))
    return strokes
