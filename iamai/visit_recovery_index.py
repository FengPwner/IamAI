"""visit_recovery_index — measure post-visit cadence recovery speed.

After a caretaker visits the repository (runs diagnostics, restarts
processes, commits backlog), the writer needs time to stabilise.
This module quantifies *how fast* the writer returns to its normal
stroke cadence after each visit.

Recovery model
--------------

1. **Baseline cadence** is computed from the 20 strokes *before*
   the visit window — the median inter-stroke gap.
2. **Visit window** is defined by ``visit_start`` → ``visit_end``
   (caller-supplied timestamps).
3. **Post-visit strokes** are collected until either *n* strokes
   appear or a timeout elapses.
4. For each post-visit stroke the running median gap is updated.
   The writer is *recovered* when the running median first drops
   within ``tolerance`` of the baseline.
5. The **recovery index** is ``baseline / actual_recovery_time``,
   clipped to [0, 1].  A score of 1.0 means instant recovery;
   0.0 means the writer never recovered within the window.

Grades
------

========  ============================================================
grade     meaning
========  ============================================================
FAST      recovery index ≥ 0.80 — back to rhythm within ~1 cycle
NORMAL    0.50 ≤ index < 0.80 — a few cycles of warm-up
SLOW      0.20 ≤ index < 0.50 — took noticeably long
STALLED   index < 0.20 — writer did not recover in the window
UNKNOWN   not enough data to compute (fewer than 3 pre-visit strokes)
========  ============================================================

Usage::

    from iamai.visit_recovery_index import compute_recovery

    report = compute_recovery(
        strokes=[...],            # list of stroke dicts with 'at' field
        visit_start=epoch_start,
        visit_end=epoch_end,
        baseline_window=20,       # pre-visit strokes for baseline
        tolerance=0.25,           # ±25 % of baseline counts as recovered
    )
    print(report.index)    # 0.73
    print(report.grade)    # 'NORMAL'
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------

_GRADE_FAST = 0.80
_GRADE_NORMAL = 0.50
_GRADE_SLOW = 0.20

_MIN_PRE_STROKES = 3  # need at least this many to establish a baseline


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RecoveryReport:
    """Result of a single post-visit recovery analysis."""

    baseline_cadence_s: float = 0.0
    """Median inter-stroke gap (seconds) before the visit."""

    recovery_time_s: float = 0.0
    """Seconds from visit_end until cadence returned to baseline."""

    index: float = 0.0
    """Recovery index in [0, 1].  Higher is faster."""

    grade: str = "UNKNOWN"
    """One of FAST, NORMAL, SLOW, STALLED, UNKNOWN."""

    post_stroke_count: int = 0
    """Number of post-visit strokes examined."""

    recovered: bool = False
    """True if the writer reached baseline cadence within the window."""

    detail: str = ""
    """Human-readable summary."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_ts(raw: str) -> float:
    """Parse an ISO-8601 timestamp to a Unix epoch (seconds)."""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _inter_stroke_gaps(epochs: Sequence[float]) -> List[float]:
    """Return the list of consecutive gaps (seconds) between timestamps."""
    if len(epochs) < 2:
        return []
    return [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]


def _classify(index: float) -> str:
    """Map a recovery index to a grade string."""
    if index >= _GRADE_FAST:
        return "FAST"
    if index >= _GRADE_NORMAL:
        return "NORMAL"
    if index >= _GRADE_SLOW:
        return "SLOW"
    return "STALLED"


def _running_median(values: List[float]) -> float:
    """Return the median of a list of floats."""
    if not values:
        return 0.0
    return median(values)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_recovery(
    strokes: Sequence[dict],
    visit_start: float,
    visit_end: float,
    *,
    baseline_window: int = 20,
    tolerance: float = 0.25,
    max_post_strokes: int = 100,
) -> RecoveryReport:
    """Analyse how fast the writer recovered after a caretaker visit.

    Parameters
    ----------
    strokes:
        All strokes (dicts with an ``at`` field, ISO-8601 or epoch str).
    visit_start:
        Unix epoch when the caretaker visit began.
    visit_end:
        Unix epoch when the caretaker visit ended.
    baseline_window:
        Number of pre-visit strokes used to compute the baseline cadence.
    tolerance:
        Fractional tolerance — recovery is declared when the running
        post-visit median gap falls within ``baseline * (1 ± tolerance)``.
    max_post_strokes:
        Maximum number of post-visit strokes to examine.

    Returns
    -------
    RecoveryReport with the computed index and grade.
    """
    if visit_end < visit_start:
        return RecoveryReport(
            detail="visit_end is before visit_start — invalid window"
        )

    # Parse all stroke timestamps to epochs.
    epochs = sorted(_parse_ts(s["at"]) for s in strokes)

    # Split into pre-visit and post-visit.
    pre_epochs = [e for e in epochs if e < visit_start]
    post_epochs = [e for e in epochs if e > visit_end]

    # --- Baseline cadence --------------------------------------------------
    pre_slice = pre_epochs[-baseline_window:] if len(pre_epochs) >= _MIN_PRE_STROKES else pre_epochs
    if len(pre_slice) < _MIN_PRE_STROKES:
        return RecoveryReport(
            detail=f"only {len(pre_slice)} pre-visit strokes — need ≥ {_MIN_PRE_STROKES}"
        )

    pre_gaps = _inter_stroke_gaps(pre_slice)
    baseline = _running_median(pre_gaps)
    if baseline <= 0:
        return RecoveryReport(
            baseline_cadence_s=0.0,
            detail="baseline cadence is zero or negative — strokes may be duplicated",
        )

    # --- Post-visit recovery -----------------------------------------------
    if not post_epochs:
        return RecoveryReport(
            baseline_cadence_s=baseline,
            grade="STALLED",
            detail="no post-visit strokes found",
        )

    post_slice = post_epochs[:max_post_strokes]
    upper_bound = baseline * (1.0 + tolerance)

    # Recovery is measured from the *first* post-visit stroke, not from
    # visit_end — the gap between visit_end and the first stroke is
    # unavoidable scheduling latency, not writer sluggishness.
    first_post = post_slice[0]

    recovery_time = 0.0
    recovered = False

    for i in range(1, len(post_slice)):
        window_gaps = _inter_stroke_gaps(post_slice[: i + 1])
        running_med = _running_median(window_gaps)
        if running_med <= upper_bound and running_med > 0:
            recovery_time = post_slice[i] - first_post
            recovered = True
            break
    else:
        # Never recovered within the window — use total span as recovery_time.
        if len(post_slice) > 1:
            recovery_time = post_slice[-1] - first_post
        else:
            recovery_time = 0.0

    # --- Index -------------------------------------------------------------
    # index = baseline / recovery_time  (clamped to [0, 1]).
    # When recovery_time ≤ baseline the writer recovered within one
    # cadence interval → index = 1.0 (perfect recovery).
    if recovered and recovery_time > 0 and baseline > 0:
        raw_index = baseline / recovery_time
        index = max(0.0, min(1.0, raw_index))
    elif recovered:
        # recovery_time == 0 means the first gap alone was already within
        # bounds — treat as instant recovery.
        index = 1.0
    else:
        index = 0.0

    grade = _classify(index)

    return RecoveryReport(
        baseline_cadence_s=round(baseline, 2),
        recovery_time_s=round(recovery_time, 2),
        index=round(index, 4),
        grade=grade,
        post_stroke_count=len(post_slice),
        recovered=recovered,
        detail=(
            f"baseline={baseline:.1f}s, recovery={recovery_time:.1f}s, "
            f"index={index:.2f} ({grade})"
        ),
    )


def batch_recovery(
    strokes: Sequence[dict],
    visits: Sequence[dict],
    **kwargs,
) -> List[RecoveryReport]:
    """Compute recovery for multiple visits.

    Each visit dict must have ``start`` and ``end`` keys (Unix epochs).

    Returns a list of RecoveryReport, one per visit (same order).
    """
    results = []
    for v in visits:
        report = compute_recovery(
            strokes=strokes,
            visit_start=v["start"],
            visit_end=v["end"],
            **kwargs,
        )
        results.append(report)
    return results
