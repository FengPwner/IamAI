#!/usr/bin/env python3
"""stroke_zeitgeber — detect calendar-based rhythms in the stroke stream.

A *zeitgeber* (German: "time-giver") is an external cue that synchronises
a biological or mechanical rhythm.  For the IamAI writer, potential
zeitgebers include:

- the **caretaker loop** (typically hourly or every-N-minutes)
- the **commit batch cycle** (every 600 s ≈ 10 min)
- the **circadian cycle** (human attention waxes and wanes by hour)
- the **weekly cycle** (weekday vs weekend)

This module does not assume any of these exist a priori.  It measures
the *empirical* hourly and weekday distribution of strokes, then asks:
is there a statistically detectable rhythm, or is the output uniform
(i.e. the writer runs 24/7 with no external synchronisation)?

Analysis dimensions
-------------------

===================  =====================================================
metric               meaning
===================  =====================================================
hourly_counts        strokes per hour-of-day (0–23)
hourly_entropy       Shannon entropy of the hourly distribution
hourly_uniformity    normalised uniformity (1.0 = perfectly uniform,
                     0.0 = all strokes in one hour)
peak_hours           hours with above-mean stroke counts
quiet_hours          hours with below-mean/2 stroke counts
weekday_counts       strokes per weekday (0=Mon … 6=Sun)
weekday_entropy      Shannon entropy of the weekday distribution
weekday_uniformity   normalised uniformity
dominant_zeitgeber   the strongest detected signal: "none", "hourly",
                     "daily", or "both"
===================  =====================================================

Detection logic
---------------

The uniformity score is derived from Shannon entropy::

    uniformity = H(observed) / H_max

where ``H_max = log2(N)`` and ``N`` is the number of bins (24 for hours,
7 for weekdays).  A uniformity ≥ 0.85 is considered "no detectable
rhythm" (the writer is effectively 24/7).  Below 0.85, a rhythm is
present and the corresponding zeitgeber is flagged.

Public API
----------
- ``ZeitgeberReport``: dataclass with all analysis dimensions
- ``analyze(strokes, ...) -> ZeitgeberReport``
- ``hourly_distribution(timestamps) -> dict[int, int]``
- ``weekday_distribution(timestamps) -> dict[int, int]``
- ``entropy(counts) -> float``
- ``uniformity(counts) -> float``

Usage::

    from iamai.stroke_zeitgeber import analyze
    import json

    strokes = [json.loads(line) for line in open("data/strokes.jsonl")]
    report = analyze(strokes)
    print(report.dominant_zeitgeber)  # "hourly"
    print(report.peak_hours)          # [9, 10, 14, 15]
    print(report.hourly_uniformity)   # 0.73
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Union


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZeitgeberReport:
    """Complete zeitgeber analysis of a stroke stream."""

    hourly_counts: Dict[int, int]
    weekday_counts: Dict[int, int]
    hourly_entropy: float
    weekday_entropy: float
    hourly_uniformity: float
    weekday_uniformity: float
    peak_hours: List[int]
    quiet_hours: List[int]
    dominant_zeitgeber: str
    total_strokes: int

    @property
    def has_hourly_rhythm(self) -> bool:
        """True if the hourly distribution is non-uniform."""
        return self.hourly_uniformity < 0.85

    @property
    def has_daily_rhythm(self) -> bool:
        """True if the weekday distribution is non-uniform."""
        return self.weekday_uniformity < 0.85

    @property
    def is_24_7(self) -> bool:
        """True if no calendar-based rhythm is detected."""
        return self.dominant_zeitgeber == "none"

    def peak_hours_text(self) -> str:
        """Human-readable peak hours summary."""
        if not self.peak_hours:
            return "no peak hours detected"
        return ", ".join(f"{h:02d}:00" for h in sorted(self.peak_hours))

    def quiet_hours_text(self) -> str:
        """Human-readable quiet hours summary."""
        if not self.quiet_hours:
            return "no quiet hours detected"
        return ", ".join(f"{h:02d}:00" for h in sorted(self.quiet_hours))

    def summary_text(self) -> str:
        """One-line human-readable summary."""
        if self.is_24_7:
            return (
                f"no calendar rhythm detected across {self.total_strokes} strokes; "
                f"output appears 24/7 (hourly uniformity {self.hourly_uniformity:.2f}, "
                f"weekday uniformity {self.weekday_uniformity:.2f})"
            )
        parts = []
        if self.has_hourly_rhythm:
            parts.append(
                f"hourly rhythm present (uniformity {self.hourly_uniformity:.2f}, "
                f"peak: {self.peak_hours_text()})"
            )
        if self.has_daily_rhythm:
            peak_days = [
                ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]
                for d in sorted(self.weekday_counts, key=self.weekday_counts.get, reverse=True)[:3]
            ]
            parts.append(
                f"weekday rhythm present (uniformity {self.weekday_uniformity:.2f}, "
                f"top days: {', '.join(peak_days)})"
            )
        return f"{self.dominant_zeitgeber} zeitgeber — {'; '.join(parts)}"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_ts(raw: Union[str, datetime]) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware datetime."""
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    s = str(raw).strip()
    # Handle Z suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot parse timestamp: {raw!r}")


def _extract_timestamps(strokes: Sequence) -> List[datetime]:
    """Extract and parse timestamps from a stroke sequence.

    Accepts:
    - dicts with "at" key
    - datetime objects
    - ISO-8601 strings
    """
    result = []
    for s in strokes:
        if isinstance(s, dict):
            raw = s.get("at") or s.get("timestamp") or s.get("ts")
            if raw is None:
                continue
            result.append(_parse_ts(raw))
        elif isinstance(s, datetime):
            result.append(_parse_ts(s))
        elif isinstance(s, str):
            result.append(_parse_ts(s))
        else:
            continue
    return result


# ---------------------------------------------------------------------------
# Distribution functions
# ---------------------------------------------------------------------------

def hourly_distribution(timestamps: Sequence[datetime]) -> Dict[int, int]:
    """Count strokes per hour-of-day (0–23, UTC).

    Args:
        timestamps: sequence of timezone-aware datetimes.

    Returns:
        dict mapping hour (0–23) to stroke count.
    """
    counter: Counter = Counter()
    for ts in timestamps:
        utc_hour = ts.astimezone(timezone.utc).hour
        counter[utc_hour] += 1
    # Ensure all 24 hours are present
    return {h: counter.get(h, 0) for h in range(24)}


def weekday_distribution(timestamps: Sequence[datetime]) -> Dict[int, int]:
    """Count strokes per weekday (0=Mon … 6=Sun, UTC).

    Args:
        timestamps: sequence of timezone-aware datetimes.

    Returns:
        dict mapping weekday (0–6) to stroke count.
    """
    counter: Counter = Counter()
    for ts in timestamps:
        utc_weekday = ts.astimezone(timezone.utc).weekday()
        counter[utc_weekday] += 1
    return {d: counter.get(d, 0) for d in range(7)}


# ---------------------------------------------------------------------------
# Entropy and uniformity
# ---------------------------------------------------------------------------

def entropy(counts: Union[Dict, List[int]]) -> float:
    """Compute Shannon entropy (bits) from a count distribution.

    Args:
        counts: dict or list of non-negative integer counts.

    Returns:
        Shannon entropy in bits.  Returns 0.0 if total is 0.
    """
    if isinstance(counts, dict):
        values = list(counts.values())
    else:
        values = list(counts)
    total = sum(values)
    if total == 0:
        return 0.0
    h = 0.0
    for v in values:
        if v > 0:
            p = v / total
            h -= p * math.log2(p)
    return h


def uniformity(counts: Union[Dict, List[int]]) -> float:
    """Compute normalised uniformity (0.0–1.0) from a count distribution.

    ``uniformity = H(observed) / H_max`` where ``H_max = log2(N)``
    and ``N`` is the number of bins.  Returns 1.0 if H_max is 0
    (i.e. only one bin) or if the total count is 0 (no data).

    Args:
        counts: dict or list of non-negative integer counts.

    Returns:
        Float in [0.0, 1.0].  1.0 = perfectly uniform.
    """
    if isinstance(counts, dict):
        values = list(counts.values())
    else:
        values = list(counts)
    total = sum(values)
    if total == 0:
        return 1.0  # no data → treat as uniform (no rhythm detected)
    n = len(values)
    if n <= 1:
        return 1.0
    h_max = math.log2(n)
    if h_max == 0:
        return 1.0
    h = entropy(values)
    return h / h_max


# ---------------------------------------------------------------------------
# Peak / quiet detection
# ---------------------------------------------------------------------------

def _detect_peaks(counts: Dict[int, int], factor: float = 1.2) -> List[int]:
    """Find keys with count > factor × mean."""
    values = list(counts.values())
    total = sum(values)
    if total == 0:
        return []
    mean = total / len(values)
    if mean == 0:
        return []
    return sorted(k for k, v in counts.items() if v > factor * mean)


def _detect_quiets(counts: Dict[int, int], factor: float = 0.5) -> List[int]:
    """Find keys with count < factor × mean and count present."""
    values = list(counts.values())
    total = sum(values)
    if total == 0:
        return []
    mean = total / len(values)
    if mean == 0:
        return []
    return sorted(k for k, v in counts.items() if v < factor * mean and v >= 0)


# ---------------------------------------------------------------------------
# Dominant zeitgeber classification
# ---------------------------------------------------------------------------

_RHYTHM_THRESHOLD = 0.85


def _classify_dominant(hourly_u: float, weekday_u: float) -> str:
    """Classify the dominant zeitgeber from uniformity scores.

    Returns one of: "none", "hourly", "daily", "both".
    """
    hourly_rhythm = hourly_u < _RHYTHM_THRESHOLD
    daily_rhythm = weekday_u < _RHYTHM_THRESHOLD
    if hourly_rhythm and daily_rhythm:
        return "both"
    if hourly_rhythm:
        return "hourly"
    if daily_rhythm:
        return "daily"
    return "none"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(
    strokes: Sequence,
    rhythm_threshold: float = _RHYTHM_THRESHOLD,
) -> ZeitgeberReport:
    """Analyse calendar-based rhythms in a stroke stream.

    Args:
        strokes: sequence of dicts (with "at" key), datetimes, or
                 ISO-8601 strings.
        rhythm_threshold: uniformity below this value indicates a
                          detectable rhythm (default 0.85).

    Returns:
        A ZeitgeberReport with all analysis dimensions.
    """
    timestamps = _extract_timestamps(strokes)
    total = len(timestamps)

    h_dist = hourly_distribution(timestamps)
    w_dist = weekday_distribution(timestamps)

    h_entropy = entropy(h_dist)
    w_entropy = entropy(w_dist)
    h_uniformity = uniformity(h_dist)
    w_uniformity = uniformity(w_dist)

    peak_hours = _detect_peaks(h_dist)
    quiet_hours = _detect_quiets(h_dist)
    dominant = _classify_dominant(h_uniformity, w_uniformity)

    return ZeitgeberReport(
        hourly_counts=h_dist,
        weekday_counts=w_dist,
        hourly_entropy=h_entropy,
        weekday_entropy=w_entropy,
        hourly_uniformity=h_uniformity,
        weekday_uniformity=w_uniformity,
        peak_hours=peak_hours,
        quiet_hours=quiet_hours,
        dominant_zeitgeber=dominant,
        total_strokes=total,
    )
