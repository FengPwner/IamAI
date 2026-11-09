#!/usr/bin/env python3
"""gap_regularity — classify writer rhythm from inter-stroke intervals.

A disciplined auto-writer should tick at a steady cadence.  When the
rhythm degrades it is usually a symptom, not the disease: the process
stalled, the network dropped, or the batch committer locked the index.
This module turns a list of timestamps into a **regularity verdict**
so a caretaker can tell at a glance whether the writer is humming,
drifting, or broken.

Metrics
-------

===============  ============================================================
metric           meaning
===============  ============================================================
count            number of gaps analysed (timestamps − 1).
mean_gap         arithmetic mean of inter-stroke gaps in seconds.
median_gap       median gap — robust to outlier stalls.
std_gap          standard deviation of gaps.
cv               coefficient of variation ``std / mean``.  0 = perfectly
                 regular; >1 indicates heavy-tailed or bimodal gaps.
p95_gap          95th-percentile gap — the "worst case" a caretaker
                 actually feels.
autocorr_lag1    lag-1 autocorrelation of the gap series.  Positive
                 values mean "long gaps cluster" (burst-and-pause);
                 near zero means each gap is independent.
burst_ratio      fraction of gaps exceeding ``2 × median_gap``.
                 0 = every gap is reasonable; 1 = nothing but stalls.
regularity_score weighted composite in [0, 1]:
                 ``0.30*(1-clamp(cv,0,1)) + 0.25*(1-burst_ratio)
                 + 0.25*(1-clamp(autocorr_lag1,0,1))
                 + 0.20*(1-clamp(p95_gap/max_expected,0,1))``
verdict          ``clockwork`` | ``steady`` | ``organic`` | ``erratic``
                 | ``stalled``.
===============  ============================================================

Public API
----------

>>> from iamai.gap_regularity import analyse_gaps
>>> report = analyse_gaps(timestamps)
>>> report["verdict"]
'steady'

>>> summary = regularity_summary(timestamps, windows=[50, 200])
>>> summary["trend"]
'improving'
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

# A gap longer than this (seconds) is "probably a stall, not a pause".
DEFAULT_MAX_EXPECTED = 1200  # 20 minutes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_epoch(ts: Union[int, float, str, datetime]) -> float:
    """Coerce a timestamp to a POSIX float (seconds since epoch)."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    if isinstance(ts, str):
        # Try ISO-8601 first, then fall back to a few common formats.
        _tz_fmts = {"%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"}
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                dt = datetime.strptime(ts, fmt)
                if fmt not in _tz_fmts and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
        # Last resort: let fromisoformat try.
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise TypeError(f"unsupported timestamp type: {type(ts)}")


def _gaps(timestamps: Sequence[float]) -> List[float]:
    """Compute sorted-positive inter-stroke gaps from epoch floats."""
    if len(timestamps) < 2:
        return []
    raw = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    # Drop negative or zero gaps (clock skew, duplicate strokes).
    return [g for g in raw if g > 0]


def _autocorr_lag1(series: List[float]) -> float:
    """Lag-1 autocorrelation of a numeric series.  Returns 0 when undefined."""
    n = len(series)
    if n < 3:
        return 0.0
    mean = statistics.mean(series)
    var = sum((x - mean) ** 2 for x in series)
    if var == 0:
        return 0.0
    cov = sum((series[i] - mean) * (series[i + 1] - mean) for i in range(n - 1))
    return cov / var


def _percentile(values: List[float], p: float) -> float:
    """Simple linear-interpolation percentile (p in 0..100)."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (p / 100.0) * (len(s) - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_gaps(
    timestamps: Sequence[Union[int, float, str, datetime]],
    max_expected: float = DEFAULT_MAX_EXPECTED,
) -> Dict[str, Any]:
    """Analyse inter-stroke gap regularity.

    Parameters
    ----------
    timestamps : sequence
        Chronologically ordered stroke timestamps.
    max_expected : float
        Seconds beyond which a gap is considered a stall.

    Returns
    -------
    dict
        Full regularity report.
    """
    epochs = sorted(_to_epoch(t) for t in timestamps)
    gaps = _gaps(epochs)

    if len(gaps) < 2:
        return _empty_report(len(epochs))

    mean_gap = statistics.mean(gaps)
    median_gap = statistics.median(gaps)
    std_gap = statistics.pstdev(gaps)  # population — we have the full window
    cv = std_gap / mean_gap if mean_gap > 0 else 0.0
    p95 = _percentile(gaps, 95)
    autocorr = _autocorr_lag1(gaps)
    burst_threshold = 2.0 * median_gap
    burst_ratio = sum(1 for g in gaps if g > burst_threshold) / len(gaps)

    # Composite score — higher is more regular.
    regularity_score = round(
        0.30 * (1.0 - _clamp(cv))
        + 0.25 * (1.0 - burst_ratio)
        + 0.25 * (1.0 - _clamp(autocorr))
        + 0.20 * (1.0 - _clamp(p95 / max_expected)),
        4,
    )

    verdict = _classify(regularity_score, cv, burst_ratio, autocorr, mean_gap, median_gap)

    return {
        "count": len(gaps),
        "mean_gap": round(mean_gap, 2),
        "median_gap": round(median_gap, 2),
        "std_gap": round(std_gap, 2),
        "cv": round(cv, 4),
        "p95_gap": round(p95, 2),
        "autocorr_lag1": round(autocorr, 4),
        "burst_ratio": round(burst_ratio, 4),
        "regularity_score": regularity_score,
        "verdict": verdict,
    }


def regularity_summary(
    timestamps: Sequence[Union[int, float, str, datetime]],
    windows: Optional[List[int]] = None,
    max_expected: float = DEFAULT_MAX_EXPECTED,
) -> Dict[str, Any]:
    """Multi-window summary with trend detection.

    Parameters
    ----------
    timestamps : sequence
        Full chronological stroke timestamps.
    windows : list of int, optional
        Window sizes (most-recent N strokes) to analyse.
        Default: ``[50, 200]``.

    Returns
    -------
    dict
        ``{windows: {n: report, ...}, trend}`` where trend is
        ``improving``, ``stable``, or ``degrading``.
    """
    if windows is None:
        windows = [50, 200]

    epochs = sorted(_to_epoch(t) for t in timestamps)
    results: Dict[int, Dict[str, Any]] = {}
    for w in windows:
        subset = epochs[-w:] if len(epochs) >= w else epochs
        results[w] = analyse_gaps(subset, max_expected=max_expected)

    # Trend: compare the smallest window score to the largest.
    sizes = sorted(results.keys())
    if len(sizes) >= 2:
        recent_score = results[sizes[0]]["regularity_score"]
        older_score = results[sizes[-1]]["regularity_score"]
        delta = recent_score - older_score
        if delta > 0.05:
            trend = "improving"
        elif delta < -0.05:
            trend = "degrading"
        else:
            trend = "stable"
    else:
        trend = "insufficient"

    return {"windows": results, "trend": trend}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(
    score: float,
    cv: float,
    burst_ratio: float,
    autocorr: float,
    mean_gap: float,
    median_gap: float,
) -> str:
    """Map metrics to a human-readable verdict."""
    # Stalled: most gaps are huge, regardless of regularity.
    if median_gap > DEFAULT_MAX_EXPECTED:
        return "stalled"
    # High autocorrelation with high CV means burst-pause pattern.
    if autocorr > 0.5 and cv > 1.0:
        return "stalled"
    if score >= 0.80:
        return "clockwork"
    if score >= 0.60:
        return "steady"
    if score >= 0.35:
        return "organic"
    return "erratic"


def _empty_report(sample_count: int) -> Dict[str, Any]:
    """Return a zeroed report when there are too few gaps to analyse."""
    return {
        "count": max(sample_count - 1, 0),
        "mean_gap": 0.0,
        "median_gap": 0.0,
        "std_gap": 0.0,
        "cv": 0.0,
        "p95_gap": 0.0,
        "autocorr_lag1": 0.0,
        "burst_ratio": 0.0,
        "regularity_score": 0.0,
        "verdict": "insufficient",
    }


# ---------------------------------------------------------------------------
# CLI shortcut
# ---------------------------------------------------------------------------

def brief(report: Dict[str, Any]) -> str:
    """One-line human summary of a regularity report."""
    s = report["regularity_score"]
    v = report["verdict"]
    n = report["count"]
    med = report["median_gap"]
    return f"regularity={s:.2f} ({v}) · {n} gaps · median={med:.0f}s"
