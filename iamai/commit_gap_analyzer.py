"""commit_gap_analyzer — measure regularity of the commit cadence.

A healthy repo has commits at predictable intervals.  This module parses
the commit log, computes inter-commit gaps, and produces a *regularity
score* that captures how well the rhythm is being maintained.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
commit_count              total commits analysed
gap_count                 number of inter-commit intervals
mean_gap_seconds          arithmetic mean of gaps
median_gap_seconds        median gap
max_gap_seconds           longest gap observed
min_gap_seconds           shortest gap observed
std_gap_seconds           standard deviation of gaps
regularity_score          0–1: 1.0 = perfectly regular, 0.0 = chaotic
outlier_count             gaps exceeding 2x the mean
outlier_fraction          fraction of gaps that are outliers
gap_distribution          histogram of gap buckets (0-60s, 60-300s,
                          300-600s, 600-1800s, 1800s+)
========================  =============================================

Regularity score
----------------

Computed from the coefficient of variation (CV = std / mean):

    score = 1 / (1 + CV)

A perfectly regular cadence (all gaps equal) has CV = 0, score = 1.0.
A cadence where std equals the mean scores 0.5.  Higher variance pushes
the score toward zero.

Outlier detection
-----------------

A gap is an *outlier* when it exceeds ``outlier_multiplier * mean_gap``.
Default multiplier is 2.0 (i.e., twice the mean).

Gap distribution buckets
------------------------

Gaps are classified into five buckets to give a quick visual sense:

    rapid    : < 60 s       (back-to-back commits)
    steady   : 60–300 s     (healthy cadence window)
    normal   : 300–600 s    (10-minute batch target)
    slow     : 600–1800 s   (half-hour or more)
    stalled  : >= 1800 s    (30 min+, likely a process death)

Usage::

    python3 -m iamai.commit_gap_analyzer              # analyse last 50 commits
    python3 -m iamai.commit_gap_analyzer -n 100       # last 100 commits
    python3 -m iamai.commit_gap_analyzer --json       # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

_GAP_BUCKETS = [
    ("rapid", 0, 60),
    ("steady", 60, 300),
    ("normal", 300, 600),
    ("slow", 600, 1800),
    ("stalled", 1800, float("inf")),
]

_DEFAULT_N = 50
_OUTLIER_MULTIPLIER = 2.0


# -----------------------------------------------------------------------
# Git interaction
# -----------------------------------------------------------------------


def _run_git_log(n: int, path: str = ".") -> List[str]:
    """Return the last *n* commit timestamps as ISO-8601 strings."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "log",
            f"--max-count={n}",
            "--format=%aI",
            "--reverse",  # oldest first
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    return lines


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 timestamp (with or without timezone)."""
    # Python 3.7+ fromisoformat handles most formats; we normalise 'Z' suffix.
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# -----------------------------------------------------------------------
# Core analysis
# -----------------------------------------------------------------------


def compute_gaps(timestamps: List[str]) -> List[float]:
    """Return a list of inter-commit gaps in seconds.

    Parameters
    ----------
    timestamps : list of ISO-8601 strings, oldest first.

    Returns
    -------
    list of float — each element is seconds between consecutive commits.
    """
    if len(timestamps) < 2:
        return []
    parsed = [_parse_iso(t) for t in timestamps]
    gaps: List[float] = []
    for i in range(1, len(parsed)):
        delta = (parsed[i] - parsed[i - 1]).total_seconds()
        gaps.append(max(delta, 0.0))  # clamp negative (clock skew) to zero
    return gaps


def gap_distribution(gaps: List[float]) -> Dict[str, int]:
    """Classify gaps into buckets and return counts."""
    dist: Dict[str, int] = {name: 0 for name, _, _ in _GAP_BUCKETS}
    for g in gaps:
        for name, lo, hi in _GAP_BUCKETS:
            if lo <= g < hi:
                dist[name] += 1
                break
    return dist


def detect_outliers(gaps: List[float], multiplier: float = _OUTLIER_MULTIPLIER) -> List[float]:
    """Return gaps that exceed *multiplier* times the mean."""
    if not gaps:
        return []
    m = mean(gaps)
    threshold = m * multiplier
    return [g for g in gaps if g > threshold]


def regularity_score(gaps: List[float]) -> float:
    """Compute a 0–1 regularity score from the coefficient of variation.

    Returns 1.0 for a single gap or perfectly uniform gaps.
    Returns 0.0 for empty input.
    """
    if not gaps:
        return 0.0
    if len(gaps) == 1:
        return 1.0
    m = mean(gaps)
    if m == 0:
        return 0.0  # all commits at the same instant — degenerate
    s = stdev(gaps)
    cv = s / m
    return 1.0 / (1.0 + cv)


def gap_report(
    n: int = _DEFAULT_N,
    path: str = ".",
    outlier_multiplier: float = _OUTLIER_MULTIPLIER,
) -> Dict[str, Any]:
    """Analyse the last *n* commits and return a structured report."""
    timestamps = _run_git_log(n, path)
    gaps = compute_gaps(timestamps)

    if not gaps:
        return {
            "commit_count": len(timestamps),
            "gap_count": 0,
            "mean_gap_seconds": 0.0,
            "median_gap_seconds": 0.0,
            "max_gap_seconds": 0.0,
            "min_gap_seconds": 0.0,
            "std_gap_seconds": 0.0,
            "regularity_score": 0.0,
            "outlier_count": 0,
            "outlier_fraction": 0.0,
            "gap_distribution": gap_distribution([]),
            "label": "insufficient_data",
        }

    m = mean(gaps)
    med = median(gaps)
    mx = max(gaps)
    mn = min(gaps)
    s = stdev(gaps) if len(gaps) > 1 else 0.0
    score = regularity_score(gaps)
    outliers = detect_outliers(gaps, outlier_multiplier)
    dist = gap_distribution(gaps)

    # Label
    if score >= 0.8:
        label = "regular"
    elif score >= 0.5:
        label = "moderate"
    elif score >= 0.3:
        label = "irregular"
    else:
        label = "chaotic"

    return {
        "commit_count": len(timestamps),
        "gap_count": len(gaps),
        "mean_gap_seconds": round(m, 2),
        "median_gap_seconds": round(med, 2),
        "max_gap_seconds": round(mx, 2),
        "min_gap_seconds": round(mn, 2),
        "std_gap_seconds": round(s, 2),
        "regularity_score": round(score, 4),
        "outlier_count": len(outliers),
        "outlier_fraction": round(len(outliers) / len(gaps), 4) if gaps else 0.0,
        "gap_distribution": dist,
        "label": label,
    }


def gap_summary(n: int = _DEFAULT_N, path: str = ".") -> str:
    """Return a human-readable summary string."""
    report = gap_report(n=n, path=path)
    lines = [
        f"commit_gap_analyzer — last {report['commit_count']} commits",
        f"  gaps     : {report['gap_count']}",
        f"  mean     : {report['mean_gap_seconds']:.1f}s",
        f"  median   : {report['median_gap_seconds']:.1f}s",
        f"  range    : {report['min_gap_seconds']:.1f}s – {report['max_gap_seconds']:.1f}s",
        f"  std      : {report['std_gap_seconds']:.1f}s",
        f"  score    : {report['regularity_score']:.4f}  [{report['label']}]",
        f"  outliers : {report['outlier_count']}  ({report['outlier_fraction']:.1%})",
        f"  buckets  : {report['gap_distribution']}",
    ]
    return "\n".join(lines)


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyse commit cadence regularity.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-n",
        "--commits",
        type=int,
        default=_DEFAULT_N,
        help=f"Number of recent commits to analyse (default {_DEFAULT_N}).",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Path to the git repository (default: current directory).",
    )
    parser.add_argument(
        "--outlier-multiplier",
        type=float,
        default=_OUTLIER_MULTIPLIER,
        help=f"Multiplier for outlier detection (default {_OUTLIER_MULTIPLIER}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full report as JSON.",
    )
    args = parser.parse_args(argv)

    report = gap_report(
        n=args.commits,
        path=args.path,
        outlier_multiplier=args.outlier_multiplier,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(gap_summary(n=args.commits, path=args.path))

    return 0 if report["label"] in ("regular", "moderate") else 1


if __name__ == "__main__":
    sys.exit(_cli())
