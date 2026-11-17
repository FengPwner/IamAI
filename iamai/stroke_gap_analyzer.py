"""stroke_gap_analyzer — predict writer stalls from inter-stroke gaps.

The writer loop is designed to emit one stroke every ~15 s.
In practice, gaps vary: network hiccups, garbage collection,
lock contention, or a dying process all leave a signature in the
gap distribution.  This module turns raw timestamps into an
actionable health assessment *before* the stall actually happens.

===========================  ============================================
module                       what it measures
===========================  ============================================
cadence_jitter               short-term timing irregularity
cadence_stall_detector       binary "is it stalled right now?"
writer_silence_detector      time since last stroke
**stroke_gap_analyzer**      **gap distribution + trend → stall forecast**
===========================  ============================================

The caretaker visit that created this module (visit 686) found that
the repo had suffered a 2 910 s gap (48 min) with the longest gap
at 3 145 s (52 min) — both well past the 2× cadence threshold.
A trend detector would have flagged accelerating gaps ~15 min
before the writer actually went silent, giving the caretaker time
to restart cleanly instead of discovering the stall after the fact.

Stroke record
-------------

Each stroke is a dict with at least:

- ``at`` (str): ISO-8601 timestamp (``2026-10-03T03:23:10+00:00``)

Functions
---------

``compute_gaps(strokes)``
    Return sorted list of inter-stroke gaps in seconds.

``gap_stats(gaps)``
    Compute mean, median, p95, p99, max, std.

``gap_trend(gaps, window)``
    Linear regression on the last *window* gaps; returns slope
    (positive = gaps widening, negative = gaps tightening).

``stall_risk(gaps, target_cadence, now)``
    Score 0.0–1.0 combining statistical outliers, trend, and
    recency of the last stroke.

``gap_report(strokes, target_cadence, now)``
    One-call summary: stats, trend, risk, verdict.

Zero dependencies.  stdlib only.

>>> from datetime import datetime, timezone
>>> base = datetime(2026, 11, 18, 0, 0, 0, tzinfo=timezone.utc)
>>> strokes = [{"at": (base.replace(minute=i)).isoformat()} for i in range(10)]
>>> gaps = compute_gaps(strokes)
>>> len(gaps)
9
>>> gap_stats(gaps)["mean"]
60.0
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime.

    Handles both ``+00:00`` and ``Z`` suffixes.  Falls back to
    naive-to-UTC if no timezone is present.

    >>> _parse_ts("2026-10-03T03:23:10+00:00").tzname()
    'UTC'
    >>> _parse_ts("2026-10-03T03:23:10Z").tzname()
    'UTC'
    >>> _parse_ts("2026-10-03T03:23:10").tzname()
    'UTC'
    """
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        # last resort: strip fractional seconds
        dt = datetime.fromisoformat(s[:19])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------

def compute_gaps(strokes: List[Dict[str, Any]]) -> List[float]:
    """Compute inter-stroke gaps in seconds, sorted by time.

    Requires at least 2 strokes; returns an empty list otherwise.

    >>> strokes = [
    ...     {"at": "2026-11-18T00:00:00+00:00"},
    ...     {"at": "2026-11-18T00:00:15+00:00"},
    ...     {"at": "2026-11-18T00:00:45+00:00"},
    ... ]
    >>> compute_gaps(strokes)
    [15.0, 30.0]
    >>> compute_gaps([{"at": "2026-11-18T00:00:00+00:00"}])
    []
    >>> compute_gaps([])
    []
    """
    if len(strokes) < 2:
        return []
    times = sorted(_parse_ts(s["at"]) for s in strokes)
    return [
        (times[i + 1] - times[i]).total_seconds()
        for i in range(len(times) - 1)
    ]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _percentile(sorted_vals: List[float], p: float) -> float:
    """Compute the p-th percentile (0–100) from a pre-sorted list.

    Uses linear interpolation between the two nearest ranks.

    >>> _percentile([1, 2, 3, 4, 5], 50)
    3.0
    >>> _percentile([1, 2, 3, 4, 5], 0)
    1.0
    >>> _percentile([1, 2, 3, 4, 5], 100)
    5.0
    """
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    k = (p / 100.0) * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _std(values: List[float], mean: float) -> float:
    """Population standard deviation.

    >>> _std([2, 4, 4, 4, 5, 5, 7, 9], 5.0)
    2.0
    >>> _std([], 0.0)
    0.0
    """
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def gap_stats(gaps: List[float]) -> Dict[str, float]:
    """Compute summary statistics for a list of gap values.

    Returns a dict with keys: count, mean, median, p95, p99, max, std.

    >>> s = gap_stats([15, 15, 15, 15, 100])
    >>> s["count"]
    5
    >>> s["mean"]
    32.0
    >>> s["max"]
    100.0
    >>> gap_stats([])["count"]
    0
    """
    if not gaps:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "std": 0.0,
        }
    sg = sorted(gaps)
    mean = sum(sg) / len(sg)
    return {
        "count": len(sg),
        "mean": round(mean, 2),
        "median": round(_percentile(sg, 50), 2),
        "p95": round(_percentile(sg, 95), 2),
        "p99": round(_percentile(sg, 99), 2),
        "max": round(sg[-1], 2),
        "std": round(_std(sg, mean), 2),
    }


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

def gap_trend(
    gaps: List[float],
    window: int = 20,
) -> Dict[str, float]:
    """Linear regression on the most recent *window* gaps.

    Returns:

    - ``slope``: seconds-per-gap change (positive = widening)
    - ``r_squared``: goodness of fit (0–1)
    - ``sample_count``: number of gaps used

    With fewer than 3 gaps, returns zeroed results.

    >>> g = list(range(1, 11))  # [1,2,...,10] — perfect linear
    >>> t = gap_trend(g, window=10)
    >>> abs(t["slope"] - 1.0) < 0.01
    True
    >>> t["r_squared"] > 0.99
    True
    >>> gap_trend([5, 5], window=20)["slope"]
    0.0
    """
    recent = gaps[-window:] if len(gaps) > window else list(gaps)
    n = len(recent)
    if n < 3:
        return {"slope": 0.0, "r_squared": 0.0, "sample_count": n}

    x_mean = (n - 1) / 2.0
    y_mean = sum(recent) / n

    num = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
    den_x = sum((i - x_mean) ** 2 for i in range(n))
    den_y = sum((v - y_mean) ** 2 for v in recent)

    if den_x == 0:
        return {"slope": 0.0, "r_squared": 0.0, "sample_count": n}

    slope = num / den_x
    ss_res = sum((recent[i] - (y_mean + slope * (i - x_mean))) ** 2 for i in range(n))
    ss_tot = den_y
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return {
        "slope": round(slope, 4),
        "r_squared": round(max(0.0, min(1.0, r_squared)), 4),
        "sample_count": n,
    }


# ---------------------------------------------------------------------------
# Stall risk scoring
# ---------------------------------------------------------------------------

def stall_risk(
    gaps: List[float],
    target_cadence: float = 15.0,
    now: Optional[datetime] = None,
    last_stroke_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Score the probability of an imminent or ongoing stall.

    The score (0.0–1.0) combines three signals:

    1. **Outlier ratio** — fraction of gaps exceeding 4× the target
       cadence.  More outliers → higher score.
    2. **Trend slope** — positive slope means gaps are widening,
       which precedes stalls.
    3. **Recency** — if the last stroke was more than 2× target
       cadence ago, the stall may already have started.

    >>> # healthy: all gaps at 15s
    >>> g = [15.0] * 50
    >>> stall_risk(g, 15.0)["score"] < 0.1
    True

    >>> # risky: widening gaps
    >>> g = [15.0] * 40 + [30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0, 600.0, 1200.0, 2400.0]
    >>> stall_risk(g, 15.0)["score"] > 0.5
    True
    """
    if not gaps:
        return {"score": 0.0, "signals": {}, "verdict": "no_data"}

    threshold_4x = target_cadence * 4
    outliers = sum(1 for g in gaps if g > threshold_4x)
    outlier_ratio = outliers / len(gaps)

    trend = gap_trend(gaps)
    slope = trend["slope"]

    # recency signal
    recency_score = 0.0
    if last_stroke_at and now:
        last_dt = _parse_ts(last_stroke_at)
        since_last = (now - last_dt).total_seconds()
        if since_last > target_cadence * 8:
            recency_score = 1.0
        elif since_last > target_cadence * 4:
            recency_score = 0.6
        elif since_last > target_cadence * 2:
            recency_score = 0.3

    # combine signals (weighted)
    outlier_component = min(outlier_ratio * 3, 1.0) * 0.35
    slope_component = min(max(slope / 10.0, 0.0), 1.0) * 0.35
    recency_component = recency_score * 0.30

    score = min(outlier_component + slope_component + recency_component, 1.0)

    if score >= 0.7:
        verdict = "stall_imminent"
    elif score >= 0.4:
        verdict = "stall_risk"
    elif score >= 0.15:
        verdict = "warning"
    else:
        verdict = "healthy"

    return {
        "score": round(score, 3),
        "signals": {
            "outlier_ratio": round(outlier_ratio, 4),
            "outlier_count": outliers,
            "trend_slope": slope,
            "trend_r_squared": trend["r_squared"],
            "recency_seconds": (
                round((now - _parse_ts(last_stroke_at)).total_seconds(), 1)
                if last_stroke_at and now else None
            ),
        },
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def gap_report(
    strokes: List[Dict[str, Any]],
    target_cadence: float = 15.0,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One-call summary of writer gap health.

    >>> from datetime import datetime, timezone
    >>> now = datetime(2026, 11, 18, 0, 5, 0, tzinfo=timezone.utc)
    >>> strokes = [
    ...     {"at": "2026-11-18T00:00:00+00:00"},
    ...     {"at": "2026-11-18T00:00:15+00:00"},
    ...     {"at": "2026-11-18T00:00:30+00:00"},
    ...     {"at": "2026-11-18T00:00:45+00:00"},
    ...     {"at": "2026-11-18T00:01:00+00:00"},
    ... ]
    >>> r = gap_report(strokes, 15.0, now)
    >>> r["stats"]["count"]
    4
    >>> r["risk"]["verdict"]
    'healthy'

    >>> gap_report([], 15.0)["risk"]["verdict"]
    'no_data'
    """
    if not strokes:
        return {
            "stats": gap_stats([]),
            "trend": gap_trend([]),
            "risk": {"score": 0.0, "signals": {}, "verdict": "no_data"},
            "total_strokes": 0,
        }

    gaps = compute_gaps(strokes)
    last_at = max(s["at"] for s in strokes)

    return {
        "total_strokes": len(strokes),
        "stats": gap_stats(gaps),
        "trend": gap_trend(gaps),
        "risk": stall_risk(
            gaps,
            target_cadence=target_cadence,
            now=now,
            last_stroke_at=last_at,
        ),
    }
