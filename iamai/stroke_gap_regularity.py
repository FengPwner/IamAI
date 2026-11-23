"""stroke_gap_regularity — measure timing consistency between strokes.

The writer is designed to produce one stroke every ~15 seconds.  In
practice the interval varies: GC pauses, filesystem latency, content
generation time, and (most importantly) process death all create gaps.
This module quantifies how *regular* the stroke timing is, providing
an early signal of degradation before the writer stalls entirely.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
gaps                      list of inter-stroke intervals (seconds)
median_gap                median interval — the typical cadence
mean_gap                  mean interval — pulled up by outliers
max_gap                   largest single gap (likely a stall)
anomalous_gaps            list of gaps exceeding the anomaly threshold
                          (default: 3× median)
anomaly_count             how many anomalous gaps were found
regularity_score          0–1 metric: 1.0 = perfectly regular,
                          0.0 = wildly irregular or stalled
========================  =============================================

Regularity score
----------------

The score is computed from the coefficient of variation (CV) of the
gap distribution, inverted through a sigmoid::

    regularity = 1 / (1 + (cv / reference_cv) ** 2)

where ``reference_cv`` is the CV expected from a healthy writer
(default 0.3, based on observed cadence jitter).  A CV of 0.3 yields
a score of 0.5; a CV of 0.1 yields ~0.92; a CV of 1.0 yields ~0.08.

This means:

=============  =====================================================
score          interpretation
=============  =====================================================
≥ 0.8          clockwork — gaps are tight, writer is healthy
0.5 – 0.8      steady — some variation but nothing alarming
0.2 – 0.5      jittery — irregular timing, check for resource issues
< 0.2          erratic — major stalls detected, intervention likely
=============  =====================================================

Anomaly detection
-----------------

A gap is *anomalous* when it exceeds ``anomaly_multiplier × median_gap``
(default multiplier: 3).  The module reports both the count and the
actual anomalous gap values so the caretaker can see where stalls
occurred.

Usage::

    from iamai.stroke_gap_regularity import gap_report, gap_summary

    report = gap_report(n_strokes=100)
    print(report["regularity_score"])  # e.g. 0.72
    print(report["median_gap"])        # e.g. 15.3
    print(report["anomaly_count"])     # e.g. 2

    print(gap_summary())
    # "gaps: steady 0.72 (median 15.3s, max 312.0s, 2 anomalies in 99 intervals)"

CLI::

    python -m iamai.stroke_gap_regularity --n 100 --json

Written by Qwen during caretaker visit 809, 2026-11-23.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_STROKES = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
_DEFAULT_N = 100
_REFERENCE_CV = 0.3
_ANOMALY_MULTIPLIER = 3.0

# Regularity bands
_BANDS = [
    (0.8, "clockwork"),
    (0.5, "steady"),
    (0.2, "jittery"),
    (0.0, "erratic"),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_strokes_with_timestamps(
    n: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Read the last *n* strokes that have parseable timestamps."""
    p = path or _DEFAULT_STROKES
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-n:] if len(lines) >= n else lines
    result: List[Dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            # Validate that 'at' field exists and is parseable
            if "at" in entry:
                _parse_timestamp(entry["at"])
                result.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return result


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    # Handle various ISO formats
    ts = ts.strip()
    # Python 3.7+ fromisoformat handles most cases, but not 'Z' suffix
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        raise ValueError(f"Cannot parse timestamp: {ts!r}")


# ---------------------------------------------------------------------------
# Gap computation
# ---------------------------------------------------------------------------


def compute_gaps(strokes: Sequence[Dict[str, Any]]) -> List[float]:
    """Compute inter-stroke gaps in seconds.

    Returns a list of non-negative floats, one shorter than the input.
    Strokes must have parseable 'at' fields.
    """
    if len(strokes) < 2:
        return []
    timestamps = [_parse_timestamp(s["at"]) for s in strokes]
    gaps: List[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        gaps.append(max(0.0, delta))
    return gaps


def _median(values: Sequence[float]) -> float:
    """Compute the median of a sorted or unsorted sequence."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _mean(values: Sequence[float]) -> float:
    """Compute the arithmetic mean."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: Sequence[float], mean_val: Optional[float] = None) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    m = mean_val if mean_val is not None else _mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


def find_anomalous_gaps(
    gaps: Sequence[float],
    median_gap: Optional[float] = None,
    multiplier: float = _ANOMALY_MULTIPLIER,
) -> List[Tuple[int, float]]:
    """Find gaps that exceed ``multiplier × median_gap``.

    Returns a list of ``(index, gap_seconds)`` tuples.
    """
    if not gaps:
        return []
    med = median_gap if median_gap is not None else _median(gaps)
    if med <= 0:
        return []
    threshold = multiplier * med
    return [(i, g) for i, g in enumerate(gaps) if g > threshold]


# ---------------------------------------------------------------------------
# Regularity score
# ---------------------------------------------------------------------------


def regularity_score(
    gaps: Sequence[float],
    reference_cv: float = _REFERENCE_CV,
) -> float:
    """Compute a regularity score in [0, 1].

    1.0 = perfectly regular gaps; 0.0 = wildly irregular.
    Uses an inverted sigmoid based on the coefficient of variation.
    """
    if len(gaps) < 2:
        return 1.0 if len(gaps) == 1 else 0.0
    m = _mean(gaps)
    if m <= 0:
        return 0.0
    cv = _std(gaps, m) / m
    # Sigmoid inversion: score = 1 / (1 + (cv / ref)^2)
    ratio = cv / reference_cv
    return 1.0 / (1.0 + ratio ** 2)


def regularity_label(score: float) -> str:
    """Map a regularity score to a human-readable label."""
    for threshold, name in _BANDS:
        if score >= threshold:
            return name
    return "erratic"


# ---------------------------------------------------------------------------
# Report / CLI
# ---------------------------------------------------------------------------


def gap_report(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
    anomaly_multiplier: float = _ANOMALY_MULTIPLIER,
    reference_cv: float = _REFERENCE_CV,
) -> Dict[str, Any]:
    """Produce a full gap regularity report."""
    strokes = _load_strokes_with_timestamps(n=n_strokes, path=path)
    gaps = compute_gaps(strokes)

    if not gaps:
        return {
            "n_strokes_analysed": len(strokes),
            "n_intervals": 0,
            "regularity_score": 0.0,
            "label": "erratic",
            "median_gap": 0.0,
            "mean_gap": 0.0,
            "max_gap": 0.0,
            "anomaly_count": 0,
            "anomalous_gaps": [],
        }

    med = _median(gaps)
    mean = _mean(gaps)
    max_gap = max(gaps)
    score = regularity_score(gaps, reference_cv=reference_cv)
    anomalies = find_anomalous_gaps(gaps, median_gap=med, multiplier=anomaly_multiplier)

    return {
        "n_strokes_analysed": len(strokes),
        "n_intervals": len(gaps),
        "regularity_score": round(score, 4),
        "label": regularity_label(score),
        "median_gap": round(med, 2),
        "mean_gap": round(mean, 2),
        "max_gap": round(max_gap, 2),
        "anomaly_count": len(anomalies),
        "anomalous_gaps": [
            {"index": idx, "gap_seconds": round(g, 2)} for idx, g in anomalies
        ],
    }


def gap_summary(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> str:
    """One-line human summary for dashboards."""
    r = gap_report(n_strokes=n_strokes, path=path)
    if r["n_intervals"] == 0:
        return "gaps: no data (insufficient strokes with timestamps)"
    return (
        f"gaps: {r['label']} {r['regularity_score']:.2f} "
        f"(median {r['median_gap']:.1f}s, "
        f"max {r['max_gap']:.1f}s, "
        f"{r['anomaly_count']} anomal{'y' if r['anomaly_count'] == 1 else 'ies'} "
        f"in {r['n_intervals']} intervals) "
        f"| {r['n_strokes_analysed']} strokes"
    )


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stroke gap regularity analysis for the IamAI project."
    )
    parser.add_argument(
        "--n", type=int, default=_DEFAULT_N,
        help=f"number of recent strokes to analyse (default {_DEFAULT_N})"
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="path to strokes.jsonl (default: data/strokes.jsonl)"
    )
    parser.add_argument(
        "--json", action="store_true", help="output JSON instead of text"
    )
    parser.add_argument(
        "--anomaly-multiplier", type=float, default=_ANOMALY_MULTIPLIER,
        help=f"anomaly threshold multiplier (default {_ANOMALY_MULTIPLIER})"
    )
    args = parser.parse_args(argv)

    report = gap_report(
        n_strokes=args.n,
        path=args.path,
        anomaly_multiplier=args.anomaly_multiplier,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(gap_summary(n_strokes=args.n, path=args.path))

    return 0 if report["label"] in ("clockwork", "steady") else 1


if __name__ == "__main__":
    sys.exit(_cli())
