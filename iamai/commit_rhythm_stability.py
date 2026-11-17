#!/usr/bin/env python3
"""commit_rhythm_stability — measure how steady the commit heartbeat is.

A well-tuned autowrite pipeline commits at roughly regular intervals.
The *rhythm* is the sequence of inter-commit gaps; *stability* is how
tightly those gaps cluster around their median.

Why median, not mean?
    Commit gaps are right-skewed: most are near the target cadence,
    but occasional long gaps (network stalls, process deaths) pull the
    mean upward.  The median resists these outliers and reflects the
    *typical* gap.

Metrics
-------
Given a sorted list of commit timestamps ``[t₀, t₁, …, tₙ]``:

- ``gaps``:           list of ``tᵢ₊₁ − tᵢ`` for i in 0..n−1
- ``median_gap_s``:   median of gaps
- ``mad_gap_s``:      median absolute deviation of gaps
- ``cv``:             coefficient of variation = std(gaps) / mean(gaps)
- ``robust_cv``:      mad / median  (outlier-resistant CV analogue)
- ``p95_gap_s``:      95th-percentile gap
- ``max_gap_s``:      longest single gap
- ``stability_score``: 0–100 score; 100 = perfectly regular

Stability score
---------------
The score maps ``robust_cv`` to a 0–100 scale:

=========  ===========  =============================================
score      robust_cv    interpretation
=========  ===========  =============================================
90–100     < 0.10       metronomic — gaps barely vary
70–89      < 0.30       steady — normal jitter, nothing to investigate
50–69      < 0.60       wobbly — noticeable irregularity, worth a look
30–49      < 1.00       erratic — rhythm is breaking down
0–29       >= 1.00      chaotic — no discernible pattern
=========  ===========  =============================================

Formula::

    score = max(0, 100 − 100 × robust_cv)   (clamped to [0, 100])

This is intentionally linear: each 0.01 increase in robust_cv costs
one point.  A robust_cv of 1.0 (MAD equals the median) means the
rhythm is so irregular that the typical deviation is as large as the
typical gap itself — score zero.

Anomaly detection
-----------------
A gap is flagged as *anomalous* when it exceeds::

    median_gap + 3 × mad_gap

This threshold is generous: it only flags gaps that are truly far
outside the normal distribution, avoiding false positives from
minor cadence adjustments.

Edge cases
----------
- Fewer than 2 timestamps → no gaps → returns a sentinel report with
  ``stability_score = -1`` (insufficient data).
- All gaps identical → ``mad = 0``, ``robust_cv = 0``, score = 100.
- Single gap → ``mad = 0`` (trivially stable).

Usage::

    from iamai.commit_rhythm_stability import analyze_rhythm

    timestamps = [1000, 1600, 2210, 2800, 3450, 4020]
    report = analyze_rhythm(timestamps)
    print(report["stability_score"])  # e.g. 92.3
    print(report["tier"])             # "metronomic"
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Sequence


def _compute_gaps(timestamps: Sequence[float]) -> List[float]:
    """Return sorted list of inter-commit gaps in seconds."""
    ts = sorted(timestamps)
    return [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]


def _percentile(data: List[float], pct: float) -> float:
    """Compute the pct-th percentile of a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[int(f)] * (c - k) + data[int(c)] * (k - f)


def _tier_for_score(score: float) -> str:
    """Map a stability score to its qualitative tier."""
    if score < 0:
        return "insufficient_data"
    if score >= 90:
        return "metronomic"
    if score >= 70:
        return "steady"
    if score >= 50:
        return "wobbly"
    if score >= 30:
        return "erratic"
    return "chaotic"


def analyze_rhythm(
    timestamps: Sequence[float],
    anomaly_sigma: float = 3.0,
) -> Dict[str, Any]:
    """Analyze the commit rhythm from a sequence of timestamps.

    Parameters
    ----------
    timestamps:
        Unix timestamps (seconds) of commits, in any order.
        Must contain at least 2 values to produce a meaningful report.
    anomaly_sigma:
        Number of MADs above the median at which a gap is flagged
        as anomalous.  Default 3.0.

    Returns
    -------
    dict with keys:
        n_commits, n_gaps, gaps, median_gap_s, mad_gap_s,
        mean_gap_s, std_gap_s, cv, robust_cv, p95_gap_s,
        max_gap_s, min_gap_s, stability_score, tier,
        anomalous_gaps, n_anomalies.
    """
    ts_list = list(timestamps)
    n_commits = len(ts_list)

    if n_commits < 2:
        return {
            "n_commits": n_commits,
            "n_gaps": 0,
            "gaps": [],
            "median_gap_s": 0.0,
            "mad_gap_s": 0.0,
            "mean_gap_s": 0.0,
            "std_gap_s": 0.0,
            "cv": 0.0,
            "robust_cv": 0.0,
            "p95_gap_s": 0.0,
            "max_gap_s": 0.0,
            "min_gap_s": 0.0,
            "stability_score": -1.0,
            "tier": "insufficient_data",
            "anomalous_gaps": [],
            "n_anomalies": 0,
        }

    gaps = _compute_gaps(ts_list)
    n_gaps = len(gaps)
    sorted_gaps = sorted(gaps)

    median_gap = statistics.median(gaps)
    mean_gap = statistics.mean(gaps)

    # Median absolute deviation
    abs_devs = sorted([abs(g - median_gap) for g in gaps])
    mad_gap = statistics.median(abs_devs)

    # Standard deviation (population-style for consistency)
    if n_gaps > 1:
        std_gap = statistics.stdev(gaps)
    else:
        std_gap = 0.0

    # Coefficient of variation (classic)
    cv = std_gap / mean_gap if mean_gap > 0 else 0.0

    # Robust CV (MAD / median)
    robust_cv = mad_gap / median_gap if median_gap > 0 else 0.0

    # Percentiles
    p95_gap = _percentile(sorted_gaps, 95)
    max_gap = sorted_gaps[-1]
    min_gap = sorted_gaps[0]

    # Stability score
    raw_score = 100.0 - 100.0 * robust_cv
    stability_score = max(0.0, min(100.0, raw_score))

    tier = _tier_for_score(stability_score)

    # Anomaly detection
    threshold = median_gap + anomaly_sigma * mad_gap
    anomalous = [
        {"index": i, "gap_s": g, "ratio_to_median": g / median_gap if median_gap > 0 else 0.0}
        for i, g in enumerate(gaps)
        if g > threshold and mad_gap > 0
    ]

    return {
        "n_commits": n_commits,
        "n_gaps": n_gaps,
        "gaps": gaps,
        "median_gap_s": round(median_gap, 3),
        "mad_gap_s": round(mad_gap, 3),
        "mean_gap_s": round(mean_gap, 3),
        "std_gap_s": round(std_gap, 3),
        "cv": round(cv, 4),
        "robust_cv": round(robust_cv, 4),
        "p95_gap_s": round(p95_gap, 3),
        "max_gap_s": round(max_gap, 3),
        "min_gap_s": round(min_gap, 3),
        "stability_score": round(stability_score, 1),
        "tier": tier,
        "anomalous_gaps": anomalous,
        "n_anomalies": len(anomalous),
    }


def rhythm_summary_line(report: Dict[str, Any]) -> str:
    """One-line human-readable summary of a rhythm report."""
    if report["tier"] == "insufficient_data":
        return f"rhythm: insufficient data ({report['n_commits']} commits, need ≥2)"
    score = report["stability_score"]
    tier = report["tier"]
    med = report["median_gap_s"]
    n_anom = report["n_anomalies"]
    return (
        f"rhythm: {tier} (score {score}, median gap {med:.0f}s, "
        f"{report['n_gaps']} gaps, {n_anom} anomalies)"
    )
