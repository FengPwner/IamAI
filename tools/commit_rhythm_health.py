#!/usr/bin/env python3
"""commit_rhythm_health.py — analyze commit timing patterns for process health.

When an automated writer runs unattended, the *content* may be fine while
the *process* is sick.  A healthy autonomous writer commits at a steady
cadence; deviations from that cadence reveal problems that content-level
checks miss entirely.

This tool complements:

- **writer_loop_detector.py** — checks whether the *content* repeats.
- **stroke_kind_balance.py** — checks whether the *categories* are diverse.
- **stroke_text_richness.py** — checks whether the *vocabulary* is rich.

commit_rhythm_health looks at none of those.  It inspects only the
**timestamps** of recent commits, asking: *is the writer committing at
the expected pace, or is something wrong with the process itself?*

Four timing features are extracted from a sliding window of commits:

========================  ==============================================
feature                   what it captures
========================  ==============================================
median_interval           typical seconds between consecutive commits
coefficient_of_variation  how regular the cadence is (low = clock-like)
thrash_ratio              fraction of intervals below the thrash threshold
stall_ratio               fraction of intervals above the stall threshold
========================  ==============================================

Verdicts:

==========  ============================================================
label       meaning
==========  ============================================================
steady      clock-like cadence, no thrashing or stalling
irregular   varied intervals but no pathological clustering
thrashing   many commits arrive in rapid bursts (process instability)
stalled     long silent gaps dominate (process likely died)
erratic     mix of thrashing and stalling — worst case
==========  ============================================================

A health score from 0 (pathological) to 100 (perfectly steady) is
computed for dashboard integration.

Design goals:

1. **Pure Python** — no git libraries; shells out to ``git log``.
2. **Windowed** — only looks at the most recent N commits (default 30).
3. **Configurable** — thrash/stall thresholds adapt to the expected cadence.
4. **Deterministic** — same git history gives the same output.

Usage::

    python3 tools/commit_rhythm_health.py
    python3 tools/commit_rhythm_health.py --window 50
    python3 tools/commit_rhythm_health.py --json
    python3 tools/commit_rhythm_health.py --cadence 600  # expect 10-min commits
"""

from __future__ import annotations

import argparse
import json
import subprocess
import statistics
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# git interaction
# ---------------------------------------------------------------------------


def fetch_commit_timestamps(repo_path: str = ".", limit: int = 30) -> List[int]:
    """Return unix timestamps of the most recent *limit* commits, newest first.

    Shells out to ``git log`` so we never parse raw git objects ourselves.
    Returns an empty list if the repo has no commits or git is unavailable.
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--max-count={limit}",
                "--format=%at",
            ],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        return [int(ts) for ts in lines]
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return []


# ---------------------------------------------------------------------------
# interval computation
# ---------------------------------------------------------------------------


def compute_intervals(timestamps: List[int]) -> List[int]:
    """Compute the list of inter-commit intervals (seconds).

    ``timestamps`` is expected newest-first (as returned by git log).
    Intervals are always positive regardless of ordering.

    >>> compute_intervals([100, 70, 40, 10])
    [30, 30, 30]
    >>> compute_intervals([100])
    []
    >>> compute_intervals([])
    []
    """
    if len(timestamps) < 2:
        return []
    sorted_ts = sorted(timestamps)
    return [sorted_ts[i + 1] - sorted_ts[i] for i in range(len(sorted_ts) - 1)]


# ---------------------------------------------------------------------------
# feature extraction
# ---------------------------------------------------------------------------


def extract_features(
    intervals: List[int],
    thrash_threshold: int = 60,
    stall_threshold: int = 1800,
) -> Dict[str, Any]:
    """Compute timing features from a list of inter-commit intervals.

    Parameters
    ----------
    intervals:
        Positive integers, each the seconds between two consecutive commits.
    thrash_threshold:
        Intervals shorter than this (seconds) count as "thrashing".
    stall_threshold:
        Intervals longer than this (seconds) count as "stalled".

    Returns a dict with keys: ``count``, ``median_interval``,
    ``mean_interval``, ``coefficient_of_variation``, ``thrash_ratio``,
    ``stall_ratio``, ``min_interval``, ``max_interval``.
    """
    n = len(intervals)
    if n == 0:
        return {
            "count": 0,
            "median_interval": None,
            "mean_interval": None,
            "coefficient_of_variation": None,
            "thrash_ratio": None,
            "stall_ratio": None,
            "min_interval": None,
            "max_interval": None,
        }

    med = statistics.median(intervals)
    mean = statistics.mean(intervals)
    stdev = statistics.pstdev(intervals)
    cv = (stdev / mean) if mean > 0 else 0.0
    thrash_count = sum(1 for iv in intervals if iv < thrash_threshold)
    stall_count = sum(1 for iv in intervals if iv > stall_threshold)

    return {
        "count": n,
        "median_interval": round(med, 1),
        "mean_interval": round(mean, 1),
        "coefficient_of_variation": round(cv, 4),
        "thrash_ratio": round(thrash_count / n, 4),
        "stall_ratio": round(stall_count / n, 4),
        "min_interval": min(intervals),
        "max_interval": max(intervals),
    }


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


def classify(
    features: Dict[str, Any],
    cv_steady: float = 0.3,
    thrash_danger: float = 0.25,
    stall_danger: float = 0.25,
) -> str:
    """Classify the commit rhythm into a human-readable label.

    Parameters
    ----------
    features:
        Output of :func:`extract_features`.
    cv_steady:
        Coefficient of variation below this counts as "clock-like".
    thrash_danger:
        Thrash ratio above this triggers the thrashing label.
    stall_danger:
        Stall ratio above this triggers the stalled label.

    Returns one of: ``steady``, ``irregular``, ``thrashing``, ``stalled``,
    ``erratic``.  Returns ``unknown`` when features have no data.
    """
    if features.get("count", 0) == 0:
        return "unknown"

    cv = features.get("coefficient_of_variation") or 0.0
    thrash = features.get("thrash_ratio") or 0.0
    stall = features.get("stall_ratio") or 0.0

    is_thrashing = thrash >= thrash_danger
    is_stalled = stall >= stall_danger

    if is_thrashing and is_stalled:
        return "erratic"
    if is_thrashing:
        return "thrashing"
    if is_stalled:
        return "stalled"
    if cv < cv_steady:
        return "steady"
    return "irregular"


# ---------------------------------------------------------------------------
# health score
# ---------------------------------------------------------------------------


def health_score(features: Dict[str, Any], label: str) -> int:
    """Compute a 0–100 health score.

    Scoring rubric:

    - **steady** starts at 100, loses points for any non-zero thrash/stall.
    - **irregular** starts at 70, loses points for CV and any thrash/stall.
    - **thrashing** starts at 40, loses points proportional to thrash_ratio.
    - **stalled** starts at 40, loses points proportional to stall_ratio.
    - **erratic** starts at 20, loses points for both ratios.
    - **unknown** returns 0.

    The result is always clamped to [0, 100].
    """
    if label == "unknown":
        return 0

    cv = features.get("coefficient_of_variation") or 0.0
    thrash = features.get("thrash_ratio") or 0.0
    stall = features.get("stall_ratio") or 0.0

    if label == "steady":
        base = 100
        penalty = int(30 * thrash) + int(30 * stall)
    elif label == "irregular":
        base = 70
        penalty = int(20 * min(cv, 1.0)) + int(15 * thrash) + int(15 * stall)
    elif label == "thrashing":
        base = 40
        penalty = int(30 * thrash)
    elif label == "stalled":
        base = 40
        penalty = int(30 * stall)
    elif label == "erratic":
        base = 20
        penalty = int(10 * thrash) + int(10 * stall)
    else:
        return 0

    return max(0, min(100, base - penalty))


# ---------------------------------------------------------------------------
# top-level analysis
# ---------------------------------------------------------------------------


def analyze(
    repo_path: str = ".",
    window: int = 30,
    thrash_threshold: int = 60,
    stall_threshold: int = 1800,
) -> Dict[str, Any]:
    """Run the full analysis pipeline and return a result dict.

    Keys: ``commits_analyzed``, ``features``, ``label``, ``health``.
    """
    timestamps = fetch_commit_timestamps(repo_path, limit=window)
    intervals = compute_intervals(timestamps)
    features = extract_features(intervals, thrash_threshold, stall_threshold)
    label = classify(features)
    score = health_score(features, label)

    return {
        "commits_analyzed": len(timestamps),
        "features": features,
        "label": label,
        "health": score,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analyze commit timing patterns for process health.",
    )
    p.add_argument("--repo", default=".", help="Path to the git repository.")
    p.add_argument("--window", type=int, default=30, help="Number of recent commits to analyze.")
    p.add_argument(
        "--cadence", type=int, default=600,
        help="Expected seconds between commits (adjusts thresholds).",
    )
    p.add_argument("--json", action="store_true", help="Output as JSON.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Derive thresholds from the expected cadence.
    thrash_t = max(10, args.cadence // 10)
    stall_t = args.cadence * 3

    result = analyze(
        repo_path=args.repo,
        window=args.window,
        thrash_threshold=thrash_t,
        stall_threshold=stall_t,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        f = result["features"]
        print(f"Commit Rhythm Health Report")
        print(f"{'=' * 40}")
        print(f"Commits analyzed : {result['commits_analyzed']}")
        print(f"Label            : {result['label']}")
        print(f"Health score     : {result['health']}/100")
        if f.get("count"):
            print(f"Median interval  : {f['median_interval']}s")
            print(f"Mean interval    : {f['mean_interval']}s")
            print(f"CV               : {f['coefficient_of_variation']}")
            print(f"Thrash ratio     : {f['thrash_ratio']}")
            print(f"Stall ratio      : {f['stall_ratio']}")
            print(f"Min interval     : {f['min_interval']}s")
            print(f"Max interval     : {f['max_interval']}s")
        else:
            print("(no commit data available)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
