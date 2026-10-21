#!/usr/bin/env python3
"""Analyse whether stroke content properties correlate with writer stalls.

Caretaker visits 258 and 259 ruled out two stall hypotheses:

  - batch-interval correlation (score 0.20 — independent)
  - uptime fatigue correlation  (score 0.50 — mixed / coin-flip)

Visit 259 proposed stroke-content correlation as the next candidate:
specific stroke *properties* (not kind, which is 99.8 % "thought") may
trigger stalls.  This module tests two content-level properties:

  1. **text_length** — long texts might reflect expensive generation
     (more tokens → higher chance of API timeout or rate-limit).
  2. **metric_density** — strokes embedding git metrics (file counts,
     line counts, commit depths) require a subprocess call to ``git``
     inside the writer; a slow or blocked subprocess could stall the
     loop.

For each stall (gap > threshold) the module records the properties of
the *last stroke before the gap*.  It then compares the distribution of
those properties against the full-stroke population.

Outputs:
  - ``length_score``: fraction of stall-preceding strokes whose text
    length is above the population median.
  - ``metric_score``: fraction of stall-preceding strokes that contain
    a git-metrics pattern, compared to the population rate.
  - ``verdict``:
      content_correlated  — either score >= 0.65
      weak_signal        — either score >= 0.55
      independent        — both scores <  0.55

Usage:
    python3 tools/stroke_content_stall_analysis.py
    python3 tools/stroke_content_stall_analysis.py --threshold 300
    python3 tools/stroke_content_stall_analysis.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

# git-metrics patterns found in stroke text (e.g. "1049 files",
# "222112 lines", "12 commits deep", "673 python files").
METRIC_RE = re.compile(
    r"\d+\s+(?:files?|lines?|commits?\s+deep|logged\s+thoughts?|"
    r"python\s+files?|tracked\s+files?)"
)


# ---------------------------------------------------------------------------
# pure helpers (no I/O — easy to test)
# ---------------------------------------------------------------------------

def detect_stalls(
    timestamps: List[datetime],
    threshold_seconds: float = 300.0,
) -> List[int]:
    """Return indices of the *last stroke before each gap*.

    Given N timestamps, returns a list of indices i such that
    timestamps[i+1] - timestamps[i] > threshold_seconds.
    """
    stalls: List[int] = []
    for i in range(len(timestamps) - 1):
        gap = (timestamps[i + 1] - timestamps[i]).total_seconds()
        if gap > threshold_seconds:
            stalls.append(i)
    return stalls


def text_length(stroke: Dict[str, Any]) -> int:
    """Character count of the stroke text."""
    return len(stroke.get("text", ""))


def has_metric(stroke: Dict[str, Any]) -> bool:
    """True if the stroke text contains a git-metrics pattern."""
    return bool(METRIC_RE.search(stroke.get("text", "")))


def median(values: List[int]) -> float:
    """Simple median without importing statistics."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def analyse(
    strokes: List[Dict[str, Any]],
    threshold_seconds: float = 300.0,
) -> Dict[str, Any]:
    """Run the full content-stall analysis on a list of stroke dicts.

    Each stroke must have at least ``at`` (ISO timestamp) and ``text``.
    """
    timestamps = [
        datetime.fromisoformat(s.get("at") or s.get("t", ""))
        for s in strokes
        if s.get("at") or s.get("t")
    ]
    # Re-filter strokes to only those with valid timestamps
    strokes = [
        s for s in strokes if s.get("at") or s.get("t")
    ]
    stall_indices = detect_stalls(timestamps, threshold_seconds)

    # --- population baselines ---
    all_lengths = [text_length(s) for s in strokes]
    med_length = median(all_lengths)
    pop_metric_rate = (
        sum(1 for s in strokes if has_metric(s)) / len(strokes)
        if strokes
        else 0.0
    )

    # --- stall-preceding strokes ---
    stall_lengths = [text_length(strokes[i]) for i in stall_indices]
    stall_metric_count = sum(1 for i in stall_indices if has_metric(strokes[i]))

    above_median = sum(1 for l in stall_lengths if l > med_length)
    length_score = above_median / len(stall_indices) if stall_indices else 0.0

    metric_rate_stall = (
        stall_metric_count / len(stall_indices) if stall_indices else 0.0
    )

    # compare stall metric rate to population rate
    # metric_score > 0.5 means stalls over-represent metric strokes
    if pop_metric_rate > 0:
        metric_score = min(metric_rate_stall / (pop_metric_rate * 2), 1.0)
    else:
        metric_score = 0.5  # no metrics in population → neutral

    # --- verdict ---
    if length_score >= 0.65 or metric_score >= 0.65:
        verdict = "content_correlated"
    elif length_score >= 0.55 or metric_score >= 0.55:
        verdict = "weak_signal"
    else:
        verdict = "independent"

    return {
        "strokes_analyzed": len(strokes),
        "stalls_detected": len(stall_indices),
        "population_median_length": med_length,
        "population_metric_rate": round(pop_metric_rate, 4),
        "length_score": round(length_score, 4),
        "metric_score": round(metric_score, 4),
        "stall_median_length": median(stall_lengths) if stall_lengths else 0.0,
        "stall_metric_rate": round(metric_rate_stall, 4),
        "verdict": verdict,
    }


def format_summary(result: Dict[str, Any]) -> str:
    """Human-readable summary of analysis results."""
    lines = [
        f"strokes analyzed  : {result['strokes_analyzed']}",
        f"stalls detected   : {result['stalls_detected']}",
        f"",
        f"population median length : {result['population_median_length']:.0f}",
        f"population metric rate : {result['population_metric_rate']:.2%}",
        f"",
        f"length_score      : {result['length_score']:.4f}",
        f"metric_score      : {result['metric_score']:.4f}",
        f"verdict           : {result['verdict']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_strokes(path: Path = STROKES_PATH) -> List[Dict[str, Any]]:
    strokes: List[Dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    return strokes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse stroke-content correlation with stalls."
    )
    parser.add_argument(
        "--threshold", type=float, default=300.0,
        help="Gap in seconds to classify as a stall (default: 300)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON instead of text",
    )
    args = parser.parse_args()

    strokes = load_strokes()
    result = analyse(strokes, threshold_seconds=args.threshold)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_summary(result))


if __name__ == "__main__":
    main()
