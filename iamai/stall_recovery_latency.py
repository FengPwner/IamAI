"""Stall recovery latency — measure how long the writer takes to resume after a stall.

Background
----------
Caretaker visits 258–262 ruled out four stall *causes* (batch-interval
correlation, uptime fatigue, content properties, diurnal pattern).
This module shifts from *why* stalls happen to *how* they end:

  - When a stall occurs, how long until the writer produces its next stroke?
  - Is the recovery latency stable over time, or getting worse?
  - Do longer stalls take proportionally longer to recover from?

A stall is defined as a gap > ``threshold_seconds`` between consecutive
strokes.  Recovery latency is the gap from the **end of the stall**
(the first stroke after the gap) to the **second stroke after the gap**
— i.e. confirmation that the writer is producing again, not a single
lucky stroke.

Approach
--------
1. Parse stroke timestamps from ``data/strokes.jsonl``.
2. Identify stalls (gaps > threshold).
3. For each stall, record:
   - ``stall_duration``: seconds of silence
   - ``recovery_latency``: seconds from stall-end to next normal stroke
4. Classify each recovery:

   ============  ==========================================
   bucket        meaning
   ============  ==========================================
   ``instant``   recovery < 2× normal cadence
   ``slow``      recovery 2–5× normal cadence
   ``stuck``     recovery > 5× normal cadence (may cascade)
   ============  ==========================================

5. Compute aggregate statistics.

Public API
----------
- ``detect_stalls(timestamps, threshold)`` → list of stall dicts
- ``recovery_latency(stalls, timestamps)`` → list[float]
- ``classify_recovery(latency, cadence)`` → str
- ``recovery_stats(latencies)`` → dict with median, p95, max, bucket counts
- ``recovery_trend(latencies)`` → list of (index, latency) for plotting

CLI
---
::

    python3 -m iamai.stall_recovery_latency
    python3 -m iamai.stall_recovery_latency --threshold 600
    python3 -m iamai.stall_recovery_latency --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_TZ_CN = timezone(timedelta(hours=8))
_DEFAULT_THRESHOLD_S = 300.0  # 5 minutes


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_timestamps(path: str | Path | None = None) -> list[datetime]:
    """Read stroke timestamps from *path* (or ``data/strokes.jsonl``)."""
    if path is None:
        repo = Path(__file__).resolve().parent.parent
        path = repo / "data" / "strokes.jsonl"
    ts: list[datetime] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw = obj.get("at")
            if raw is None:
                continue
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts.append(dt)
    ts.sort()
    return ts


# ---------------------------------------------------------------------------
# Stall detection
# ---------------------------------------------------------------------------

def detect_stalls(
    timestamps: list[datetime],
    threshold_seconds: float = _DEFAULT_THRESHOLD_S,
) -> list[dict[str, Any]]:
    """Return a list of stall descriptors.

    Each dict contains:
      - ``index``: position in the timestamp list (start of the gap)
      - ``gap_start``: datetime of last stroke before silence
      - ``gap_end``: datetime of first stroke after silence
      - ``duration``: seconds of silence
    """
    stalls: list[dict[str, Any]] = []
    for i in range(len(timestamps) - 1):
        gap = (timestamps[i + 1] - timestamps[i]).total_seconds()
        if gap > threshold_seconds:
            stalls.append({
                "index": i,
                "gap_start": timestamps[i],
                "gap_end": timestamps[i + 1],
                "duration": gap,
            })
    return stalls


# ---------------------------------------------------------------------------
# Recovery latency
# ---------------------------------------------------------------------------

def recovery_latency(
    stalls: list[dict[str, Any]],
    timestamps: list[datetime],
) -> list[float]:
    """For each stall, measure seconds until the *second* post-stall stroke.

    Using the second stroke (not the first) filters out single-stroke
    "blips" that don't indicate sustained recovery.

    If a stall occurs at the end of the timeline with no subsequent
    strokes, it is skipped (the writer never recovered in the data
    window).
    """
    latencies: list[float] = []
    for s in stalls:
        idx = s["index"]
        # first post-stall stroke is at idx+1
        # second post-stall stroke is at idx+2
        if idx + 2 < len(timestamps):
            latency = (timestamps[idx + 2] - timestamps[idx + 1]).total_seconds()
            latencies.append(latency)
    return latencies


def median_cadence(timestamps: list[datetime]) -> float:
    """Return the median inter-stroke interval in seconds."""
    if len(timestamps) < 2:
        return 0.0
    gaps = [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(len(timestamps) - 1)
    ]
    return statistics.median(gaps)


def classify_recovery(latency: float, cadence: float) -> str:
    """Classify a single recovery latency.

    Returns one of ``instant``, ``slow``, or ``stuck``.
    """
    if cadence <= 0:
        return "instant"
    ratio = latency / cadence
    if ratio < 2.0:
        return "instant"
    if ratio < 5.0:
        return "slow"
    return "stuck"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def recovery_stats(
    latencies: list[float],
    cadence: float = 0.0,
) -> dict[str, Any]:
    """Compute aggregate statistics over a list of recovery latencies."""
    if not latencies:
        return {
            "count": 0,
            "median": 0.0,
            "mean": 0.0,
            "p95": 0.0,
            "max": 0.0,
            "min": 0.0,
            "buckets": {"instant": 0, "slow": 0, "stuck": 0},
        }
    sorted_l = sorted(latencies)
    n = len(sorted_l)
    p95_idx = min(int(n * 0.95), n - 1)
    buckets = {"instant": 0, "slow": 0, "stuck": 0}
    for lat in latencies:
        buckets[classify_recovery(lat, cadence)] += 1
    return {
        "count": n,
        "median": round(statistics.median(sorted_l), 1),
        "mean": round(statistics.mean(sorted_l), 1),
        "p95": round(sorted_l[p95_idx], 1),
        "max": round(sorted_l[-1], 1),
        "min": round(sorted_l[0], 1),
        "buckets": buckets,
    }


def recovery_trend(latencies: list[float]) -> list[tuple[int, float]]:
    """Return indexed latencies for trend analysis."""
    return [(i, round(lat, 1)) for i, lat in enumerate(latencies)]


def stall_recovery_correlation(stalls: list[dict[str, Any]], latencies: list[float]) -> float:
    """Pearson-like correlation between stall duration and recovery latency.

    Returns a value in [-1, 1].  Returns 0.0 if insufficient data or
    zero variance in either series.
    """
    if len(stalls) != len(latencies) or len(stalls) < 3:
        return 0.0
    durations = [s["duration"] for s in stalls]
    n = len(durations)
    mean_d = statistics.mean(durations)
    mean_r = statistics.mean(latencies)
    cov = sum((d - mean_d) * (r - mean_r) for d, r in zip(durations, latencies))
    std_d = (sum((d - mean_d) ** 2 for d in durations)) ** 0.5
    std_r = (sum((r - mean_r) ** 2 for r in latencies)) ** 0.5
    if std_d == 0 or std_r == 0:
        return 0.0
    return round(cov / (std_d * std_r), 4)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(
    path: str | Path | None = None,
    threshold_seconds: float = _DEFAULT_THRESHOLD_S,
) -> dict[str, Any]:
    """End-to-end analysis: parse, detect stalls, compute recovery stats."""
    timestamps = parse_timestamps(path)
    if len(timestamps) < 3:
        return {"error": "insufficient data", "stroke_count": len(timestamps)}
    stalls = detect_stalls(timestamps, threshold_seconds)
    latencies = recovery_latency(stalls, timestamps)
    cadence = median_cadence(timestamps)
    stats = recovery_stats(latencies, cadence)
    correlation = stall_recovery_correlation(stalls, latencies)
    return {
        "stroke_count": len(timestamps),
        "stall_count": len(stalls),
        "cadence_median_s": round(cadence, 1),
        "threshold_s": threshold_seconds,
        "recovery": stats,
        "stall_recovery_correlation": correlation,
    }


def format_report(summary: dict[str, Any]) -> str:
    """Human-readable report."""
    if "error" in summary:
        return f"Error: {summary['error']} ({summary['stroke_count']} strokes)"
    lines = [
        f"Strokes analysed : {summary['stroke_count']}",
        f"Stalls detected  : {summary['stall_count']}",
        f"Median cadence   : {summary['cadence_median_s']}s",
        f"Threshold        : {summary['threshold_s']}s",
        "",
        "Recovery latency:",
        f"  count   : {summary['recovery']['count']}",
        f"  median  : {summary['recovery']['median']}s",
        f"  mean    : {summary['recovery']['mean']}s",
        f"  p95     : {summary['recovery']['p95']}s",
        f"  max     : {summary['recovery']['max']}s",
        f"  min     : {summary['recovery']['min']}s",
        "",
        "Buckets:",
        f"  instant : {summary['recovery']['buckets']['instant']}",
        f"  slow    : {summary['recovery']['buckets']['slow']}",
        f"  stuck   : {summary['recovery']['buckets']['stuck']}",
        "",
        f"Stall↔recovery correlation: {summary['stall_recovery_correlation']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Stall recovery latency analysis")
    p.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD_S,
                   help="stall threshold in seconds (default 300)")
    p.add_argument("--json", action="store_true", help="output JSON")
    p.add_argument("--strokes", type=str, default=None,
                   help="path to strokes.jsonl")
    args = p.parse_args(argv)

    result = summarize(path=args.strokes, threshold_seconds=args.threshold)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()
