"""gap_anatomy — dissect writer silence gaps to measure their impact.

``stall_root_cause`` diagnoses *why* a stall happened.  ``stroke_freshness``
tells you *how stale* the repo is right now.  Neither answers the
caretaker's deeper question: *what did this gap cost us, and how does
it compare to the others?*

A **gap** is any silence in the stroke log longer than 2x the expected
cadence.  Gaps are inevitable — process reclaims, system maintenance,
overnight stalls, network outages — but not all gaps are equal.  A
five-minute gap during a commit boundary is noise; a four-hour gap at
3 AM is a failure mode.

This module dissects each gap along three axes:

=============  =====================================================
axis           question
=============  =====================================================
severity       how long was the silence relative to the cadence?
missed cost    how many strokes should have been produced but weren't?
recovery       how fast did the writer return to normal cadence?
=============  =====================================================

Severity tiers:

==========  ===============================================
tier        meaning
==========  ===============================================
trivial     2–5x cadence — commit boundary or brief pause
notable     5–20x cadence — short stall, self-recovered
significant 20–100x cadence — process restart likely needed
severe      >100x cadence — overnight stall, external rescue
==========  ===============================================

Recovery patterns (measured from the first 5 post-gap strokes):

=============  =====================================================
pattern        meaning
=============  =====================================================
instant        first post-gap interval is within 2x cadence
gradual        intervals converge to cadence within 5 strokes
stuttering     intervals oscillate between fast and slow
never          no post-gap strokes at all (gap extends to present)
=============  =====================================================

Usage::

    from iamai.gap_anatomy import find_gaps, gap_report, gap_summary

    gaps = find_gaps(strokes_path="data/strokes.jsonl", cadence=15)
    for g in gaps[-5:]:
        print(gap_report(g))

    print(gap_summary(gaps))
    # "42 gaps in 20 days: 31 trivial, 8 notable, 2 significant,
    #  1 severe — total missed ~384 strokes"

Public API
----------

- ``find_gaps(strokes_path, cadence=15, min_multiplier=2.0)``
  → list of gap dicts
- ``classify_gap(duration_seconds, cadence)`` → severity tier string
- ``classify_recovery(intervals, cadence)`` → recovery pattern string
- ``gap_report(gap)`` → one-liner for a single gap
- ``gap_summary(gaps)`` → aggregate one-liner
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Severity thresholds (multiples of cadence)
# ---------------------------------------------------------------------------

SEVERITY_TRIVIAL = 2       # 2–5x cadence
SEVERITY_NOTABLE = 5       # 5–20x
SEVERITY_SIGNIFICANT = 20  # 20–100x
SEVERITY_SEVERE = 100      # >100x

# Recovery analysis window
RECOVERY_STROKES = 5


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

def _empty_gap() -> dict[str, Any]:
    """Return a skeleton gap dict with all expected keys."""
    return {
        "start": "",
        "end": "",
        "duration_seconds": 0.0,
        "severity": "trivial",
        "missed_strokes": 0,
        "recovery": "instant",
    }


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_gap(duration_seconds: float, cadence: int) -> str:
    """Classify a gap's severity based on duration relative to cadence.

    Parameters
    ----------
    duration_seconds:
        Length of the silence in seconds.
    cadence:
        Expected inter-stroke interval in seconds.

    Returns
    -------
    One of "trivial", "notable", "significant", "severe".
    """
    if cadence <= 0:
        return "severe"
    ratio = duration_seconds / cadence
    if ratio >= SEVERITY_SEVERE:
        return "severe"
    if ratio >= SEVERITY_SIGNIFICANT:
        return "significant"
    if ratio >= SEVERITY_NOTABLE:
        return "notable"
    return "trivial"


def classify_recovery(intervals: list[float], cadence: int) -> str:
    """Classify how the writer recovered after a gap.

    Parameters
    ----------
    intervals:
        List of inter-stroke intervals (seconds) for the first few
        strokes after the gap.  Need at least 2 for analysis;
        fewer returns "never" (0) or "instant" (1, within tolerance).
    cadence:
        Expected inter-stroke interval in seconds.

    Returns
    -------
    One of "instant", "gradual", "stuttering", "never".
    """
    if not intervals:
        return "never"
    if len(intervals) == 1:
        return "instant" if intervals[0] <= cadence * 2 else "gradual"

    # Check if first interval is already within tolerance
    if intervals[0] <= cadence * 2:
        return "instant"

    # Check for convergence: each interval gets closer to cadence
    diffs = [abs(iv - cadence) for iv in intervals]
    converging = all(
        diffs[i] >= diffs[i + 1] - cadence * 0.5
        for i in range(len(diffs) - 1)
    )
    if converging and diffs[-1] <= cadence:
        return "gradual"

    # Check for stuttering: high variance in intervals
    if len(intervals) >= 3:
        mean_iv = sum(intervals) / len(intervals)
        variance = sum((iv - mean_iv) ** 2 for iv in intervals) / len(intervals)
        if variance > (cadence * 0.8) ** 2:
            return "stuttering"

    # Default: didn't converge cleanly but isn't stuttering
    return "gradual"


def _missed_strokes(duration_seconds: float, cadence: int) -> int:
    """Estimate how many strokes were missed during a gap."""
    if cadence <= 0:
        return 0
    return max(0, int(duration_seconds / cadence) - 1)


# ---------------------------------------------------------------------------
# Stroke log parsing
# ---------------------------------------------------------------------------


def _load_timestamps(strokes_path: str | Path) -> list[datetime]:
    """Read stroke timestamps from the JSONL log.

    Only parses the ``at`` field; skips malformed lines.
    """
    path = Path(strokes_path)
    if not path.exists():
        return []

    timestamps: list[datetime] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = record.get("at", "")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    timestamps.append(dt)
            except (json.JSONDecodeError, ValueError):
                continue
    return timestamps


# ---------------------------------------------------------------------------
# Gap discovery
# ---------------------------------------------------------------------------


def find_gaps(
    strokes_path: str | Path,
    cadence: int = 15,
    min_multiplier: float = 2.0,
) -> list[dict[str, Any]]:
    """Scan the stroke log and return all gaps exceeding the threshold.

    Parameters
    ----------
    strokes_path:
        Path to ``data/strokes.jsonl``.
    cadence:
        Expected inter-stroke interval in seconds.
    min_multiplier:
        Minimum gap/cadence ratio to qualify as a gap.

    Returns
    -------
    List of gap dicts, sorted chronologically.  Each dict contains:
        start, end, duration_seconds, severity, missed_strokes, recovery.
    """
    timestamps = _load_timestamps(strokes_path)
    if len(timestamps) < 2:
        return []

    threshold = cadence * min_multiplier
    gaps: list[dict[str, Any]] = []

    for i in range(1, len(timestamps)):
        gap_seconds = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if gap_seconds < threshold:
            continue

        # Classify severity
        severity = classify_gap(gap_seconds, cadence)
        missed = _missed_strokes(gap_seconds, cadence)

        # Analyze recovery: collect next RECOVERY_STROKES intervals
        recovery_intervals: list[float] = []
        for j in range(i + 1, min(i + RECOVERY_STROKES + 1, len(timestamps))):
            iv = (timestamps[j] - timestamps[j - 1]).total_seconds()
            recovery_intervals.append(iv)

        recovery = classify_recovery(recovery_intervals, cadence)

        gaps.append({
            "start": timestamps[i - 1].isoformat(),
            "end": timestamps[i].isoformat(),
            "duration_seconds": round(gap_seconds, 1),
            "severity": severity,
            "missed_strokes": missed,
            "recovery": recovery,
        })

    return gaps


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def gap_report(gap: dict[str, Any]) -> str:
    """One-liner describing a single gap.

    >>> gap_report({
    ...     "start": "2026-10-20T03:00:00+00:00",
    ...     "end": "2026-10-20T03:05:30+00:00",
    ...     "duration_seconds": 330.0,
    ...     "severity": "notable",
    ...     "missed_strokes": 21,
    ...     "recovery": "instant",
    ... })
    'gap notable: 330s silence, ~21 strokes missed, recovery instant'
    """
    return (
        f"gap {gap['severity']}: {gap['duration_seconds']:.0f}s silence, "
        f"~{gap['missed_strokes']} strokes missed, "
        f"recovery {gap['recovery']}"
    )


def gap_summary(gaps: list[dict[str, Any]]) -> str:
    """Aggregate summary across all discovered gaps.

    >>> gap_summary([])
    'no gaps found'
    """
    if not gaps:
        return "no gaps found"

    counts = {"trivial": 0, "notable": 0, "significant": 0, "severe": 0}
    total_missed = 0
    total_duration = 0.0

    for g in gaps:
        sev = g.get("severity", "trivial")
        counts[sev] = counts.get(sev, 0) + 1
        total_missed += g.get("missed_strokes", 0)
        total_duration += g.get("duration_seconds", 0.0)

    # Time span
    if len(gaps) >= 2:
        first = datetime.fromisoformat(gaps[0]["start"])
        last = datetime.fromisoformat(gaps[-1]["end"])
        span_days = max(1, (last - first).days)
        span_label = f"in {span_days} days"
    else:
        span_label = "total"

    parts = []
    for tier in ("trivial", "notable", "significant", "severe"):
        if counts[tier]:
            parts.append(f"{counts[tier]} {tier}")

    return (
        f"{len(gaps)} gaps {span_label}: "
        f"{', '.join(parts)} — "
        f"total missed ~{total_missed} strokes "
        f"({total_duration:.0f}s silence)"
    )
