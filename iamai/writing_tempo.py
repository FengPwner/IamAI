"""Writing tempo — measure the rhythm and health of the stroke writer.

The writer is expected to append a stroke roughly every 15-35 seconds.
This module analyses the *intervals* between consecutive strokes to
detect stalls, accelerations, decelerations, and to produce a single
health score that a caretaker can glance at.

Key concepts
~~~~~~~~~~~~

- **interval**: seconds between two consecutive strokes.
- **stall**: any interval longer than ``stall_threshold`` (default 300 s,
  i.e. 5 minutes — roughly 10× the expected cadence).
- **tempo_score**: 0.0 – 1.0 rating of how *regular* the writer is.
  1.0 means every interval is within the expected band; deductions are
  applied for variance, stalls, and drift from the target cadence.
- **verdict**: one of ``healthy``, ``wobbling``, ``stalling``, ``dead``
  — a quick label for dashboards.

All functions accept a list of ISO-8601 timestamps (strings) so they
work in tests without touching the real repo.  A convenience wrapper
``tempo_from_jsonl`` reads the file directly.

Usage::

    from iamai.writing_tempo import tempo_report, verdict

    stamps = [s["at"] for s in load_strokes()]
    report = tempo_report(stamps)
    print(verdict(report))          # "healthy"
    print(report.score)             # 0.94
    print(report.stall_count)       # 0
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_TARGET_INTERVAL = 30.0      # seconds — expected cadence
DEFAULT_STALL_THRESHOLD = 300.0     # seconds — 5 min, ~10× cadence
DEFAULT_RECENT_WINDOW = 50          # how many recent intervals to compare
DEFAULT_BASELINE_WINDOW = 200       # how many historical intervals


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class TempoReport:
    """Result of a tempo analysis."""

    total_strokes: int = 0
    total_intervals: int = 0
    mean_interval: float = 0.0
    median_interval: float = 0.0
    stdev_interval: float = 0.0
    p10_interval: float = 0.0
    p90_interval: float = 0.0
    min_interval: float = 0.0
    max_interval: float = 0.0
    stall_count: int = 0
    stall_gaps: List[float] = field(default_factory=list)
    recent_mean: float = 0.0
    baseline_mean: float = 0.0
    drift_ratio: float = 0.0        # recent / baseline; 1.0 = no drift
    score: float = 1.0              # 0.0 – 1.0

    @property
    def is_stalling(self) -> bool:
        return self.stall_count > 0

    @property
    def is_dead(self) -> bool:
        """Writer is probably dead if the last stroke is very old."""
        return self.total_strokes < 2 or self.score < 0.2


# ---------------------------------------------------------------------------
# core helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    # Python 3.11+ handles the Z suffix; for older versions we replace it.
    cleaned = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def _intervals(timestamps: Sequence[str]) -> List[float]:
    """Compute intervals (seconds) between consecutive timestamps."""
    if len(timestamps) < 2:
        return []
    dts = [_parse_iso(t) for t in timestamps]
    return [(dts[i + 1] - dts[i]).total_seconds() for i in range(len(dts) - 1)]


def _percentile(data: List[float], pct: float) -> float:
    """Simple percentile without numpy."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def _compute_score(
    intervals: List[float],
    target: float,
    stall_threshold: float,
) -> float:
    """Compute a 0.0 – 1.0 health score.

    Deductions:
    - variance penalty:  up to 0.3 for high stdev relative to target
    - stall penalty:     0.05 per stall, capped at 0.4
    - drift penalty:     up to 0.2 for mean far from target
    """
    if not intervals:
        return 0.0

    score = 1.0
    mean = statistics.mean(intervals)

    # variance penalty — coefficient of variation capped at 1.0
    try:
        stdev = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
    except statistics.StatisticsError:
        stdev = 0.0
    cv = min(stdev / max(target, 1.0), 1.0)
    score -= cv * 0.3

    # stall penalty
    stalls = [iv for iv in intervals if iv > stall_threshold]
    score -= min(len(stalls) * 0.05, 0.4)

    # drift penalty — how far the mean is from target (relative)
    drift = abs(mean - target) / max(target, 1.0)
    score -= min(drift * 0.2, 0.2)

    return max(0.0, round(score, 4))


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def tempo_report(
    timestamps: Sequence[str],
    *,
    target: float = DEFAULT_TARGET_INTERVAL,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
) -> TempoReport:
    """Analyse the tempo of a sequence of stroke timestamps.

    Parameters
    ----------
    timestamps : sequence of ISO-8601 strings
    target : expected interval in seconds (default 30)
    stall_threshold : seconds above which an interval is a stall
    recent_window : number of trailing intervals for "recent" stats
    baseline_window : number of intervals before the recent window

    Returns
    -------
    TempoReport
    """
    if not timestamps:
        return TempoReport()

    intervals = _intervals(timestamps)
    if not intervals:
        return TempoReport(total_strokes=len(timestamps))

    n = len(intervals)
    mean_iv = statistics.mean(intervals)
    median_iv = statistics.median(intervals)
    stdev_iv = statistics.stdev(intervals) if n > 1 else 0.0
    p10 = _percentile(intervals, 10)
    p90 = _percentile(intervals, 90)

    stalls = [iv for iv in intervals if iv > stall_threshold]

    # recent vs baseline
    recent = intervals[-recent_window:] if n >= recent_window else intervals
    baseline_start = max(0, n - recent_window - baseline_window)
    baseline_end = max(0, n - recent_window)
    baseline = intervals[baseline_start:baseline_end] if baseline_end > baseline_start else intervals

    recent_mean = statistics.mean(recent) if recent else 0.0
    baseline_mean = statistics.mean(baseline) if baseline else 0.0
    drift_ratio = recent_mean / baseline_mean if baseline_mean > 0 else 1.0

    score = _compute_score(intervals, target, stall_threshold)

    return TempoReport(
        total_strokes=len(timestamps),
        total_intervals=n,
        mean_interval=round(mean_iv, 2),
        median_interval=round(median_iv, 2),
        stdev_interval=round(stdev_iv, 2),
        p10_interval=round(p10, 2),
        p90_interval=round(p90, 2),
        min_interval=round(min(intervals), 2),
        max_interval=round(max(intervals), 2),
        stall_count=len(stalls),
        stall_gaps=[round(s, 2) for s in stalls],
        recent_mean=round(recent_mean, 2),
        baseline_mean=round(baseline_mean, 2),
        drift_ratio=round(drift_ratio, 4),
        score=score,
    )


def verdict(report: TempoReport) -> str:
    """Return a human-friendly health label.

    - ``"dead"``     — fewer than 2 strokes or score < 0.2
    - ``"stalling"`` — any stall detected
    - ``"wobbling"`` — score < 0.7
    - ``"healthy"``  — everything else
    """
    if report.is_dead:
        return "dead"
    if report.is_stalling:
        return "stalling"
    if report.score < 0.7:
        return "wobbling"
    return "healthy"


def tempo_summary(report: TempoReport) -> str:
    """One-line human-readable summary."""
    v = verdict(report)
    return (
        f"{v}: {report.total_strokes} strokes, "
        f"mean {report.mean_interval:.1f}s, "
        f"median {report.median_interval:.1f}s, "
        f"{report.stall_count} stall(s), "
        f"score {report.score:.2f}"
    )


def tempo_from_jsonl(
    path: str | Path,
    *,
    target: float = DEFAULT_TARGET_INTERVAL,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    max_strokes: int = 0,
) -> TempoReport:
    """Read a JSONL file and produce a tempo report.

    Parameters
    ----------
    path : path to strokes.jsonl
    max_strokes : if > 0, only use the last N strokes (for large files)
    """
    p = Path(path)
    if not p.exists():
        return TempoReport()

    timestamps: list[str] = []
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            ts = obj.get("at")
            if ts:
                timestamps.append(ts)

    if max_strokes > 0 and len(timestamps) > max_strokes:
        timestamps = timestamps[-max_strokes:]

    return tempo_report(
        timestamps,
        target=target,
        stall_threshold=stall_threshold,
        recent_window=recent_window,
        baseline_window=baseline_window,
    )


def find_stalls(
    timestamps: Sequence[str],
    stall_threshold: float = DEFAULT_STALL_THRESHOLD,
) -> list[dict]:
    """Return a list of stall events with start, end, and duration.

    Each entry::

        {"from": "2026-10-17T01:00:00+00:00",
         "to":   "2026-10-17T01:15:00+00:00",
         "seconds": 900.0}
    """
    if len(timestamps) < 2:
        return []
    stalls: list[dict] = []
    dts = [_parse_iso(t) for t in timestamps]
    for i in range(len(dts) - 1):
        gap = (dts[i + 1] - dts[i]).total_seconds()
        if gap > stall_threshold:
            stalls.append({
                "from": timestamps[i],
                "to": timestamps[i + 1],
                "seconds": round(gap, 2),
            })
    return stalls
