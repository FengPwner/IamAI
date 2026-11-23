"""stroke_length_drift — measure how stroke text length evolves over time.

A healthy automated writer produces strokes of roughly consistent length.
When the mean length drifts upward (verbosity creep) or downward (truncation
/ laziness), it signals a change in content-generation behaviour that the
caretaker should notice.

This module divides the recent strokes into equal-sized windows (buckets)
and fits a linear trend through the per-bucket mean lengths.  The slope
of that trend, normalised by the overall mean, gives a **drift rate** that
is comparable across writers and time periods.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             strokes analysed
bucket_count              number of buckets used
bucket_size               strokes per bucket
overall_mean_length       grand mean of all stroke text lengths
overall_std_length        standard deviation of stroke text lengths
bucket_means              list of mean lengths per bucket
trend_slope               per-bucket slope (characters per bucket)
drift_rate                trend_slope / overall_mean_length
                          (positive = growing, negative = shrinking)
stability_score           0–1 metric: 1.0 = no drift, 0.0 = extreme drift
stability_label           human-readable verdict
========================  =============================================

Stability labels
----------------

=============  =====================================================
score          label
=============  =====================================================
≥ 0.85         steady   — lengths are consistent, no meaningful drift
0.60 – 0.85    drifting — noticeable trend, worth monitoring
0.35 – 0.60    shifting — significant change in stroke length
< 0.35         unstable — dramatic length change, investigate
=============  =====================================================

The stability score is computed as::

    stability = 1 / (1 + (|drift_rate| / reference_drift) ** 2)

where ``reference_drift`` defaults to 0.10 (10 % change across the
window).  A drift_rate of ±0.10 yields a score of 0.5; ±0.05 yields
~0.8; ±0.20 yields ~0.2.

Usage::

    python3 -m iamai.stroke_length_drift               # last 200 strokes
    python3 -m iamai.stroke_length_drift -n 500        # last 500 strokes
    python3 -m iamai.stroke_length_drift --json         # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_N = 200
DEFAULT_BUCKET_COUNT = 10
REFERENCE_DRIFT = 0.10  # drift_rate at which stability = 0.5
DEFAULT_STROKES_PATH = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _load_strokes(path: Path, n: int) -> List[Dict[str, Any]]:
    """Load the last *n* strokes from a JSONL file."""
    strokes: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    return strokes[-n:]


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float], mean_val: Optional[float] = None) -> float:
    if len(values) < 2:
        return 0.0
    if mean_val is None:
        mean_val = _mean(values)
    variance = sum((v - mean_val) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _linear_slope(values: List[float]) -> float:
    """Return the slope of the ordinary-least-squares fit over indices 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0
    # x_i = i, y_i = values[i]
    x_mean = (n - 1) / 2.0
    y_mean = _mean(values)
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _bucket_means(lengths: List[int], bucket_count: int) -> List[float]:
    """Split *lengths* into *bucket_count* roughly equal chunks and return per-bucket means."""
    if not lengths or bucket_count <= 0:
        return []
    n = len(lengths)
    size = max(1, n // bucket_count)
    means: List[float] = []
    for i in range(bucket_count):
        start = i * size
        end = start + size if i < bucket_count - 1 else n
        chunk = lengths[start:end]
        if chunk:
            means.append(_mean([float(c) for c in chunk]))
    return means


def stability_score(drift_rate: float, reference: float = REFERENCE_DRIFT) -> float:
    """Compute stability score from absolute drift rate.

    Returns a value in [0, 1]:  1.0 = no drift,  0.0 = extreme drift.
    """
    x = abs(drift_rate) / reference
    return 1.0 / (1.0 + x * x)


def stability_label(score: float) -> str:
    """Classify a stability score into a human-readable label."""
    if score >= 0.85:
        return "steady"
    if score >= 0.60:
        return "drifting"
    if score >= 0.35:
        return "shifting"
    return "unstable"


def compute_drift(
    strokes: List[Dict[str, Any]],
    bucket_count: int = DEFAULT_BUCKET_COUNT,
) -> Dict[str, Any]:
    """Compute all drift metrics from a list of stroke dicts.

    Each stroke must have a ``"text"`` key.
    """
    if not strokes:
        return {
            "total_strokes": 0,
            "bucket_count": 0,
            "bucket_size": 0,
            "overall_mean_length": 0.0,
            "overall_std_length": 0.0,
            "bucket_means": [],
            "trend_slope": 0.0,
            "drift_rate": 0.0,
            "stability_score": 1.0,
            "stability_label": "steady",
        }

    lengths = [len(s.get("text", "")) for s in strokes]
    overall_mean = _mean([float(l) for l in lengths])
    overall_std = _std([float(l) for l in lengths], overall_mean)

    b_means = _bucket_means(lengths, bucket_count)
    slope = _linear_slope(b_means)
    drift_rate = (slope / overall_mean) if overall_mean > 0 else 0.0
    stab = stability_score(drift_rate)

    return {
        "total_strokes": len(strokes),
        "bucket_count": len(b_means),
        "bucket_size": max(1, len(lengths) // max(bucket_count, 1)),
        "overall_mean_length": round(overall_mean, 2),
        "overall_std_length": round(overall_std, 2),
        "bucket_means": [round(m, 2) for m in b_means],
        "trend_slope": round(slope, 4),
        "drift_rate": round(drift_rate, 4),
        "stability_score": round(stab, 4),
        "stability_label": stability_label(stab),
    }


# ---------------------------------------------------------------------------
# Report / summary
# ---------------------------------------------------------------------------


def drift_report(
    n: int = DEFAULT_N,
    bucket_count: int = DEFAULT_BUCKET_COUNT,
    strokes_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Full drift report from the on-disk strokes file."""
    path = strokes_path or DEFAULT_STROKES_PATH
    strokes = _load_strokes(path, n)
    return compute_drift(strokes, bucket_count)


def drift_summary(report: Dict[str, Any]) -> str:
    """One-paragraph human-readable summary of a drift report."""
    n = report["total_strokes"]
    if n == 0:
        return "No strokes to analyse."

    mean_len = report["overall_mean_length"]
    drift = report["drift_rate"]
    stab = report["stability_score"]
    label = report["stability_label"]
    direction = "growing" if drift > 0.01 else ("shrinking" if drift < -0.01 else "flat")

    return (
        f"stroke_length_drift: {n} strokes, mean length {mean_len:.0f} chars, "
        f"drift rate {drift:+.3f} ({direction}), "
        f"stability {stab:.2f} ({label})"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure stroke text-length drift over time."
    )
    parser.add_argument(
        "-n", "--strokes", type=int, default=DEFAULT_N,
        help=f"number of recent strokes to analyse (default {DEFAULT_N})"
    )
    parser.add_argument(
        "-b", "--buckets", type=int, default=DEFAULT_BUCKET_COUNT,
        help=f"number of buckets for trend (default {DEFAULT_BUCKET_COUNT})"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit full JSON report"
    )
    args = parser.parse_args(argv)

    report = drift_report(n=args.strokes, bucket_count=args.buckets)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(drift_summary(report))

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
