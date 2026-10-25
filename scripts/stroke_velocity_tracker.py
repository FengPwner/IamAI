#!/usr/bin/env python3
"""
stroke_velocity_tracker.py — measure writing momentum and cadence health.

the IamAI writer produces strokes at a target cadence of one every 15 seconds,
batched into commits every 10 minutes. this tool parses the append-only
strokes log (data/strokes.jsonl), computes velocity and momentum metrics,
and scores the system's writing health.

metrics (each 0–25, total 0–100, higher is better):
  1. recent_stroke_rate    — strokes/hour over the last 6 hours vs target
  2. rate_trend            — recent 6h rate vs prior 18h rate (momentum)
  3. cadence_regularity    — coefficient of variation of inter-stroke gaps
                             (lower CV = more regular = better)
  4. kind_balance          — how evenly distributed are the 6 stroke kinds
                             (garden, metrics, note, snippet, devlog, thought)

grading:
  0–20   STALLED    — writer barely producing, immediate attention needed
  21–45  SPUTTERING — irregular output, cadence broken
  46–70  STEADY     — producing but with some inconsistency
  71–100 CRUISING   — strong, regular output with good diversity

usage:
    python3 scripts/stroke_velocity_tracker.py [--repo PATH] [--hours N]
    python3 scripts/stroke_velocity_tracker.py --json

exit codes:
    0 = CRUISING or STEADY (good)
    1 = SPUTTERING (warning)
    2 = STALLED (alert)
"""

import argparse
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── helpers ──────────────────────────────────────────────────────────

STROKE_KINDS = {"garden", "metrics", "note", "snippet", "devlog", "thought"}
TARGET_RATE_PER_HOUR = 240.0  # one stroke every 15s = 240/hour


def load_strokes(strokes_path: str) -> List[Dict]:
    """parse strokes.jsonl and return list of stroke dicts with parsed timestamps."""
    strokes = []
    path = Path(strokes_path)
    if not path.exists():
        return strokes
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = record.get("at", "")
            try:
                record["_ts"] = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
            strokes.append(record)
    strokes.sort(key=lambda r: r["_ts"])
    return strokes


def filter_since(strokes: List[Dict], cutoff: datetime) -> List[Dict]:
    """return strokes at or after cutoff."""
    return [s for s in strokes if s["_ts"] >= cutoff]


# ── metric 1: recent stroke rate ─────────────────────────────────────

def compute_recent_rate(strokes: List[Dict], now: datetime,
                        window_hours: float = 6.0) -> float:
    """strokes per hour over the recent window. returns 0 if no strokes."""
    cutoff = now - timedelta(hours=window_hours)
    recent = filter_since(strokes, cutoff)
    if not recent:
        return 0.0
    return len(recent) / window_hours


def score_recent_rate(rate: float, target: float = TARGET_RATE_PER_HOUR) -> int:
    """score 0–25 based on how close recent rate is to target."""
    if target <= 0:
        return 0
    ratio = rate / target
    if ratio >= 0.9:
        return 25
    if ratio >= 0.7:
        return 20
    if ratio >= 0.5:
        return 15
    if ratio >= 0.3:
        return 10
    if ratio >= 0.1:
        return 5
    return 0


# ── metric 2: rate trend (momentum) ──────────────────────────────────

def compute_rate_trend(strokes: List[Dict], now: datetime,
                       recent_hours: float = 6.0,
                       baseline_hours: float = 18.0) -> float:
    """
    ratio of recent rate to baseline rate.
    >1 means accelerating, <1 means decelerating, 1 = steady.
    returns 1.0 if baseline has no strokes (avoid division by zero).
    """
    recent_cutoff = now - timedelta(hours=recent_hours)
    baseline_cutoff = now - timedelta(hours=recent_hours + baseline_hours)

    recent = filter_since(strokes, recent_cutoff)
    baseline_all = filter_since(strokes, baseline_cutoff)
    # baseline excludes the recent window
    baseline = [s for s in baseline_all if s["_ts"] < recent_cutoff]

    if not baseline:
        # no baseline data: if recent is also empty, signal stall; else neutral
        return 1.0 if recent else 0.0

    recent_rate = len(recent) / recent_hours if recent else 0.0
    baseline_rate = len(baseline) / baseline_hours

    if baseline_rate == 0:
        return 1.0 if recent else 0.0
    return recent_rate / baseline_rate


def score_rate_trend(trend: float) -> int:
    """score 0–25. trend around 1.0 is best; <0.5 or >2.0 is concerning."""
    if 0.8 <= trend <= 1.2:
        return 25  # steady
    if 0.6 <= trend < 0.8 or 1.2 < trend <= 1.5:
        return 20  # mild drift
    if 0.4 <= trend < 0.6 or 1.5 < trend <= 2.0:
        return 12  # moderate drift
    if 0.2 <= trend < 0.4:
        return 5   # decelerating significantly
    return 0        # stalled or extreme


# ── metric 3: cadence regularity ─────────────────────────────────────

def compute_inter_stroke_gaps(strokes: List[Dict]) -> List[float]:
    """return list of inter-stroke gaps in seconds."""
    if len(strokes) < 2:
        return []
    gaps = []
    for i in range(1, len(strokes)):
        delta = (strokes[i]["_ts"] - strokes[i - 1]["_ts"]).total_seconds()
        if delta >= 0:
            gaps.append(delta)
    return gaps


def compute_gap_cv(gaps: List[float]) -> float:
    """
    coefficient of variation of inter-stroke gaps.
    lower = more regular. returns inf if no gaps (no data = worst case).
    """
    if not gaps:
        return float("inf")
    mean = sum(gaps) / len(gaps)
    if mean < 1.0:
        # sub-second mean gap → effectively no cadence signal
        return float("inf")
    variance = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    std = math.sqrt(variance)
    return std / mean


def score_cadence_regularity(cv: float) -> int:
    """score 0–25. CV < 0.3 is excellent, > 2.0 or inf is very irregular."""
    if cv == float("inf"):
        return 0
    if cv <= 0.3:
        return 25
    if cv <= 0.5:
        return 20
    if cv <= 1.0:
        return 15
    if cv <= 1.5:
        return 10
    if cv <= 2.0:
        return 5
    return 0


# ── metric 4: kind balance ───────────────────────────────────────────

def compute_kind_distribution(strokes: List[Dict]) -> Counter:
    """count strokes by kind."""
    return Counter(s.get("kind", "unknown") for s in strokes)


def compute_kind_balance_ratio(dist: Counter) -> float:
    """
    how evenly distributed are the 6 expected kinds.
    1.0 = perfectly even, 0.0 = all in one kind.
    uses a simplified evenness: min_count / max_count across expected kinds.
    """
    counts = [dist.get(k, 0) for k in STROKE_KINDS]
    if not counts or max(counts) == 0:
        return 0.0
    return min(counts) / max(counts)


def score_kind_balance(ratio: float) -> int:
    """score 0–25 based on kind evenness."""
    if ratio >= 0.9:
        return 25
    if ratio >= 0.75:
        return 20
    if ratio >= 0.5:
        return 15
    if ratio >= 0.3:
        return 10
    if ratio >= 0.1:
        return 5
    return 0


# ── composite ────────────────────────────────────────────────────────

def compute_all_scores(strokes: List[Dict], now: Optional[datetime] = None
                       ) -> Dict:
    """compute all metrics and return a structured result dict."""
    if now is None:
        now = datetime.now(timezone.utc)

    # metric 1: recent rate
    rate = compute_recent_rate(strokes, now)
    s_rate = score_recent_rate(rate)

    # metric 2: trend
    trend = compute_rate_trend(strokes, now)
    s_trend = score_rate_trend(trend)

    # metric 3: cadence regularity (use recent strokes only for relevance)
    cutoff_24h = now - timedelta(hours=24)
    recent_24h = filter_since(strokes, cutoff_24h)
    gaps = compute_inter_stroke_gaps(recent_24h)
    cv = compute_gap_cv(gaps)
    s_cadence = score_cadence_regularity(cv)

    # metric 4: kind balance (use recent 24h)
    dist = compute_kind_distribution(recent_24h)
    balance = compute_kind_balance_ratio(dist)
    s_balance = score_kind_balance(balance) if recent_24h else 0

    total = s_rate + s_trend + s_cadence + s_balance
    grade = classify(total)

    return {
        "recent_rate_per_hour": round(rate, 1),
        "recent_rate_score": s_rate,
        "rate_trend": round(trend, 3),
        "rate_trend_score": s_trend,
        "cadence_cv": round(cv, 3),
        "cadence_score": s_cadence,
        "kind_balance_ratio": round(balance, 3),
        "kind_balance_score": s_balance,
        "kind_counts": dict(dist),
        "total_score": total,
        "grade": grade,
        "strokes_analyzed_24h": len(recent_24h),
        "timestamp": now.isoformat(),
    }


def classify(total: int) -> str:
    """map total score to grade label."""
    if total >= 71:
        return "CRUISING"
    if total >= 46:
        return "STEADY"
    if total >= 21:
        return "SPUTTERING"
    return "STALLED"


def exit_code_for(grade: str) -> int:
    """map grade to exit code."""
    return {"CRUISING": 0, "STEADY": 0, "SPUTTERING": 1, "STALLED": 2}.get(grade, 1)


# ── formatting ───────────────────────────────────────────────────────

def format_bar(score: int, max_score: int = 25, width: int = 20) -> str:
    """render a simple ascii bar."""
    filled = int((score / max_score) * width) if max_score > 0 else 0
    return "█" * filled + "░" * (width - filled)


def format_report(result: Dict) -> str:
    """format result as a human-readable report."""
    lines = [
        "╔══════════════════════════════════════════════════════╗",
        "║         STROKE VELOCITY TRACKER                     ║",
        "╠══════════════════════════════════════════════════════╣",
        "",
        f"  grade: {result['grade']}  (score: {result['total_score']}/100)",
        f"  strokes analyzed (24h): {result['strokes_analyzed_24h']}",
        f"  timestamp: {result['timestamp']}",
        "",
        "  ┌─ metrics ─────────────────────────────────────────┐",
        f"  │ recent rate:  {result['recent_rate_per_hour']:.1f}/hr "
        f"(target {TARGET_RATE_PER_HOUR:.0f}/hr)            │",
        f"  │   [{format_bar(result['recent_rate_score'])}] "
        f"{result['recent_rate_score']}/25    │",
        f"  │ trend:        {result['rate_trend']:.3f} "
        f"(1.0 = steady)                │",
        f"  │   [{format_bar(result['rate_trend_score'])}] "
        f"{result['rate_trend_score']}/25    │",
        f"  │ cadence CV:   {result['cadence_cv']:.3f} "
        f"(lower = more regular)    │",
        f"  │   [{format_bar(result['cadence_score'])}] "
        f"{result['cadence_score']}/25    │",
        f"  │ kind balance: {result['kind_balance_ratio']:.3f} "
        f"(1.0 = even)             │",
        f"  │   [{format_bar(result['kind_balance_score'])}] "
        f"{result['kind_balance_score']}/25    │",
        "  └───────────────────────────────────────────────────┘",
        "",
        "  kind distribution (24h):",
    ]

    kind_counts = result.get("kind_counts", {})
    for kind in sorted(STROKE_KINDS):
        count = kind_counts.get(kind, 0)
        lines.append(f"    {kind:10s} {count:5d}")

    lines.append("")
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="measure writing momentum and cadence health."
    )
    parser.add_argument(
        "--repo", default=".",
        help="path to the IamAI repo (default: cwd)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output JSON instead of human-readable report",
    )
    parser.add_argument(
        "--hours", type=float, default=6.0,
        help="recent window in hours (default: 6)",
    )
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    strokes_path = os.path.join(repo, "data", "strokes.jsonl")

    strokes = load_strokes(strokes_path)
    if not strokes:
        print("no strokes found in", strokes_path, file=sys.stderr)
        sys.exit(2)

    now = datetime.now(timezone.utc)
    result = compute_all_scores(strokes, now)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    sys.exit(exit_code_for(result["grade"]))


if __name__ == "__main__":
    main()
