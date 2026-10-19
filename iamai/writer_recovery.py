"""Measure how well a writer recovers after a stall event.

A stall is inevitable in any long-running automation: the process
crashes, the cloud VM gets recycled, the network blips. What matters
is not that it stopped, but *how it came back*.

``writer_recovery`` looks at the gap before and after a restart and
classifies the recovery into one of four qualities:

- **full** — the writer resumed at or above its pre-stall cadence
- **partial** — the writer resumed but at a degraded pace
- **fragile** — the writer resumed but stalled again within the
  observation window
- **failed** — the writer did not produce any strokes after restart

The scoring is deliberately simple: it compares the observed post-
restart cadence against the expected cadence, and penalizes repeated
stalls. No ML, no heuristics beyond arithmetic.

Usage::

    from iamai.writer_recovery import recovery_quality
    result = recovery_quality(
        expected_cadence_seconds=15,
        post_restart_gaps=[16, 15, 17, 14, 16],
        observation_window_seconds=300,
        stalled_again=False,
    )
    print(result["quality"])    # "full"
    print(result["ratio"])      # ~0.94
    print(result["advice"])     # "Recovery nominal."
"""

from __future__ import annotations

from typing import Any


# Quality thresholds (ratio of actual cadence to expected)
_FULL_THRESHOLD = 0.80       # post cadence is within 80% of expected
_PARTIAL_THRESHOLD = 0.40    # below 80% but above 40%
# below 40% → fragile (if not stalled again)

# How many seconds after restart we consider "observation window"
_DEFAULT_OBSERVATION_WINDOW = 300  # 5 minutes


def _median(values: list[float]) -> float:
    """Return the median of a list of numbers. Empty list → 0."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _compute_ratio(
    expected_cadence_seconds: int,
    post_restart_gaps: list[int | float],
) -> float:
    """Compute how close the post-restart cadence is to expected.

    Returns a float in [0, ∞) where 1.0 means exact match.
    Values > 1.0 mean the writer is *faster* than expected (good).
    Values near 0 mean the writer is much slower.
    """
    if not post_restart_gaps or expected_cadence_seconds <= 0:
        return 0.0
    median_gap = _median([float(g) for g in post_restart_gaps])
    if median_gap <= 0:
        return float("inf")
    return expected_cadence_seconds / median_gap


def recovery_quality(
    expected_cadence_seconds: int,
    post_restart_gaps: list[int | float],
    observation_window_seconds: int = _DEFAULT_OBSERVATION_WINDOW,
    stalled_again: bool = False,
) -> dict[str, Any]:
    """Classify how well the writer recovered after a restart.

    Args:
        expected_cadence_seconds: the writer's target stroke interval
        post_restart_gaps: list of actual inter-stroke gaps (seconds)
            observed after the restart. Empty means no strokes produced.
        observation_window_seconds: how long (seconds) we watched
            after restart (used for context, not scoring)
        stalled_again: True if the writer stalled again within the
            observation window

    Returns:
        Dict with keys:
        - quality: str ("full" | "partial" | "fragile" | "failed")
        - ratio: float, expected/actual cadence ratio (0 if no strokes)
        - median_gap: float, median post-restart gap in seconds
        - stroke_count: int, number of post-restart strokes observed
        - observation_window: int, seconds watched
        - advice: str, one actionable sentence
    """
    stroke_count = len(post_restart_gaps)

    # No strokes at all → failed
    if stroke_count == 0:
        return {
            "quality": "failed",
            "ratio": 0.0,
            "median_gap": 0.0,
            "stroke_count": 0,
            "observation_window": observation_window_seconds,
            "advice": (
                "Writer produced no strokes after restart — "
                "check logs and process status immediately."
            ),
        }

    median_gap = _median([float(g) for g in post_restart_gaps])
    ratio = _compute_ratio(expected_cadence_seconds, post_restart_gaps)

    # Stalled again → fragile regardless of ratio
    if stalled_again:
        return {
            "quality": "fragile",
            "ratio": round(ratio, 3),
            "median_gap": round(median_gap, 1),
            "stroke_count": stroke_count,
            "observation_window": observation_window_seconds,
            "advice": (
                "Writer restarted but stalled again — investigate root cause "
                "(resource pressure, lock contention, or config drift)."
            ),
        }

    # Classify by ratio
    if ratio >= _FULL_THRESHOLD:
        quality = "full"
        advice = "Recovery nominal — writer resumed at expected cadence."
    elif ratio >= _PARTIAL_THRESHOLD:
        quality = "partial"
        advice = (
            "Writer resumed but slower than expected — "
            "monitor for further degradation."
        )
    else:
        quality = "fragile"
        advice = (
            "Writer resumed but cadence is severely degraded — "
            "treat as a soft failure and investigate."
        )

    return {
        "quality": quality,
        "ratio": round(ratio, 3),
        "median_gap": round(median_gap, 1),
        "stroke_count": stroke_count,
        "observation_window": observation_window_seconds,
        "advice": advice,
    }
