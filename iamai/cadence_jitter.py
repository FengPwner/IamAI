"""cadence_jitter — measure timing irregularity in a stroke sequence.

Existing cadence modules (cadence_adherence, cadence_drift) answer
"how close is the rhythm to the target?" and "is the rhythm shifting
over time?".  Neither answers a simpler question: how *irregular*
is the spacing between consecutive strokes?

A writer hitting exactly every 15 seconds has jitter = 0.  A writer
whose gaps alternate between 10 s and 20 s has the same *mean* gap
but substantial jitter.  Jitter captures this variance.

Design
------

- Input: a list of datetime-convertible timestamps (or pre-computed
  gap seconds).
- Output: a jitter report with standard deviation, coefficient of
  variation (CV), max deviation, and a quality label.

Quality labels
--------------

==========  =====================================================
label       meaning
==========  =====================================================
steady      CV < 0.10 — gaps vary less than 10 % of the mean
regular     CV 0.10–0.25 — normal operating variance
uneven      CV 0.25–0.50 — noticeable irregularity
erratic     CV > 0.50 — highly unpredictable timing
==========  =====================================================

Zero dependencies.  stdlib only.

>>> from datetime import datetime, timezone
>>> ts = [
...     datetime(2026, 10, 18, 0, 0,  0, tzinfo=timezone.utc),
...     datetime(2026, 10, 18, 0, 0, 15, tzinfo=timezone.utc),
...     datetime(2026, 10, 18, 0, 0, 30, tzinfo=timezone.utc),
...     datetime(2026, 10, 18, 0, 0, 45, tzinfo=timezone.utc),
... ]
>>> r = jitter_report(ts)
>>> r["label"]
'steady'
>>> r["cv"]
0.0
>>> r["mean_gap_s"]
15.0

Pre-computed gaps also work:

>>> r2 = jitter_report_from_gaps([15, 15, 15, 15])
>>> r2["label"]
'steady'
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Sequence, Union


# ---------------------------------------------------------------------------
# Label classification
# ---------------------------------------------------------------------------

def classify_jitter(cv: float) -> str:
    """Classify jitter from coefficient of variation.

    Args:
        cv: coefficient of variation (std / mean), non-negative

    Returns:
        One of: "steady", "regular", "uneven", "erratic"

    Examples:
        >>> classify_jitter(0.05)
        'steady'
        >>> classify_jitter(0.15)
        'regular'
        >>> classify_jitter(0.35)
        'uneven'
        >>> classify_jitter(0.60)
        'erratic'
    """
    if cv < 0:
        cv = 0
    if cv < 0.10:
        return "steady"
    if cv < 0.25:
        return "regular"
    if cv < 0.50:
        return "uneven"
    return "erratic"


# ---------------------------------------------------------------------------
# Gap extraction
# ---------------------------------------------------------------------------

def _to_epoch(dt: Union[datetime, float, int]) -> float:
    """Convert a timestamp to epoch seconds."""
    if isinstance(dt, datetime):
        return dt.timestamp()
    return float(dt)


def extract_gaps(timestamps: Sequence[Union[datetime, float, int]]) -> list[float]:
    """Compute consecutive gaps in seconds from a timestamp sequence.

    Args:
        timestamps: ordered sequence of at least 2 timestamps

    Returns:
        list of gap durations in seconds (length = len(timestamps) - 1)

    Examples:
        >>> extract_gaps([0.0, 15.0, 30.0])
        [15.0, 15.0]
    """
    if len(timestamps) < 2:
        return []
    epochs = [_to_epoch(t) for t in timestamps]
    return [round(epochs[i + 1] - epochs[i], 3) for i in range(len(epochs) - 1)]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    """Arithmetic mean."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float], mean: float) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def jitter_report_from_gaps(gaps: list[float]) -> dict[str, Any]:
    """Build a jitter report from pre-computed gap seconds.

    Args:
        gaps: list of consecutive gap durations in seconds

    Returns:
        dict with keys: count, mean_gap_s, std_gap_s, cv, max_gap_s,
        min_gap_s, max_deviation_s, label

    Examples:
        >>> r = jitter_report_from_gaps([10, 20, 10, 20])
        >>> r["label"]
        'uneven'
        >>> r["mean_gap_s"]
        15.0
    """
    if len(gaps) < 2:
        return {
            "count": len(gaps),
            "mean_gap_s": gaps[0] if gaps else 0.0,
            "std_gap_s": 0.0,
            "cv": 0.0,
            "max_gap_s": gaps[0] if gaps else 0.0,
            "min_gap_s": gaps[0] if gaps else 0.0,
            "max_deviation_s": 0.0,
            "label": "steady" if gaps else "steady",
        }

    m = _mean(gaps)
    s = _std(gaps, m)
    cv = s / m if m > 0 else 0.0
    max_dev = max(abs(g - m) for g in gaps)

    return {
        "count": len(gaps),
        "mean_gap_s": round(m, 3),
        "std_gap_s": round(s, 3),
        "cv": round(cv, 4),
        "max_gap_s": round(max(gaps), 3),
        "min_gap_s": round(min(gaps), 3),
        "max_deviation_s": round(max_dev, 3),
        "label": classify_jitter(cv),
    }


def jitter_report(
    timestamps: Sequence[Union[datetime, float, int]],
) -> dict[str, Any]:
    """Build a jitter report from a sequence of timestamps.

    Args:
        timestamps: ordered sequence of at least 2 timestamps
            (datetime objects, or numeric epoch seconds)

    Returns:
        Same dict as jitter_report_from_gaps.

    Examples:
        >>> from datetime import datetime, timezone
        >>> ts = [
        ...     datetime(2026, 10, 18, 0, 0,  0, tzinfo=timezone.utc),
        ...     datetime(2026, 10, 18, 0, 0, 15, tzinfo=timezone.utc),
        ...     datetime(2026, 10, 18, 0, 0, 30, tzinfo=timezone.utc),
        ... ]
        >>> r = jitter_report(ts)
        >>> r["label"]
        'steady'
    """
    gaps = extract_gaps(timestamps)
    return jitter_report_from_gaps(gaps)


# ---------------------------------------------------------------------------
# One-line summary
# ---------------------------------------------------------------------------

def jitter_summary(
    timestamps: Sequence[Union[datetime, float, int]],
) -> str:
    """One-line human-readable jitter summary.

    Examples:
        >>> jitter_summary([0.0, 15.0, 30.0, 45.0])
        '3 gaps: mean 15.0s, std 0.0s, CV 0.00 (steady)'
    """
    gaps = extract_gaps(timestamps)
    r = jitter_report_from_gaps(gaps)
    return (
        f"{r['count']} gaps: "
        f"mean {r['mean_gap_s']}s, "
        f"std {r['std_gap_s']}s, "
        f"CV {r['cv']:.2f} ({r['label']})"
    )
