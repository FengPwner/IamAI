#!/usr/bin/env python3
"""stroke_burst_detector — find clustering patterns in stroke timing.

A healthy writer produces strokes at a steady cadence.  A *bursty*
writer fires several strokes in quick succession, then goes quiet
for a long stretch.  Bursts are not necessarily bad — they may
signal a productive burst of creativity — but they do indicate
that the writing rhythm is uneven.

This module analyses a sequence of stroke timestamps and reports:

- **burst_count**: number of detected burst windows
- **burst_fraction**: proportion of strokes that fall inside bursts
- **max_burst_size**: largest burst (consecutive rapid-fire strokes)
- **mean_inter_burst_gap**: average silence between bursts
- **pattern**: a human-readable label

Pattern labels
--------------

===========  =====================================================
label        meaning
===========  =====================================================
steady       no bursts detected — strokes evenly spaced
occasional   1–2 small bursts amid otherwise regular cadence
clustered    multiple bursts, but gaps between them are short
bursty       frequent bursts with long silences in between
===========  =====================================================

Design choices
--------------

- A *burst* is defined as ≥ ``min_burst_size`` consecutive strokes
  whose inter-stroke gap is below ``rapid_threshold_s`` seconds.
- The default threshold is 5 s — half the typical 10–15 s cadence.
- Gaps between bursts are measured from last stroke of one burst
  to first stroke of the next.

Usage::

    from datetime import datetime, timezone
    from iamai.stroke_burst_detector import burst_report

    ts = [datetime(2026, 11, 10, 0, 0, s, tzinfo=timezone.utc)
          for s in [0, 2, 4, 60, 62, 64, 120, 180, 240]]

    r = burst_report(ts)
    print(r["burst_count"])      # 2
    print(r["pattern"])          # "clustered"
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _to_epoch(ts: Any) -> float:
    """Convert a datetime or numeric timestamp to epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        return ts.timestamp()
    raise TypeError(f"unsupported timestamp type: {type(ts).__name__}")


def _compute_gaps(timestamps: Sequence[Any]) -> List[float]:
    """Return inter-stroke gaps in seconds."""
    epochs = [_to_epoch(t) for t in timestamps]
    return [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]


def _find_bursts(
    gaps: Sequence[float],
    rapid_threshold_s: float = 5.0,
    min_burst_size: int = 3,
) -> List[Tuple[int, int]]:
    """Identify burst windows as (start_index, end_index) pairs.

    A burst spans consecutive gaps below the threshold.  The returned
    indices refer to the *stroke* positions (inclusive on both ends),
    so a burst of 3 strokes has indices (i, i+2).
    """
    if not gaps:
        return []

    bursts: List[Tuple[int, int]] = []
    run_start: Optional[int] = None

    for i, gap in enumerate(gaps):
        if gap < rapid_threshold_s:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                burst_end = i  # stroke index = gap index + 1
                size = burst_end - run_start + 1
                if size >= min_burst_size:
                    bursts.append((run_start, burst_end))
                run_start = None

    # handle run that extends to the end
    if run_start is not None:
        burst_end = len(gaps)
        size = burst_end - run_start + 1
        if size >= min_burst_size:
            bursts.append((run_start, burst_end))

    return bursts


def burst_report(
    timestamps: Sequence[Any],
    rapid_threshold_s: float = 5.0,
    min_burst_size: int = 3,
) -> Dict[str, Any]:
    """Analyse stroke timestamps for burst patterns.

    Parameters
    ----------
    timestamps:
        Ordered sequence of datetime objects or epoch-seconds.
    rapid_threshold_s:
        Inter-stroke gap (seconds) below which strokes are "rapid".
    min_burst_size:
        Minimum consecutive rapid strokes to count as a burst.

    Returns
    -------
    dict with keys: burst_count, burst_fraction, max_burst_size,
    mean_inter_burst_gap, pattern, bursts.
    """
    n = len(timestamps)
    if n < 2:
        return {
            "burst_count": 0,
            "burst_fraction": 0.0,
            "max_burst_size": 0,
            "mean_inter_burst_gap": 0.0,
            "pattern": "steady" if n <= 1 else "steady",
            "bursts": [],
        }

    gaps = _compute_gaps(timestamps)
    bursts = _find_bursts(gaps, rapid_threshold_s, min_burst_size)

    # count strokes inside bursts
    strokes_in_bursts = sum(end - start + 1 for start, end in bursts)
    burst_fraction = strokes_in_bursts / n if n else 0.0

    # max burst size
    max_burst = max((end - start + 1 for start, end in bursts), default=0)

    # inter-burst gaps
    inter_burst_gaps: List[float] = []
    epochs = [_to_epoch(t) for t in timestamps]
    for i in range(len(bursts) - 1):
        _, prev_end = bursts[i]
        next_start, _ = bursts[i + 1]
        gap = epochs[next_start] - epochs[prev_end]
        inter_burst_gaps.append(gap)

    mean_inter_burst = (
        sum(inter_burst_gaps) / len(inter_burst_gaps)
        if inter_burst_gaps
        else 0.0
    )

    # classify pattern
    pattern = _classify(
        burst_count=len(bursts),
        burst_fraction=burst_fraction,
        mean_inter_burst_gap=mean_inter_burst,
    )

    return {
        "burst_count": len(bursts),
        "burst_fraction": round(burst_fraction, 4),
        "max_burst_size": max_burst,
        "mean_inter_burst_gap": round(mean_inter_burst, 2),
        "pattern": pattern,
        "bursts": bursts,
    }


def _classify(
    burst_count: int,
    burst_fraction: float,
    mean_inter_burst_gap: float,
) -> str:
    """Assign a human-readable pattern label."""
    if burst_count == 0:
        return "steady"
    if burst_count <= 2 and burst_fraction < 0.3:
        return "occasional"
    if mean_inter_burst_gap > 0 and mean_inter_burst_gap < 60:
        return "clustered"
    return "bursty"


def burst_timeline(
    timestamps: Sequence[Any],
    rapid_threshold_s: float = 5.0,
    min_burst_size: int = 3,
) -> str:
    """Return a compact ASCII timeline showing burst regions.

    Bursts are marked with ``█``, regular strokes with ``·``,
    and gaps with ``─``.

    >>> from datetime import datetime, timezone
    >>> ts = [datetime(2026,11,10,0,0,s, tzinfo=timezone.utc)
    ...       for s in [0,2,4,60,62,64,180,300]]
    >>> print(burst_timeline(ts))
    ███─███──·─·
    """
    if not timestamps:
        return ""

    epochs = [_to_epoch(t) for t in timestamps]
    gaps = _compute_gaps(timestamps)
    bursts = _find_bursts(gaps, rapid_threshold_s, min_burst_size)

    # build a set of stroke indices that are in bursts
    burst_indices: set = set()
    for start, end in bursts:
        for i in range(start, end + 1):
            burst_indices.add(i)

    chars: List[str] = []
    for i in range(len(timestamps)):
        if i in burst_indices:
            chars.append("█")
        else:
            chars.append("·")
        if i < len(timestamps) - 1:
            gap = epochs[i + 1] - epochs[i]
            if gap < rapid_threshold_s:
                chars.append("")  # no separator inside burst
            elif gap < 30:
                chars.append("─")
            else:
                chars.append("──")

    return "".join(chars)
