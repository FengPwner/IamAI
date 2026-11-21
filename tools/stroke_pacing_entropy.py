#!/usr/bin/env python3
"""stroke_pacing_entropy.py — measure the entropy of inter-stroke intervals.

A perfectly periodic writer (one stroke every 15.000s) has zero timing entropy:
the intervals carry no information.  A writer that occasionally pauses, bursts,
or slows down has higher entropy — its rhythm is less predictable, which is
a weak signal of autonomy rather than mechanical clockwork.

This tool computes:

    intervals       list of seconds between consecutive strokes
    mean_interval   average gap
    std_interval    standard deviation of gaps
    entropy_bits    Shannon entropy of the binned interval distribution
    cv              coefficient of variation (std / mean)
    verdict         'mechanical' | 'organic' | 'erratic'

Thresholds (tuneable via constants):

    cv < low_cv  AND  entropy < low_entropy  → mechanical
    cv > high_cv OR   entropy > high_entropy  → erratic
    everything else                            → organic

The binning strategy is simple: round each interval to the nearest integer
second, then compute the Shannon entropy of the resulting frequency distribution.
This makes entropy comparable across runs with similar sample sizes.

Usage:
    python3 tools/stroke_pacing_entropy.py
    python3 tools/stroke_pacing_entropy.py --tail 200 --json
    python3 tools/stroke_pacing_entropy.py --low-cv 0.05 --high-cv 0.5

Exit codes:
    0  organic   (healthy variability)
    1  mechanical (too regular — likely a fixed sleep loop)
    2  erratic   (too irregular — possible stalling / restarts)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Thresholds for classification.
DEFAULT_LOW_CV = 0.10       # below this CV = too regular
DEFAULT_HIGH_CV = 0.80      # above this CV = too erratic
DEFAULT_LOW_ENTROPY = 1.0   # bits — below = very predictable
DEFAULT_HIGH_ENTROPY = 5.0  # bits — above = very unpredictable


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def parse_timestamp(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware datetime."""
    ts = ts.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_strokes(path: Path, tail: int | None = None) -> list[dict]:
    """Load strokes from the JSONL file, optionally keeping only the last N."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if tail is not None:
        lines = lines[-tail:]
    strokes = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def compute_intervals(strokes: list[dict]) -> list[float]:
    """Compute the seconds between each consecutive pair of strokes.

    Returns a list of floats, one shorter than the input.
    Strokes without a parseable 'at' field are skipped.
    """
    timestamps: list[datetime] = []
    for s in strokes:
        raw = s.get("at")
        if not raw:
            continue
        try:
            timestamps.append(parse_timestamp(str(raw)))
        except (ValueError, TypeError):
            continue
    if len(timestamps) < 2:
        return []
    intervals: list[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta >= 0:
            intervals.append(delta)
    return intervals


def bin_entropy(intervals: list[float], bin_width: float = 1.0) -> float:
    """Compute Shannon entropy (bits) of intervals rounded to the nearest bin.

    Args:
        intervals: list of interval durations in seconds.
        bin_width: width of each bin in seconds (default 1s).

    Returns:
        Entropy in bits.  Returns 0.0 for empty or single-value distributions.
    """
    if not intervals:
        return 0.0
    bins = Counter(round(iv / bin_width) * bin_width for iv in intervals)
    total = sum(bins.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in bins.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def classify(
    cv: float,
    entropy: float,
    low_cv: float = DEFAULT_LOW_CV,
    high_cv: float = DEFAULT_HIGH_CV,
    low_entropy: float = DEFAULT_LOW_ENTROPY,
    high_entropy: float = DEFAULT_HIGH_ENTROPY,
) -> str:
    """Return a verdict string based on CV and entropy thresholds."""
    if cv < low_cv and entropy < low_entropy:
        return "mechanical"
    if cv > high_cv or entropy > high_entropy:
        return "erratic"
    return "organic"


def verdict_exit(verdict: str) -> int:
    """Map verdict to exit code."""
    return {"organic": 0, "mechanical": 1, "erratic": 2}.get(verdict, 2)


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def coefficient_of_variation(values: list[float]) -> float:
    m = mean(values)
    if m == 0:
        return 0.0
    return std(values) / m


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_report(
    intervals: list[float],
    entropy: float,
    cv: float,
    verdict: str,
    sample_size: int,
) -> dict:
    """Build a structured report dictionary."""
    return {
        "sample_size": sample_size,
        "interval_count": len(intervals),
        "mean_interval_s": round(mean(intervals), 2),
        "std_interval_s": round(std(intervals), 2),
        "cv": round(cv, 4),
        "entropy_bits": round(entropy, 4),
        "min_interval_s": round(min(intervals), 2) if intervals else 0,
        "max_interval_s": round(max(intervals), 2) if intervals else 0,
        "unique_bins": len(set(round(iv) for iv in intervals)) if intervals else 0,
        "verdict": verdict,
    }


def format_report(report: dict) -> str:
    """Format a report dict into a human-readable string."""
    lines = [
        "stroke pacing entropy report",
        f"  sample:     {report['sample_size']} strokes → {report['interval_count']} intervals",
        f"  mean gap:   {report['mean_interval_s']}s  (σ = {report['std_interval_s']}s)",
        f"  cv:         {report['cv']}",
        f"  entropy:    {report['entropy_bits']} bits  ({report['unique_bins']} unique bins)",
        f"  range:      [{report['min_interval_s']}s, {report['max_interval_s']}s]",
        f"  verdict:    {report['verdict']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strokes", type=Path, default=DEFAULT_STROKES)
    ap.add_argument("--tail", type=int, default=None, help="only analyse the last N strokes")
    ap.add_argument("--low-cv", type=float, default=DEFAULT_LOW_CV)
    ap.add_argument("--high-cv", type=float, default=DEFAULT_HIGH_CV)
    ap.add_argument("--low-entropy", type=float, default=DEFAULT_LOW_ENTROPY)
    ap.add_argument("--high-entropy", type=float, default=DEFAULT_HIGH_ENTROPY)
    ap.add_argument("--bin-width", type=float, default=1.0)
    ap.add_argument("--json", action="store_true", help="output JSON instead of text")
    args = ap.parse_args()

    strokes = load_strokes(args.strokes, tail=args.tail)
    intervals = compute_intervals(strokes)

    if not intervals:
        report = build_report([], 0.0, 0.0, "mechanical", len(strokes))
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_report(report))
        return verdict_exit("mechanical")

    entropy = bin_entropy(intervals, bin_width=args.bin_width)
    cv = coefficient_of_variation(intervals)
    verdict = classify(cv, entropy, args.low_cv, args.high_cv, args.low_entropy, args.high_entropy)
    report = build_report(intervals, entropy, cv, verdict, len(strokes))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    return verdict_exit(verdict)


if __name__ == "__main__":
    sys.exit(main())
