#!/usr/bin/env python3
"""writer_exploration_balance — measure the explore/exploit tradeoff in writing.

Every stroke a writer produces either **deepens** work they have already
touched (exploitation) or **opens** fresh ground (exploration).  Neither
extreme is healthy: pure exploitation leads to local optima and tunnel
vision; pure exploration produces a scattered codebase with no sustained
thread.  The productive zone is a dynamic balance — long dives punctuated
by deliberate moves to adjacent areas.

This module quantifies that balance by tracking which files each stroke
touches and checking whether those files have been touched before within
a configurable lookback window.

Exploration dimensions
----------------------

========================  ================================================
metric                    meaning
========================  ================================================
exploration_ratio         fraction of files in a stroke that have NOT been
                          touched within the lookback window (new ground)
exploitation_ratio        fraction of files that HAVE been touched before
                          (deepening existing work)
novelty_half_life         how many strokes it takes for a file to go from
                          "fresh" (first seen) to "familiar" (re-touched);
                          shorter = writer returns to work quickly
breadth_index             number of distinct files touched in the window
                          divided by total file-touches; higher = wider
                          but shallower
depth_index               max re-touches of any single file in the window
                          divided by total file-touches; higher = deeper
                          concentration on fewer files
balance_score             composite 0.0–1.0: 0 = pure exploitation;
                          1 = pure exploration; ~0.4–0.6 = healthy balance
balance_class             deepening | broadening | balanced | scattered |
                          tunneling
========================  ================================================

Balance classes
---------------

==============  ============================================================
class           meaning
==============  ============================================================
deepening       score < 0.20 — writer is heavily re-working familiar files;
                risk of tunnel vision but high local quality
balanced-low    0.20 ≤ score < 0.40 — mostly deepening with occasional
                new ground; productive sustained work
balanced        0.40 ≤ score < 0.60 — healthy mix of new and familiar;
                the creative sweet spot
balanced-high   0.60 ≤ score < 0.80 — mostly new ground with some
                revisiting; productive expansion
broadening      score ≥ 0.80 — almost entirely new files; risk of
                surface-level work with no depth
==============  ============================================================

Usage
-----

::

    from iamai.writer_exploration_balance import compute_balance, StrokeRecord

    strokes = [StrokeRecord(timestamp=..., files=[...]), ...]
    result = compute_balance(strokes, lookback=50)
    print(balance_report(result))
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StrokeRecord:
    """A single writing event with its affected files."""

    timestamp: datetime
    files: List[str] = field(default_factory=list)
    message: str = ""


@dataclass
class BalanceResult:
    """Results of an exploration-balance analysis."""

    window_strokes: int
    exploration_ratio: float
    exploitation_ratio: float
    novelty_half_life: float
    breadth_index: float
    depth_index: float
    balance_score: float
    balance_class: str
    file_touch_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class BalanceTrend:
    """How balance scores change across successive windows."""

    direction: str  # increasing | stable | decreasing
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_seen_map(strokes: Sequence[StrokeRecord]) -> Dict[str, int]:
    """Map each file to the index of the stroke where it first appears."""
    seen: Dict[str, int] = {}
    for i, s in enumerate(strokes):
        for f in s.files:
            if f not in seen:
                seen[f] = i
    return seen


def _novelty_half_life(strokes: Sequence[StrokeRecord]) -> float:
    """Median number of strokes between a file's first and second touch.

    Files touched only once are excluded.  Returns ``float('inf')`` when
    no file has been re-touched.
    """
    first: Dict[str, int] = {}
    gaps: List[int] = []
    for i, s in enumerate(strokes):
        for f in s.files:
            if f not in first:
                first[f] = i
            elif first[f] >= 0:
                gaps.append(i - first[f])
                first[f] = -1  # count only first return

    if not gaps:
        return float("inf")
    gaps.sort()
    mid = len(gaps) // 2
    if len(gaps) % 2 == 0:
        return (gaps[mid - 1] + gaps[mid]) / 2.0
    return float(gaps[mid])


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def exploration_ratio(strokes: Sequence[StrokeRecord],
                      lookback: int = 50) -> float:
    """Fraction of file-touches that are to files NOT seen in the lookback.

    For each stroke at index *i*, the lookback set is the union of all
    files in strokes ``[max(0, i - lookback), i)``.  A file in stroke *i*
    is "explored" if it is absent from that set.
    """
    if not strokes:
        return 0.0

    total = 0
    explored = 0
    for i, s in enumerate(strokes):
        lookback_start = max(0, i - lookback)
        seen: set = set()
        for prev in strokes[lookback_start:i]:
            seen.update(prev.files)

        for f in s.files:
            total += 1
            if f not in seen:
                explored += 1

    return round(explored / total, 4) if total > 0 else 0.0


def exploitation_ratio(strokes: Sequence[StrokeRecord],
                       lookback: int = 50) -> float:
    """Complement of exploration_ratio: fraction of re-touched files."""
    return round(1.0 - exploration_ratio(strokes, lookback), 4)


def breadth_index(strokes: Sequence[StrokeRecord]) -> float:
    """Distinct files / total file-touches.  Higher = wider, shallower."""
    if not strokes:
        return 0.0
    all_files: List[str] = []
    for s in strokes:
        all_files.extend(s.files)
    if not all_files:
        return 0.0
    return round(len(set(all_files)) / len(all_files), 4)


def depth_index(strokes: Sequence[StrokeRecord]) -> float:
    """Max re-touches of a single file / total file-touches.  Higher = deeper."""
    if not strokes:
        return 0.0
    counts: Counter = Counter()
    for s in strokes:
        for f in s.files:
            counts[f] += 1
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return round(counts.most_common(1)[0][1] / total, 4)


def classify_balance(score: float) -> str:
    """Classify exploration-exploitation balance from a composite score."""
    if score < 0.20:
        return "deepening"
    elif score < 0.40:
        return "balanced-low"
    elif score < 0.60:
        return "balanced"
    elif score < 0.80:
        return "balanced-high"
    else:
        return "broadening"


def compute_balance(strokes: Sequence[StrokeRecord],
                    lookback: int = 50) -> BalanceResult:
    """Compute exploration-exploitation balance for a sequence of strokes.

    Parameters
    ----------
    strokes : sequence of StrokeRecord
        Strokes ordered oldest-first.
    lookback : int
        Number of prior strokes to consider as "recent memory".

    Returns
    -------
    BalanceResult
    """
    n = len(strokes)
    if n == 0:
        return BalanceResult(
            window_strokes=0,
            exploration_ratio=0.0,
            exploitation_ratio=0.0,
            novelty_half_life=float("inf"),
            breadth_index=0.0,
            depth_index=0.0,
            balance_score=0.5,
            balance_class="balanced",
            file_touch_counts={},
        )

    window = strokes[-lookback:] if n > lookback else list(strokes)

    exp_ratio = exploration_ratio(window, lookback=lookback)
    exploit_ratio = round(1.0 - exp_ratio, 4)
    breadth = breadth_index(window)
    depth = depth_index(window)
    half_life = _novelty_half_life(window)

    # File touch counts for reporting
    counts: Counter = Counter()
    for s in window:
        for f in s.files:
            counts[f] += 1

    # Composite score:
    #   high exploration_ratio  → more exploration  (weight 0.50)
    #   high breadth_index      → more exploration  (weight 0.25)
    #   low depth_index         → more exploration  (weight 0.25)
    balance_score = round(
        0.50 * exp_ratio
        + 0.25 * breadth
        + 0.25 * (1.0 - depth),
        4,
    )

    balance_class = classify_balance(balance_score)

    return BalanceResult(
        window_strokes=len(window),
        exploration_ratio=exp_ratio,
        exploitation_ratio=exploit_ratio,
        novelty_half_life=half_life,
        breadth_index=breadth,
        depth_index=depth,
        balance_score=balance_score,
        balance_class=balance_class,
        file_touch_counts=dict(counts.most_common(20)),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def balance_report(result: BalanceResult) -> str:
    """Human-readable summary of an exploration-balance analysis."""
    half_life_str = (
        f"{result.novelty_half_life:.1f}"
        if result.novelty_half_life != float("inf")
        else "inf (no re-touches)"
    )
    lines = [
        f"Exploration balance ({result.window_strokes} strokes)",
        f"  class:               {result.balance_class}",
        f"  balance score:       {result.balance_score:.2f}",
        f"  exploration ratio:   {result.exploration_ratio:.2%}",
        f"  exploitation ratio:  {result.exploitation_ratio:.2%}",
        f"  novelty half-life:   {half_life_str} strokes",
        f"  breadth index:       {result.breadth_index:.2f}",
        f"  depth index:         {result.depth_index:.2f}",
    ]
    if result.file_touch_counts:
        lines.append("  top files:")
        for fname, count in list(result.file_touch_counts.items())[:10]:
            lines.append(f"    {fname:40s} x{count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def balance_trend(results: Sequence[BalanceResult]) -> BalanceTrend:
    """Classify how balance scores evolve across a series of measurements."""
    if not results:
        return BalanceTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.5,
            latest_score=0.5,
            sample_count=0,
        )

    scores = [r.balance_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = round(latest - earliest, 4)

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return BalanceTrend(
        direction=direction,
        score_delta=delta,
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
