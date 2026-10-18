"""commit_interval — measure how regularly a repo commits over time.

A self-writing repository should commit like a metronome: steady,
predictable, boring.  Bursts and gaps are symptoms — bursts mean the
writer is catching up after a stall; gaps mean it stopped.

This module takes a sequence of commit timestamps and returns:

- mean interval (seconds between commits)
- interval std-dev
- coefficient of variation (std / mean)
- regularity score (0–1, where 1 = perfect metronome)
- longest gap and burst count
- an overall health label

Design
------

Regularity formula::

    cv = std(intervals) / mean(intervals)
    regularity = 1 / (1 + cv)

A perfectly regular cadence (every 600 s) gives cv = 0 → regularity = 1.
Wildly irregular (some gaps 10 s, others 3600 s) gives cv >> 1 →
regularity approaches 0.

Health labels
=============

==========  =====================================================
label       meaning
==========  =====================================================
metronome   regularity >= 0.85 — steady heartbeat
steady      regularity 0.60–0.85 — minor drift, healthy
irregular   regularity 0.35–0.60 — noticeable gaps or bursts
erratic     regularity < 0.35 — writer is stalling or crashing
==========  =====================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import math


# ── interval helpers ─────────────────────────────────────────────

def compute_intervals(timestamps: List[datetime]) -> List[float]:
    """Return sorted list of intervals (seconds) between consecutive commits.

    Timestamps need not be pre-sorted; we sort ascending first.
    Returns empty list if fewer than 2 timestamps.
    """
    if len(timestamps) < 2:
        return []
    ts = sorted(timestamps)
    return [(ts[i + 1] - ts[i]).total_seconds() for i in range(len(ts) - 1)]


def mean(values: List[float]) -> float:
    """Arithmetic mean."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def std_dev(values: List[float], ddof: int = 0) -> float:
    """Population (ddof=0) or sample (ddof=1) standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / max(n - ddof, 1)
    return math.sqrt(variance)


# ── core metrics ─────────────────────────────────────────────────

def regularity_score(intervals: List[float]) -> float:
    """Return regularity score in [0, 1].

    1.0 = perfectly regular (all intervals identical).
    Approaches 0 as intervals become wildly variable.
    """
    if not intervals:
        return 0.0
    m = mean(intervals)
    if m == 0:
        return 0.0
    cv = std_dev(intervals) / m
    return 1.0 / (1.0 + cv)


def health_label(regularity: float) -> str:
    """Classify regularity into a health label."""
    if regularity >= 0.85:
        return "metronome"
    if regularity >= 0.60:
        return "steady"
    if regularity >= 0.35:
        return "irregular"
    return "erratic"


def longest_gap(intervals: List[float]) -> float:
    """Return the longest single interval in seconds."""
    return max(intervals) if intervals else 0.0


def burst_count(intervals: List[float], threshold: float = 30.0) -> int:
    """Count how many consecutive pairs are tighter than *threshold* seconds.

    A burst is two commits within `threshold` seconds of each other.
    Three rapid-fire commits produce two burst pairs.
    """
    return sum(1 for iv in intervals if iv < threshold)


def interval_report(
    timestamps: List[datetime],
    burst_threshold: float = 30.0,
) -> Dict[str, Any]:
    """Produce a full interval health report.

    Parameters
    ----------
    timestamps : list of datetime
        Commit timestamps (any order, any timezone — we only care about
        relative differences).
    burst_threshold : float
        Seconds below which two consecutive commits count as a burst.

    Returns
    -------
    dict with keys:
        count, intervals, mean_interval, std_interval, cv,
        regularity, label, longest_gap, bursts
    """
    ivs = compute_intervals(timestamps)
    if not ivs:
        return {
            "count": len(timestamps),
            "intervals": 0,
            "mean_interval": 0.0,
            "std_interval": 0.0,
            "cv": 0.0,
            "regularity": 0.0,
            "label": "erratic",
            "longest_gap": 0.0,
            "bursts": 0,
        }

    m = mean(ivs)
    s = std_dev(ivs)
    cv = (s / m) if m > 0 else 0.0
    reg = regularity_score(ivs)

    return {
        "count": len(timestamps),
        "intervals": len(ivs),
        "mean_interval": round(m, 1),
        "std_interval": round(s, 1),
        "cv": round(cv, 3),
        "regularity": round(reg, 3),
        "label": health_label(reg),
        "longest_gap": round(longest_gap(ivs), 1),
        "bursts": burst_count(ivs, burst_threshold),
    }


# ── summary (for caretaker briefings) ────────────────────────────

def interval_summary(report: Dict[str, Any]) -> str:
    """One-line human-readable summary of an interval report."""
    n = report.get("count", 0)
    label = report.get("label", "unknown")
    reg = report.get("regularity", 0)
    gap = report.get("longest_gap", 0)
    bursts = report.get("bursts", 0)
    m = report.get("mean_interval", 0)
    return (
        f"{n} commits, regularity {reg:.3f} ({label}), "
        f"mean interval {m:.0f}s, longest gap {gap:.0f}s, "
        f"{bursts} burst(s)"
    )
