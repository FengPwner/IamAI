"""stroke_pipeline_latency — end-to-end delivery time from stroke to commit.

The IamAI pipeline has three stages:

    1. **write**  — the writer appends a stroke to ``data/strokes.jsonl``.
    2. **commit** — the batch committer picks up the change and includes it
       in the next commit (target: every 600 s).
    3. **push**   — the commit is pushed to the remote.

This module measures the latency of stage 1→2 (write-to-commit) for every
stroke, producing aggregate statistics and a health verdict.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             strokes analysed
matched_strokes           strokes that could be matched to a commit
mean_latency_seconds      average write-to-commit delay
median_latency_seconds    median delay
p95_latency_seconds       95th-percentile delay
p99_latency_seconds       99th-percentile delay
max_latency_seconds       worst-case delay
min_latency_seconds       best-case delay
within_target_fraction    fraction committed within the target window
target_seconds            the batch commit interval (default 600)
trend                     list of per-bucket mean latencies
health_label              human-readable pipeline health verdict
========================  =============================================

Health labels
-------------

Based on ``within_target_fraction`` (fraction of strokes committed
within ``target_seconds``):

    ≥ 0.95   excellent   — nearly every stroke ships on time
    ≥ 0.80   healthy     — occasional delays, pipeline working well
    ≥ 0.60   degraded    — significant fraction missing the target
    < 0.60   congested   — pipeline is struggling to keep up

How matching works
------------------

For each stroke with timestamp *t*, find the earliest commit that
modified ``data/strokes.jsonl`` with a commit timestamp ≥ *t*.  The
latency is ``commit_time − stroke_time``.

Strokes that occurred during a container reclamation (i.e., the writer
died and the stroke was only committed in the catch-up batch after
restart) will show high latency — this is expected and contributes to
the ``max_latency_seconds`` and ``p99`` metrics.

Usage::

    python3 -m iamai.stroke_pipeline_latency              # last 200 strokes
    python3 -m iamai.stroke_pipeline_latency -n 500       # last 500 strokes
    python3 -m iamai.stroke_pipeline_latency --json       # full JSON report
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO_ROOT / "data" / "strokes.jsonl"
DEFAULT_TARGET_SECONDS = 600  # 10-minute batch interval
DEFAULT_N = 200


# -----------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------


def load_strokes(
    path: Optional[Path] = None,
    n: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Load strokes from the JSONL file.

    Parameters
    ----------
    path : Path, optional
        Override path to strokes.jsonl.
    n : int, optional
        Return only the last *n* strokes.  ``None`` returns all.
    """
    p = path or STROKES_PATH
    if not p.exists():
        return []
    strokes = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            strokes.append(obj)
    if n is not None and n > 0:
        strokes = strokes[-n:]
    return strokes


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# -----------------------------------------------------------------------
# Git commit log
# -----------------------------------------------------------------------


def get_commit_timestamps(
    file_path: str = "data/strokes.jsonl",
    repo_root: Optional[Path] = None,
) -> List[datetime]:
    """Return sorted list of commit timestamps that modified *file_path*.

    Uses ``git log --format=%aI`` to get author timestamps.
    """
    root = repo_root or REPO_ROOT
    try:
        result = subprocess.run(
            [
                "git", "-C", str(root),
                "log", "--format=%aI", "--diff-filter=M",
                "--", file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []
    timestamps = []
    for line in result.stdout.strip().split("\n"):
        dt = _parse_timestamp(line.strip())
        if dt is not None:
            timestamps.append(dt)
    timestamps.sort()
    return timestamps


# -----------------------------------------------------------------------
# Matching
# -----------------------------------------------------------------------


def match_strokes_to_commits(
    strokes: List[Dict[str, Any]],
    commit_times: List[datetime],
) -> List[Dict[str, Any]]:
    """Match each stroke to the earliest commit that could contain it.

    Returns a list of dicts with keys: ``seq``, ``stroke_time``,
    ``commit_time``, ``latency_seconds``.  Strokes that cannot be matched
    (no commit after them) are omitted.
    """
    if not commit_times:
        return []

    results = []
    ci = 0  # commit index pointer

    for stroke in strokes:
        st = _parse_timestamp(stroke.get("at", ""))
        if st is None:
            continue
        # advance pointer to first commit >= stroke time
        while ci < len(commit_times) and commit_times[ci] < st:
            ci += 1
        if ci >= len(commit_times):
            break  # no future commits available
        latency = (commit_times[ci] - st).total_seconds()
        results.append({
            "seq": stroke.get("seq"),
            "stroke_time": st.isoformat(),
            "commit_time": commit_times[ci].isoformat(),
            "latency_seconds": latency,
        })

    return results


# -----------------------------------------------------------------------
# Statistics
# -----------------------------------------------------------------------


def compute_latency_stats(
    latencies: List[float],
) -> Dict[str, float]:
    """Compute descriptive statistics for a list of latency values."""
    if not latencies:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "min": 0.0,
        }
    sorted_lats = sorted(latencies)
    n = len(sorted_lats)

    def _percentile(p: float) -> float:
        k = (n - 1) * p / 100.0
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        return sorted_lats[f] + d * (sorted_lats[c] - sorted_lats[f])

    return {
        "count": n,
        "mean": round(mean(sorted_lats), 2),
        "median": round(median(sorted_lats), 2),
        "p95": round(_percentile(95), 2),
        "p99": round(_percentile(99), 2),
        "max": round(sorted_lats[-1], 2),
        "min": round(sorted_lats[0], 2),
    }


def within_target_fraction(
    latencies: List[float],
    target: float = DEFAULT_TARGET_SECONDS,
) -> float:
    """Fraction of latencies that are ≤ *target* seconds."""
    if not latencies:
        return 0.0
    within = sum(1 for l in latencies if l <= target)
    return round(within / len(latencies), 4)


def health_label(fraction: float) -> str:
    """Classify pipeline health based on on-time delivery fraction."""
    if fraction >= 0.95:
        return "excellent"
    if fraction >= 0.80:
        return "healthy"
    if fraction >= 0.60:
        return "degraded"
    return "congested"


# -----------------------------------------------------------------------
# Trend
# -----------------------------------------------------------------------


def compute_trend(
    matched: List[Dict[str, Any]],
    bucket_size: int = 20,
) -> List[float]:
    """Compute per-bucket mean latency for trend analysis.

    Splits matched strokes into consecutive buckets of *bucket_size*
    and returns the mean latency of each bucket.
    """
    if not matched or bucket_size <= 0:
        return []
    latencies = [m["latency_seconds"] for m in matched]
    buckets = []
    for i in range(0, len(latencies), bucket_size):
        chunk = latencies[i:i + bucket_size]
        if chunk:
            buckets.append(round(mean(chunk), 2))
    return buckets


def trend_direction(trend: List[float]) -> str:
    """Classify latency trend as improving, stable, or degrading.

    Compares mean of first half to mean of second half:
        - >10% decrease → improving
        - >10% increase → degrading
        - otherwise     → stable
    """
    if len(trend) < 2:
        return "stable"
    mid = len(trend) // 2
    first_half = mean(trend[:mid]) if mid > 0 else 0
    second_half = mean(trend[mid:]) if mid < len(trend) else 0
    if first_half == 0:
        return "stable"
    change = (second_half - first_half) / first_half
    if change < -0.10:
        return "improving"
    if change > 0.10:
        return "degrading"
    return "stable"


# -----------------------------------------------------------------------
# Reports
# -----------------------------------------------------------------------


def pipeline_report(
    n: int = DEFAULT_N,
    target: float = DEFAULT_TARGET_SECONDS,
    path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate a full pipeline latency report.

    Returns a dict with all metrics, suitable for JSON serialization.
    """
    strokes = load_strokes(path=path, n=n)
    commit_times = get_commit_timestamps(repo_root=repo_root)
    matched = match_strokes_to_commits(strokes, commit_times)
    latencies = [m["latency_seconds"] for m in matched]

    stats = compute_latency_stats(latencies)
    wtf = within_target_fraction(latencies, target)
    trend = compute_trend(matched)

    return {
        "total_strokes": len(strokes),
        "matched_strokes": len(matched),
        "unmatched_strokes": len(strokes) - len(matched),
        "mean_latency_seconds": stats["mean"],
        "median_latency_seconds": stats["median"],
        "p95_latency_seconds": stats["p95"],
        "p99_latency_seconds": stats["p99"],
        "max_latency_seconds": stats["max"],
        "min_latency_seconds": stats["min"],
        "within_target_fraction": wtf,
        "target_seconds": target,
        "health_label": health_label(wtf),
        "trend": trend,
        "trend_direction": trend_direction(trend),
    }


def pipeline_summary(report: Dict[str, Any]) -> str:
    """One-line human-readable summary of the pipeline health."""
    n = report.get("matched_strokes", 0)
    total = report.get("total_strokes", 0)
    label = report.get("health_label", "unknown")
    wtf = report.get("within_target_fraction", 0)
    med = report.get("median_latency_seconds", 0)
    p95 = report.get("p95_latency_seconds", 0)
    direction = report.get("trend_direction", "stable")
    return (
        f"pipeline {label}: {n}/{total} strokes matched, "
        f"{wtf:.0%} within target, "
        f"median {med:.0f}s, p95 {p95:.0f}s, "
        f"trend {direction}"
    )


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure stroke-to-commit pipeline latency.",
    )
    parser.add_argument(
        "-n", type=int, default=DEFAULT_N,
        help=f"Number of recent strokes to analyse (default {DEFAULT_N}).",
    )
    parser.add_argument(
        "--target", type=float, default=DEFAULT_TARGET_SECONDS,
        help=f"Target latency in seconds (default {DEFAULT_TARGET_SECONDS}).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full report as JSON.",
    )
    args = parser.parse_args(argv)

    report = pipeline_report(n=args.n, target=args.target)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(pipeline_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
