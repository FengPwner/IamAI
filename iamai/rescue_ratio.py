"""Rescue ratio — is the system chronically distressed or mostly healthy?

A *rescue visit* is one where the caretaker had to restart at least one
process.  A *healthy visit* is one where everything was already running.
The rescue ratio is the fraction of recent visits that were rescues.

    ratio = rescue_visits / total_visits   (over a rolling window)

Interpretation::

    0.0        perfectly stable — every visit is observational
    0.0–0.2    healthy — occasional intervention
    0.2–0.5    stressed — frequent rescues, investigate root cause
    0.5–0.8    distressed — majority of visits are rescues
    0.8–1.0    critical — near-permanent failure, caretaker is a paramedic

The module also computes:

- **consecutive_rescues**: current streak of back-to-back rescue visits
- **trend**: is the ratio improving, flat, or worsening? (comparing two
  consecutive windows)
- **mean_time_between_rescues**: average seconds between rescue events

Usage::

    from iamai.rescue_ratio import RescueAnalyser

    analyser = RescueAnalyser(window=20)

    # feed visit records (list of dicts with "kind" key: "rescue" | "healthy")
    visits = [
        {"kind": "rescue", "ts": "2026-10-19T01:00:00+08:00"},
        {"kind": "healthy", "ts": "2026-10-19T02:00:00+08:00"},
        ...
    ]

    report = analyser.analyse(visits)
    print(report["ratio"])             # 0.0–1.0
    print(report["severity"])          # "stable" | "healthy" | "stressed" | ...
    print(report["consecutive_rescues"])  # int
    print(report["trend"])             # "improving" | "flat" | "worsening"
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


# Severity thresholds — each tuple is (lower_exclusive, upper_inclusive, label)
# "stable" is a special case: ratio == 0.0 exactly
_SEVERITY_BANDS = [
    (0.8, "critical"),
    (0.5, "distressed"),
    (0.2, "stressed"),
]


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a datetime object."""
    # Handle both +08:00 and Z suffixes
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def rescue_ratio(visits: List[Dict[str, Any]], window: int = 20) -> float:
    """Return the fraction of rescue visits in the last *window* visits.

    Each visit dict must have a ``"kind"`` key with value ``"rescue"`` or
    ``"healthy"``.  Returns 0.0 if *visits* is empty.
    """
    if not visits:
        return 0.0
    recent = visits[-window:]
    rescue_count = sum(1 for v in recent if v.get("kind") == "rescue")
    return rescue_count / len(recent)


def severity(ratio: float) -> str:
    """Classify a rescue ratio into a severity band.

    >>> severity(0.0)
    'stable'
    >>> severity(0.15)
    'healthy'
    >>> severity(0.35)
    'stressed'
    >>> severity(0.6)
    'distressed'
    >>> severity(0.9)
    'critical'
    """
    if ratio <= 0.0:
        return "stable"
    for threshold, label in _SEVERITY_BANDS:
        if ratio >= threshold:
            return label
    return "healthy"


def consecutive_rescues(visits: List[Dict[str, Any]]) -> int:
    """Count the current streak of back-to-back rescue visits from the tail.

    Returns 0 if the most recent visit was healthy, or if *visits* is empty.
    """
    if not visits:
        return 0
    count = 0
    for v in reversed(visits):
        if v.get("kind") == "rescue":
            count += 1
        else:
            break
    return count


def mean_time_between_rescues(
    visits: List[Dict[str, Any]],
) -> Optional[float]:
    """Return the mean seconds between consecutive rescue visits.

    Returns ``None`` if fewer than 2 rescue visits exist.
    """
    rescue_timestamps: List[float] = []
    for v in visits:
        if v.get("kind") == "rescue" and "ts" in v:
            dt = _parse_ts(v["ts"])
            rescue_timestamps.append(dt.timestamp())

    if len(rescue_timestamps) < 2:
        return None

    rescue_timestamps.sort()
    gaps = [
        rescue_timestamps[i + 1] - rescue_timestamps[i]
        for i in range(len(rescue_timestamps) - 1)
    ]
    return sum(gaps) / len(gaps)


def trend(
    visits: List[Dict[str, Any]],
    window: int = 20,
) -> str:
    """Compare the rescue ratio of two consecutive windows.

    Returns ``"improving"`` if the recent window has a lower ratio than the
    previous one, ``"worsening"`` if higher, and ``"flat"`` if unchanged.
    Requires at least ``2 * window`` visits for a meaningful comparison;
    returns ``"flat"`` otherwise.
    """
    if len(visits) < 2 * window:
        return "flat"

    recent = visits[-window:]
    previous = visits[-2 * window : -window]

    recent_ratio = sum(1 for v in recent if v.get("kind") == "rescue") / len(
        recent
    )
    previous_ratio = sum(
        1 for v in previous if v.get("kind") == "rescue"
    ) / len(previous)

    if recent_ratio < previous_ratio:
        return "improving"
    elif recent_ratio > previous_ratio:
        return "worsening"
    return "flat"


class RescueAnalyser:
    """Stateful analyser that produces a full report from visit records."""

    def __init__(self, window: int = 20):
        self.window = window

    def analyse(self, visits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a comprehensive rescue-health report.

        Keys:
            ratio, severity, consecutive_rescues, trend,
            mean_time_between_rescues, total_visits, window
        """
        r = rescue_ratio(visits, self.window)
        mtbr = mean_time_between_rescues(visits)
        return {
            "ratio": round(r, 4),
            "severity": severity(r),
            "consecutive_rescues": consecutive_rescues(visits),
            "trend": trend(visits, self.window),
            "mean_time_between_rescues": mtbr,
            "total_visits": len(visits),
            "window": self.window,
        }
