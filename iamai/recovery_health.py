"""Recovery health — measure how well the writer resumes after a stall.

The stall modules answer *when* and *why* the writer stops.  This module
answers the question that matters more: **after a restart, does it come
back healthy?**

A recovery is characterised by the first ``n`` inter-stroke gaps after
the writer resumes.  We compare those gaps to the expected cadence and
classify the recovery as one of:

- ``"full"``   — post-restart gaps are within tolerance of the target
                  cadence; the writer is back to normal speed.
- ``"limping"`` — gaps are present but significantly longer than target;
                  the writer is producing but sluggish.
- ``"stutter"`` — irregular pattern: fast-slow-fast or long initial
                  delay followed by rapid catch-up.
- ``"dead"``   — no strokes recorded after the restart within the
                  observation window.

Design choices
--------------
- **Pure function.**  Takes a list of post-recovery inter-stroke gaps
  (seconds) and the target cadence; returns a dataclass.
- **No I/O.**  The caller collects the gaps from the log; this module
  only judges them.
- **Small sample handling.**  With fewer than 3 gaps the classification
  is best-effort and flagged ``insufficient_data=True``.

Usage::

    from iamai.recovery_health import assess_recovery

    gaps = [16, 15, 14, 17, 15]  # seconds between strokes
    result = assess_recovery(gaps, target_cadence=15)
    print(result.verdict)   # "full"
    print(result.summary)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecoveryReport:
    """Judgement of post-stall recovery quality."""

    verdict: str                     # full | limping | stutter | dead
    mean_gap: float                  # mean of observed gaps (s)
    target_cadence: float            # expected gap (s)
    ratio: float                     # mean_gap / target_cadence
    jitter: float                    # std-dev of gaps (s)
    sample_count: int                # number of gaps analysed
    insufficient_data: bool = False
    summary: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _std_dev(values: List[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance ** 0.5


def _detect_stutter(gaps: List[float], target: float) -> bool:
    """Detect a stutter pattern: alternating fast/slow or initial delay.

    A stutter is defined as:
    - at least one gap > 3× target AND at least one gap < target, OR
    - the coefficient of variation (std/mean) exceeds 0.6.
    """
    if not gaps:
        return False
    mean = sum(gaps) / len(gaps)
    if mean == 0:
        return False
    cv = _std_dev(gaps) / mean
    has_slow = any(g > 3 * target for g in gaps)
    has_fast = any(g < target for g in gaps)
    return (has_slow and has_fast) or cv > 0.6


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Thresholds (multiples of target cadence)
_LIMP_RATIO = 2.0       # mean gap > 2× target → limping
_DEAD_WINDOW = 10        # if 0 gaps and observation passed → dead

def assess_recovery(
    post_gaps: List[float],
    target_cadence: float = 15.0,
) -> RecoveryReport:
    """Assess recovery health from post-restart inter-stroke gaps.

    Parameters
    ----------
    post_gaps : list of float
        Inter-stroke intervals (seconds) recorded after the writer was
        restarted.  Should be in chronological order.
    target_cadence : float
        Expected inter-stroke interval in seconds (default 15).

    Returns
    -------
    RecoveryReport
    """
    n = len(post_gaps)

    # -- dead: nothing produced ------------------------------------------------
    if n == 0:
        return RecoveryReport(
            verdict="dead",
            mean_gap=0.0,
            target_cadence=target_cadence,
            ratio=0.0,
            jitter=0.0,
            sample_count=0,
            summary="no strokes after restart — writer may be dead",
        )

    mean_gap = sum(post_gaps) / n
    jitter = _std_dev(post_gaps)
    ratio = mean_gap / target_cadence if target_cadence > 0 else 0.0
    insufficient = n < 3

    # -- classify --------------------------------------------------------------
    if _detect_stutter(post_gaps, target_cadence):
        verdict = "stutter"
    elif ratio > _LIMP_RATIO:
        verdict = "limping"
    else:
        verdict = "full"

    summary = (
        f"recovery {verdict}: {n} gaps, "
        f"mean {mean_gap:.1f}s (target {target_cadence:.0f}s, "
        f"ratio {ratio:.2f}×), jitter {jitter:.1f}s"
    )

    return RecoveryReport(
        verdict=verdict,
        mean_gap=mean_gap,
        target_cadence=target_cadence,
        ratio=ratio,
        jitter=jitter,
        sample_count=n,
        insufficient_data=insufficient,
        summary=summary,
    )
