"""process_cycle_efficiency — measure productive vs overhead time.

A writer process spends time in three states:

    1. **productive** — emitting strokes at or near the target cadence.
    2. **stalled** — a gap that exceeds the stall threshold, meaning the
       process is dead, blocked, or otherwise not writing.
    3. **overhead** — the first few strokes after a restart, before the
       writer settles back into its normal rhythm.

This module parses the stroke log, classifies every inter-stroke interval
into one of those three states, and produces an **efficiency score**:

    efficiency = productive_seconds / total_seconds

A score of 1.0 means the writer never stalled.  A score of 0.5 means
half the wall-clock time was lost to stalls and restart warm-up.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             strokes analysed
productive_strokes        strokes emitted at normal cadence
overhead_strokes          post-restart warm-up strokes
stall_count               number of stall events detected
total_seconds             wall-clock span of the window
productive_seconds        seconds spent in productive writing
stall_seconds             seconds lost to stalls
overhead_seconds          seconds spent warming up after restarts
efficiency_score          0–1: productive / total
overhead_ratio            0–1: (stall + overhead) / total
trend                     list of per-window efficiency scores
efficiency_label          human-readable verdict
========================  =============================================

Classification rules
--------------------

Each inter-stroke gap is classified:

    gap < target + tolerance          → productive
    gap > stall_threshold             → stall (the entire gap is lost time)
    otherwise                         → overhead (slow but not dead)

After a stall, the next ``warmup_count`` strokes are tagged as overhead
regardless of their individual gap size, because the writer is still
settling into its cadence.

    target_cadence    15.0 s   expected stroke interval
    tolerance         10.0 s   ± seconds still considered productive
    stall_threshold   45.0 s   gap above this counts as a stall
    warmup_count      4        strokes after a stall tagged as overhead

Efficiency score
----------------

    efficiency = productive_seconds / total_seconds

where ``total_seconds = productive_seconds + stall_seconds + overhead_seconds``.

Score bands:

    >= 0.90   "efficient"  — writer is humming along
    >= 0.70   "adequate"   — occasional stalls, mostly productive
    >= 0.50   "strained"   — significant time lost to stalls
    <  0.50   "struggling" — more overhead than output

Trend analysis
--------------

When ``window_size`` is given, the stroke log is split into non-overlapping
windows and each window gets its own efficiency score.  This reveals
whether efficiency is improving, stable, or degrading over the observation
period.

Usage::

    from iamai.process_cycle_efficiency import efficiency_report, efficiency_summary

    report = efficiency_report(n_strokes=500)
    print(report["efficiency_score"])   # e.g. 0.87
    print(report["stall_count"])        # e.g. 3
    print(report["efficiency_label"])   # "adequate"

    print(efficiency_summary())
    # "efficiency: adequate 0.87 (3 stalls, 87% productive)"

CLI::

    python -m iamai.process_cycle_efficiency --n 500 --json

Written by Qwen during caretaker visit 813, 2026-11-23.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_STROKES = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
_DEFAULT_N = 200
_TARGET_CADENCE = 15.0
_TOLERANCE = 10.0
_STALL_THRESHOLD = 45.0
_WARMUP_COUNT = 4
_DEFAULT_WINDOW = 50  # strokes per trend window

# Score bands
_BANDS = [
    (0.90, "efficient"),
    (0.70, "adequate"),
    (0.50, "strained"),
    (0.00, "struggling"),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_strokes(
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
            if "at" in entry:
                _parse_timestamp(entry["at"])
                result.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return result


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    ts = ts.strip()
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
    """Compute inter-stroke gaps in seconds."""
    if len(strokes) < 2:
        return []
    timestamps = [_parse_timestamp(s["at"]) for s in strokes]
    gaps: List[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        gaps.append(max(0.0, delta))
    return gaps


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_gaps(
    gaps: Sequence[float],
    target_cadence: float = _TARGET_CADENCE,
    tolerance: float = _TOLERANCE,
    stall_threshold: float = _STALL_THRESHOLD,
    warmup_count: int = _WARMUP_COUNT,
) -> List[str]:
    """Classify each gap as 'productive', 'stall', or 'overhead'.

    Rules:
        - gap > stall_threshold → 'stall'
        - first ``warmup_count`` gaps after a stall → 'overhead'
        - gap <= target + tolerance → 'productive'
        - otherwise → 'overhead'

    Returns a list of labels, one per gap.
    """
    labels: List[str] = []
    warmup_remaining = 0
    productive_ceiling = target_cadence + tolerance

    for gap in gaps:
        if warmup_remaining > 0:
            labels.append("overhead")
            warmup_remaining -= 1
        elif gap > stall_threshold:
            labels.append("stall")
            warmup_remaining = warmup_count
        elif gap <= productive_ceiling:
            labels.append("productive")
        else:
            labels.append("overhead")

    return labels


# ---------------------------------------------------------------------------
# Time accounting
# ---------------------------------------------------------------------------


def account_time(
    gaps: Sequence[float],
    labels: Sequence[str],
) -> Dict[str, float]:
    """Sum seconds by classification label."""
    totals: Dict[str, float] = {"productive": 0.0, "stall": 0.0, "overhead": 0.0}
    for gap, label in zip(gaps, labels):
        totals[label] = totals.get(label, 0.0) + gap
    return totals


def count_by_label(labels: Sequence[str]) -> Dict[str, int]:
    """Count strokes per classification label."""
    counts: Dict[str, int] = {"productive": 0, "stall": 0, "overhead": 0}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def efficiency_score(time_account: Dict[str, float]) -> float:
    """Compute efficiency = productive / total.

    Returns 1.0 when total is zero (no data to evaluate).
    """
    total = sum(time_account.values())
    if total <= 0:
        return 1.0
    return time_account.get("productive", 0.0) / total


def efficiency_label(score: float) -> str:
    """Map an efficiency score to a human-readable band."""
    for threshold, name in _BANDS:
        if score >= threshold:
            return name
    return "struggling"


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_trend(
    gaps: Sequence[float],
    window_size: int = _DEFAULT_WINDOW,
    target_cadence: float = _TARGET_CADENCE,
    tolerance: float = _TOLERANCE,
    stall_threshold: float = _STALL_THRESHOLD,
    warmup_count: int = _WARMUP_COUNT,
) -> List[float]:
    """Split gaps into windows and compute efficiency per window.

    Returns a list of efficiency scores, one per window.
    """
    if not gaps or window_size < 1:
        return []

    trend: List[float] = []
    for start in range(0, len(gaps), window_size):
        window_gaps = gaps[start : start + window_size]
        labels = classify_gaps(
            window_gaps,
            target_cadence=target_cadence,
            tolerance=tolerance,
            stall_threshold=stall_threshold,
            warmup_count=warmup_count,
        )
        ta = account_time(window_gaps, labels)
        trend.append(round(efficiency_score(ta), 4))

    return trend


def trend_direction(trend: Sequence[float]) -> str:
    """Classify trend as 'improving', 'stable', or 'degrading'.

    Uses simple first-half vs second-half comparison.
    """
    if len(trend) < 2:
        return "stable"

    mid = len(trend) // 2
    first_half = sum(trend[:mid]) / mid
    second_half = sum(trend[mid:]) / (len(trend) - mid)

    delta = second_half - first_half
    if delta > 0.05:
        return "improving"
    elif delta < -0.05:
        return "degrading"
    return "stable"


# ---------------------------------------------------------------------------
# Report / summary
# ---------------------------------------------------------------------------


def efficiency_report(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
    target_cadence: float = _TARGET_CADENCE,
    tolerance: float = _TOLERANCE,
    stall_threshold: float = _STALL_THRESHOLD,
    warmup_count: int = _WARMUP_COUNT,
    window_size: int = _DEFAULT_WINDOW,
) -> Dict[str, Any]:
    """Produce a full process cycle efficiency report."""
    strokes = _load_strokes(n=n_strokes, path=path)
    gaps = compute_gaps(strokes)

    if len(gaps) < 2:
        return {
            "total_strokes": len(strokes),
            "productive_strokes": 0,
            "overhead_strokes": 0,
            "stall_count": 0,
            "total_seconds": 0.0,
            "productive_seconds": 0.0,
            "stall_seconds": 0.0,
            "overhead_seconds": 0.0,
            "efficiency_score": 1.0,
            "overhead_ratio": 0.0,
            "trend": [],
            "trend_direction": "stable",
            "efficiency_label": "efficient",
        }

    labels = classify_gaps(
        gaps,
        target_cadence=target_cadence,
        tolerance=tolerance,
        stall_threshold=stall_threshold,
        warmup_count=warmup_count,
    )
    time_account = account_time(gaps, labels)
    stroke_counts = count_by_label(labels)
    score = efficiency_score(time_account)
    total = sum(time_account.values())
    overhead_ratio = (
        (time_account["stall"] + time_account["overhead"]) / total
        if total > 0
        else 0.0
    )
    trend = compute_trend(
        gaps,
        window_size=window_size,
        target_cadence=target_cadence,
        tolerance=tolerance,
        stall_threshold=stall_threshold,
        warmup_count=warmup_count,
    )

    return {
        "total_strokes": len(strokes),
        "productive_strokes": stroke_counts["productive"],
        "overhead_strokes": stroke_counts["overhead"],
        "stall_count": stroke_counts["stall"],
        "total_seconds": round(total, 1),
        "productive_seconds": round(time_account["productive"], 1),
        "stall_seconds": round(time_account["stall"], 1),
        "overhead_seconds": round(time_account["overhead"], 1),
        "efficiency_score": round(score, 4),
        "overhead_ratio": round(overhead_ratio, 4),
        "trend": trend,
        "trend_direction": trend_direction(trend),
        "efficiency_label": efficiency_label(score),
    }


def efficiency_summary(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> str:
    """One-line human summary for dashboards."""
    r = efficiency_report(n_strokes=n_strokes, path=path)
    pct = r["efficiency_score"] * 100
    return (
        f"efficiency: {r['efficiency_label']} {r['efficiency_score']:.2f} "
        f"({r['stall_count']} stall{'s' if r['stall_count'] != 1 else ''}, "
        f"{pct:.0f}% productive, trend {r['trend_direction']})"
    )


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Process cycle efficiency analysis for the IamAI project."
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
        "--target-cadence", type=float, default=_TARGET_CADENCE,
        help=f"expected seconds per stroke (default {_TARGET_CADENCE})"
    )
    parser.add_argument(
        "--stall-threshold", type=float, default=_STALL_THRESHOLD,
        help=f"seconds above which a gap is a stall (default {_STALL_THRESHOLD})"
    )
    parser.add_argument(
        "--window", type=int, default=_DEFAULT_WINDOW,
        help=f"strokes per trend window (default {_DEFAULT_WINDOW})"
    )
    args = parser.parse_args(argv)

    report = efficiency_report(
        n_strokes=args.n,
        path=args.path,
        target_cadence=args.target_cadence,
        stall_threshold=args.stall_threshold,
        window_size=args.window,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(efficiency_summary(n_strokes=args.n, path=args.path))

    return 0 if report["efficiency_label"] in ("efficient", "adequate") else 1


if __name__ == "__main__":
    sys.exit(_cli())
