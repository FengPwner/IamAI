#!/usr/bin/env python3
"""writer_momentum — measure whether a writer builds on recent work or keeps restarting.

Momentum is the difference between a writer who accumulates and one who
repeats. A high-momentum writer picks up where they left off: the next
stroke extends the previous one, the next file deepens the module that
was just created, the next test validates the function that was just
written. A low-momentum writer keeps starting over — new threads, new
files, new ideas — without building enough depth on any single thread
to produce lasting artifacts.

Momentum is not the same as focus. Focus measures whether consecutive
strokes are *related* (same cluster, overlapping paths). Momentum
measures whether consecutive strokes *build on each other* — each stroke
adding a layer to the work the previous stroke began. A focused writer
might spend ten strokes on the same cluster but rewrite the same file
ten times (high focus, low momentum). A high-momentum writer might
touch different files in each stroke but always advance a coherent
larger goal.

Dimensions
----------

======================  ================================================
metric                  meaning
======================  ================================================
build_on_rate           fraction of strokes that modify a file also
                        touched within the previous ``lookback`` strokes;
                        higher = more often extending recent work
continuation_ratio      fraction of consecutive stroke pairs where the
                        later stroke touches at least one file from the
                        earlier stroke; stricter than focus relatedness
                        (requires exact file overlap, not just cluster)
depth_per_thread        average strokes spent on each thread before
                        switching; a thread is a maximal run of
                        consecutive strokes sharing at least one file
fresh_start_rate        fraction of strokes that share zero files with
                        the preceding ``lookback`` strokes; the inverse
                        of building on recent work
momentum_class          rolling | cruising | stuttering | restarting
======================  ================================================

Momentum classes
----------------

==============  ============================================================
class           meaning
==============  ============================================================
rolling         score ≥ 0.70 — writer consistently builds on recent work;
                each stroke naturally extends the previous one; strong
                compounding effect
cruising        0.50 ≤ score < 0.70 — healthy forward progress with
                occasional fresh starts; the normal productive mode
stuttering      0.30 ≤ score < 0.50 — frequent fresh starts interrupt
                building; the writer starts many threads but finishes few
restarting      score < 0.30 — most strokes begin something new; prior
                work is rarely extended; risk of accumulation without depth
==============  ============================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stroke_files(stroke: dict[str, Any]) -> set[str]:
    """Extract normalized file paths from a stroke record."""
    files = stroke.get("files", [])
    if not isinstance(files, list):
        return set()
    result = set()
    for f in files:
        if isinstance(f, (str, Path)):
            s = str(f).strip()
            if s:
                result.add(s)
    return result


def _recent_file_set(
    strokes: list[dict[str, Any]],
    index: int,
    lookback: int,
) -> set[str]:
    """Collect all files touched in the ``lookback`` strokes before ``index``."""
    start = max(0, index - lookback)
    files: set[str] = set()
    for j in range(start, index):
        files |= _stroke_files(strokes[j])
    return files


def _thread_id(files: set[str], prev_files: set[str]) -> bool:
    """Return True if ``files`` continues the same thread as ``prev_files``.

    A continuation requires at least one exact file in common.
    """
    return bool(files & prev_files)


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def compute_momentum_metrics(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
    lookback: int = 3,
) -> dict[str, Any]:
    """Compute momentum metrics for a list of strokes.

    Parameters
    ----------
    strokes : list[dict]
        List of stroke records, each containing a ``files`` field.
    window_size : int
        Number of recent strokes to analyze.
    lookback : int
        How many prior strokes to check when computing build-on rate.

    Returns
    -------
    dict
        Momentum metrics including:
        - build_on_rate, continuation_ratio, depth_per_thread,
          fresh_start_rate, momentum_score, momentum_class,
          strokes_analyzed, threads_count.
    """
    if not strokes:
        return {
            "build_on_rate": 0.0,
            "continuation_ratio": 0.0,
            "depth_per_thread": 0.0,
            "fresh_start_rate": 1.0,
            "momentum_score": 0.0,
            "momentum_class": "restarting",
            "strokes_analyzed": 0,
            "threads_count": 0,
        }

    recent = strokes[-window_size:]
    n = len(recent)

    if n < 2:
        files0 = _stroke_files(recent[0]) if n == 1 else set()
        return {
            "build_on_rate": 0.0,
            "continuation_ratio": 0.0,
            "depth_per_thread": float(n),
            "fresh_start_rate": 0.0 if files0 else 1.0,
            "momentum_score": 0.0,
            "momentum_class": "restarting",
            "strokes_analyzed": n,
            "threads_count": 1 if files0 else 0,
        }

    build_on_count = 0
    continuation_count = 0
    fresh_start_count = 0

    # Thread tracking
    threads: list[int] = []
    current_thread_len = 1

    for i in range(1, n):
        cur_files = _stroke_files(recent[i])
        prev_files = _stroke_files(recent[i - 1])

        # Build-on: any overlap with the lookback window
        recent_files = _recent_file_set(recent, i, lookback)
        if recent_files and cur_files & recent_files:
            build_on_count += 1

        # Continuation: direct file overlap with immediately previous stroke
        if _thread_id(cur_files, prev_files):
            continuation_count += 1
            current_thread_len += 1
        else:
            threads.append(current_thread_len)
            current_thread_len = 1

            # Fresh start: zero overlap with entire lookback window
            if not (cur_files & recent_files):
                fresh_start_count += 1

    # Close last thread
    threads.append(current_thread_len)

    pairs = n - 1
    build_on_rate = build_on_count / pairs
    continuation_ratio = continuation_count / pairs
    fresh_start_rate = fresh_start_count / pairs
    depth_per_thread = sum(threads) / len(threads) if threads else 0.0

    # Composite score: build-on (35%), continuation (30%), depth (20%), inverse fresh-start (15%)
    # Depth component: normalize to [0, 1] with a soft cap at 10 strokes per thread
    depth_norm = min(depth_per_thread / 10.0, 1.0)
    momentum_score = (
        build_on_rate * 0.35
        + continuation_ratio * 0.30
        + depth_norm * 0.20
        + (1.0 - fresh_start_rate) * 0.15
    )
    momentum_score = round(min(max(momentum_score, 0.0), 1.0), 4)

    return {
        "build_on_rate": round(build_on_rate, 4),
        "continuation_ratio": round(continuation_ratio, 4),
        "depth_per_thread": round(depth_per_thread, 4),
        "fresh_start_rate": round(fresh_start_rate, 4),
        "momentum_score": momentum_score,
        "momentum_class": _classify(momentum_score),
        "strokes_analyzed": n,
        "threads_count": len(threads),
    }


def _classify(score: float) -> str:
    """Map a composite momentum score to a momentum class."""
    if score >= 0.70:
        return "rolling"
    if score >= 0.50:
        return "cruising"
    if score >= 0.30:
        return "stuttering"
    return "restarting"


# ---------------------------------------------------------------------------
# Analysis (file-based entry point)
# ---------------------------------------------------------------------------

def analyze_writer_momentum(
    strokes_path: str | Path,
    window_size: int = 20,
    lookback: int = 3,
) -> dict[str, Any]:
    """Load strokes from a JSONL file and compute momentum metrics.

    Parameters
    ----------
    strokes_path : str or Path
        Path to a JSONL file where each line is a JSON stroke record.
    window_size : int
        Number of recent strokes to analyze.
    lookback : int
        How many prior strokes to check for build-on computation.

    Returns
    -------
    dict
        Momentum metrics from :func:`compute_momentum_metrics`.
    """
    path = Path(strokes_path)
    if not path.exists():
        return compute_momentum_metrics([], window_size=window_size)

    strokes: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return compute_momentum_metrics(strokes, window_size=window_size, lookback=lookback)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_momentum_report(metrics: dict[str, Any]) -> str:
    """Format momentum metrics as a human-readable report.

    Parameters
    ----------
    metrics : dict
        Output from :func:`compute_momentum_metrics`.

    Returns
    -------
    str
        Multi-line formatted report string.
    """
    lines = [
        "Writer Momentum Report",
        "=" * 40,
        f"Strokes analyzed:    {metrics['strokes_analyzed']}",
        f"Threads detected:    {metrics['threads_count']}",
        "",
        "Metrics:",
        f"  build_on_rate:       {metrics['build_on_rate']:.4f}",
        f"  continuation_ratio:  {metrics['continuation_ratio']:.4f}",
        f"  depth_per_thread:    {metrics['depth_per_thread']:.4f}",
        f"  fresh_start_rate:    {metrics['fresh_start_rate']:.4f}",
        "",
        f"Momentum score:      {metrics['momentum_score']:.4f}",
        f"Momentum class:      {metrics['momentum_class']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def compute_momentum_trend(
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze how momentum changes across multiple snapshots.

    Parameters
    ----------
    snapshots : list[dict]
        List of momentum metric dicts (from successive time windows).

    Returns
    -------
    dict
        Trend information including:
        - direction: increasing | stable | decreasing
        - delta: score change from first to last snapshot
        - snapshots: number of snapshots analyzed
    """
    if len(snapshots) < 2:
        return {
            "direction": "insufficient_data",
            "delta": 0.0,
            "snapshots": len(snapshots),
        }

    scores = [s.get("momentum_score", 0.0) for s in snapshots]
    delta = scores[-1] - scores[0]

    if delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "delta": round(delta, 4),
        "snapshots": len(snapshots),
        "first_score": scores[0],
        "last_score": scores[-1],
    }


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Return just the trend direction string."""
    return compute_momentum_trend(snapshots)["direction"]
