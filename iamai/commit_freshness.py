#!/usr/bin/env python3
"""commit_freshness — measure how recently the codebase has been touched.

A living codebase keeps its files warm: docs updated, tests refreshed,
modules revisited.  A stale codebase accumulates dead zones — files
nobody has looked at in months, modules that quietly rot.

This module answers: **how fresh is the codebase right now, and which
areas are going cold?**

Freshness dimensions
--------------------

========================  ================================================
metric                    meaning
========================  ================================================
mean_age_hours            average hours since last modification across
                          all tracked files (lower = fresher)
median_age_hours          median age — resistant to a single ancient file
                          dragging the mean up
freshness_score           0.0–1.0 composite: 1.0 = everything touched
                          within the freshness horizon; 0.0 = nothing
stale_fraction              fraction of files older than the staleness
                          threshold
hotspot_ratio               fraction of files touched within the "hot"
                          window (default 24 h)
coldest_area               top-level directory with the highest median
                          file age
freshness_class           fresh | warm | tepid | stale | frozen
========================  ================================================

Freshness classes
-----------------

=============  ==========================================================
class          meaning
=============  ==========================================================
fresh          score ≥ 0.80 — most files touched recently
warm           0.60 ≤ score < 0.80 — generally active, some aging
tepid          0.40 ≤ score < 0.60 — mixed; some areas well-maintained
stale          0.20 ≤ score < 0.40 — significant portions untouched
frozen         score < 0.20 — the codebase has gone cold
=============  ==========================================================

Public API
----------
- ``FileAge`` — data class for one file's age information
- ``compute_freshness(file_ages, ...) -> FreshnessResult``
- ``classify_freshness(score) -> str``
- ``freshness_report(result) -> str``
- ``freshness_trend(results) -> FreshnessTrend``

Usage::

    from iamai.commit_freshness import FileAge, compute_freshness
    from datetime import datetime

    now = datetime(2026, 11, 10, 12, 0)
    files = [
        FileAge(path="iamai/foo.py", last_touched=datetime(2026, 11, 10, 10, 0)),
        FileAge(path="tests/test_foo.py", last_touched=datetime(2026, 11, 9, 8, 0)),
    ]
    result = compute_freshness(files, reference_time=now)
    print(result.freshness_class)  # e.g. "warm"
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_STALE_HOURS = 168.0   # 7 days — beyond this a file is "stale"
DEFAULT_HOT_HOURS = 24.0      # 1 day  — within this a file is "hot"
DEFAULT_FRESH_HORIZON_HOURS = 72.0  # 3 days — used for score calculation


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileAge:
    """One file's age relative to a reference point in time."""
    path: str
    last_touched: datetime

    def age_hours(self, reference: datetime) -> float:
        """Hours between *last_touched* and *reference*."""
        delta = reference - self.last_touched
        return max(delta.total_seconds() / 3600.0, 0.0)

    def area(self) -> str:
        """Top-level directory (or '.' for root-level files)."""
        parts = self.path.replace("\\", "/").split("/")
        return parts[0] if len(parts) > 1 else "."


@dataclass
class FreshnessResult:
    """Aggregate freshness measurement for a set of files."""
    mean_age_hours: float
    median_age_hours: float
    freshness_score: float
    stale_fraction: float
    hotspot_ratio: float
    coldest_area: str
    coldest_area_age_hours: float
    freshness_class: str
    total_files: int
    stale_files: int
    hot_files: int
    area_ages: dict = field(default_factory=dict)


@dataclass
class FreshnessTrend:
    """How freshness is changing over successive measurements."""
    direction: str       # improving | stable | decaying
    score_delta: float   # latest score minus earliest score
    latest_class: str
    earliest_class: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_freshness(
    file_ages: Sequence[FileAge],
    *,
    reference_time: Optional[datetime] = None,
    stale_hours: float = DEFAULT_STALE_HOURS,
    hot_hours: float = DEFAULT_HOT_HOURS,
    fresh_horizon_hours: float = DEFAULT_FRESH_HORIZON_HOURS,
) -> FreshnessResult:
    """Compute aggregate freshness for *file_ages*.

    Parameters
    ----------
    file_ages : sequence of FileAge
        Each file with its last-touched timestamp.
    reference_time : datetime, optional
        "Now" for the calculation.  Defaults to ``datetime.utcnow()``.
    stale_hours : float
        Files older than this are counted as stale.
    hot_hours : float
        Files younger than this are counted as hot.
    fresh_horizon_hours : float
        Maximum age that still earns a full 1.0 contribution to the score;
        older files contribute linearly less down to 0.0 at *stale_hours*.
    """
    if reference_time is None:
        reference_time = datetime.utcnow()

    if not file_ages:
        return FreshnessResult(
            mean_age_hours=0.0,
            median_age_hours=0.0,
            freshness_score=0.0,
            stale_fraction=0.0,
            hotspot_ratio=0.0,
            coldest_area="(none)",
            coldest_area_age_hours=0.0,
            freshness_class="frozen",
            total_files=0,
            stale_files=0,
            hot_files=0,
        )

    ages = [fa.age_hours(reference_time) for fa in file_ages]
    n = len(ages)

    mean_age = statistics.mean(ages)
    median_age = statistics.median(ages)

    # --- stale / hot counts ---
    stale_count = sum(1 for a in ages if a > stale_hours)
    hot_count = sum(1 for a in ages if a <= hot_hours)
    stale_frac = stale_count / n
    hot_ratio = hot_count / n

    # --- freshness score ---
    # Each file contributes a value in [0, 1]:
    #   age <= fresh_horizon → 1.0
    #   fresh_horizon < age <= stale_hours → linearly decaying
    #   age > stale_hours → 0.0
    contributions = []
    for a in ages:
        if a <= fresh_horizon_hours:
            contributions.append(1.0)
        elif a >= stale_hours:
            contributions.append(0.0)
        else:
            span = stale_hours - fresh_horizon_hours
            contributions.append(1.0 - (a - fresh_horizon_hours) / span if span > 0 else 0.0)

    score = statistics.mean(contributions) if contributions else 0.0

    # --- per-area median age ---
    area_map: dict[str, list[float]] = {}
    for fa, age in zip(file_ages, ages):
        area_map.setdefault(fa.area(), []).append(age)

    area_medians = {area: statistics.median(v) for area, v in area_map.items()}
    coldest_area = max(area_medians, key=area_medians.get) if area_medians else "(none)"
    coldest_age = area_medians.get(coldest_area, 0.0)

    return FreshnessResult(
        mean_age_hours=round(mean_age, 2),
        median_age_hours=round(median_age, 2),
        freshness_score=round(score, 4),
        stale_fraction=round(stale_frac, 4),
        hotspot_ratio=round(hot_ratio, 4),
        coldest_area=coldest_area,
        coldest_area_age_hours=round(coldest_age, 2),
        freshness_class=classify_freshness(score),
        total_files=n,
        stale_files=stale_count,
        hot_files=hot_count,
        area_ages=area_medians,
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_freshness(score: float) -> str:
    """Map a 0.0–1.0 freshness score to a human-readable class."""
    if score >= 0.80:
        return "fresh"
    if score >= 0.60:
        return "warm"
    if score >= 0.40:
        return "tepid"
    if score >= 0.20:
        return "stale"
    return "frozen"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def freshness_report(result: FreshnessResult) -> str:
    """One-line human summary of a freshness result."""
    return (
        f"freshness={result.freshness_class}  score={result.freshness_score:.2f}  "
        f"mean_age={result.mean_age_hours:.1f}h  median={result.median_age_hours:.1f}h  "
        f"stale={result.stale_files}/{result.total_files}  "
        f"hot={result.hot_files}  coldest_area={result.coldest_area} "
        f"({result.coldest_area_age_hours:.1f}h)"
    )


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def freshness_trend(results: Sequence[FreshnessResult]) -> FreshnessTrend:
    """Determine whether freshness is improving, stable, or decaying.

    Requires at least two results; with fewer, returns a flat/stable trend.
    """
    if len(results) < 2:
        latest = results[-1] if results else None
        return FreshnessTrend(
            direction="stable",
            score_delta=0.0,
            latest_class=latest.freshness_class if latest else "frozen",
            earliest_class=latest.freshness_class if latest else "frozen",
        )

    earliest = results[0]
    latest = results[-1]
    delta = latest.freshness_score - earliest.freshness_score

    if delta > 0.05:
        direction = "improving"
    elif delta < -0.05:
        direction = "decaying"
    else:
        direction = "stable"

    return FreshnessTrend(
        direction=direction,
        score_delta=round(delta, 4),
        latest_class=latest.freshness_class,
        earliest_class=earliest.freshness_class,
    )
