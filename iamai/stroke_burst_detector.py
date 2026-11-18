#!/usr/bin/env python3
"""stroke_burst_detector — detect burst and drought patterns in the stroke stream.

The writer emits strokes at a nominal cadence (one every ~15 s).  In
practice the gaps between consecutive strokes vary: sometimes three
strokes fire within a second (a **burst**), sometimes the writer goes
silent for minutes or hours (a **drought**).

This module quantifies the *temporal texture* of the stroke stream —
not how many strokes were produced, but *how evenly* they arrive.

Core metrics
------------

=====================  =================================================
metric                 meaning
=====================  =================================================
inter_stroke_gaps      list of float seconds between consecutive strokes
mean_gap               arithmetic mean of all gaps
median_gap             median gap (robust to outliers)
gap_stddev             standard deviation of gaps
cv                     coefficient of variation (stddev / mean);
                       0 = perfectly periodic, >>1 = highly irregular
burst_threshold        gap below which a pair is considered a burst
                       (default: mean_gap * 0.25)
drought_threshold      gap above which a silence is considered a drought
                       (default: mean_gap * 3.0)
burst_events           list of (start_seq, count, span_seconds) tuples
drought_events         list of (after_seq, gap_seconds) tuples
burstiness             fraction of gaps below burst_threshold
drought_fraction       fraction of total time spent in droughts
regularity_score       1 - min(cv, 1.0); 1.0 = clockwork, 0.0 = chaos
=====================  =================================================

Interpretation guide
--------------------

============  =========  =============================================
regularity    grade      meaning
============  =========  =============================================
≥ 0.80        A          clockwork — gaps are nearly constant
0.60–0.79     B          steady — minor jitter, no major disruptions
0.40–0.59     C          uneven — mix of bursts and droughts
0.20–0.39     D          erratic — writer frequently stalls or rushes
< 0.20        F          chaotic — no discernible rhythm
============  =========  =============================================

Burst detection
---------------

A **burst** is a maximal run of consecutive gaps that are all below the
burst threshold.  A single gap of 0.5 s between two strokes is not
interesting; three consecutive gaps of 0.5 s (four strokes in 1.5 s) is.
The module groups consecutive sub-threshold gaps into burst events and
reports the start sequence, stroke count, and total span.

Drought detection
-----------------

A **drought** is any single gap that exceeds the drought threshold.
Unlike bursts, droughts are point events — a single long silence,
regardless of what surrounds it.  The module reports the sequence
number *after* which the silence occurred and the gap duration.

Public API
----------

- ``BurstReport``: dataclass with all metrics
- ``analyze(strokes) -> BurstReport``: full analysis
- ``detect_bursts(gaps, threshold) -> list``: burst event detection
- ``detect_droughts(gaps, threshold) -> list``: drought event detection
- ``inter_stroke_gaps(strokes) -> list``: raw gap extraction
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BurstEvent:
    """A maximal run of rapid-fire strokes."""
    start_seq: int
    count: int
    span_seconds: float


@dataclass
class DroughtEvent:
    """An unusually long silence between two strokes."""
    after_seq: int
    gap_seconds: float


@dataclass
class BurstReport:
    """Complete burst/drought analysis of a stroke stream."""
    inter_stroke_gaps: List[float] = field(default_factory=list)
    mean_gap: float = 0.0
    median_gap: float = 0.0
    gap_stddev: float = 0.0
    cv: float = 0.0
    burst_threshold: float = 0.0
    drought_threshold: float = 0.0
    burst_events: List[BurstEvent] = field(default_factory=list)
    drought_events: List[DroughtEvent] = field(default_factory=list)
    burstiness: float = 0.0
    drought_fraction: float = 0.0
    regularity_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "n_gaps": len(self.inter_stroke_gaps),
            "mean_gap_s": round(self.mean_gap, 2),
            "median_gap_s": round(self.median_gap, 2),
            "gap_stddev_s": round(self.gap_stddev, 2),
            "cv": round(self.cv, 4),
            "burst_threshold_s": round(self.burst_threshold, 2),
            "drought_threshold_s": round(self.drought_threshold, 2),
            "n_bursts": len(self.burst_events),
            "n_droughts": len(self.drought_events),
            "burstiness": round(self.burstiness, 4),
            "drought_fraction": round(self.drought_fraction, 4),
            "regularity_score": round(self.regularity_score, 4),
        }


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _extract_timestamps(strokes: Sequence[Dict[str, Any]]) -> List[datetime]:
    """Extract and sort timestamps from a sequence of stroke dicts."""
    timestamps = [_parse_ts(s["at"]) for s in strokes if "at" in s]
    timestamps.sort()
    return timestamps


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def inter_stroke_gaps(strokes: Sequence[Dict[str, Any]]) -> List[float]:
    """Compute the seconds between each pair of consecutive strokes.

    Parameters
    ----------
    strokes : sequence of dict
        Each dict must have an ``"at"`` key with an ISO-8601 timestamp.

    Returns
    -------
    list of float
        Gap durations in seconds, length = len(strokes) - 1.
    """
    timestamps = _extract_timestamps(strokes)
    if len(timestamps) < 2:
        return []
    gaps = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        gaps.append(max(0.0, delta))
    return gaps


def detect_bursts(
    gaps: Sequence[float],
    threshold: float,
    seq_start: int = 0,
) -> List[BurstEvent]:
    """Identify maximal runs of consecutive gaps below the burst threshold.

    Parameters
    ----------
    gaps : sequence of float
        Inter-stroke gap durations in seconds.
    threshold : float
        Gaps strictly below this value are considered part of a burst.
    seq_start : int
        Sequence number of the first stroke after the first gap.

    Returns
    -------
    list of BurstEvent
    """
    if not gaps or threshold <= 0:
        return []

    events: List[BurstEvent] = []
    run_start: Optional[int] = None
    run_span: float = 0.0

    for i, gap in enumerate(gaps):
        if gap < threshold:
            if run_start is None:
                run_start = i
                run_span = gap
            else:
                run_span += gap
        else:
            if run_start is not None:
                run_len = i - run_start
                if run_len >= 2:  # at least 3 strokes (2 consecutive short gaps)
                    events.append(BurstEvent(
                        start_seq=seq_start + run_start,
                        count=run_len + 1,
                        span_seconds=round(run_span, 3),
                    ))
                run_start = None
                run_span = 0.0

    # flush trailing run
    if run_start is not None:
        run_len = len(gaps) - run_start
        if run_len >= 2:
            events.append(BurstEvent(
                start_seq=seq_start + run_start,
                count=run_len + 1,
                span_seconds=round(run_span, 3),
            ))

    return events


def detect_droughts(
    gaps: Sequence[float],
    threshold: float,
    seq_start: int = 0,
) -> List[DroughtEvent]:
    """Identify individual gaps that exceed the drought threshold.

    Parameters
    ----------
    gaps : sequence of float
        Inter-stroke gap durations in seconds.
    threshold : float
        Gaps strictly above this value are droughts.
    seq_start : int
        Sequence number offset.

    Returns
    -------
    list of DroughtEvent
    """
    if not gaps or threshold <= 0:
        return []

    events: List[DroughtEvent] = []
    for i, gap in enumerate(gaps):
        if gap > threshold:
            events.append(DroughtEvent(
                after_seq=seq_start + i,
                gap_seconds=round(gap, 3),
            ))
    return events


def _compute_regularity(cv: float) -> float:
    """Convert coefficient of variation to a 0–1 regularity score."""
    return max(0.0, min(1.0, 1.0 - max(cv, 0.0)))


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(
    strokes: Sequence[Dict[str, Any]],
    burst_fraction: float = 0.25,
    drought_multiplier: float = 3.0,
    min_burst_run: int = 2,
) -> BurstReport:
    """Run a full burst/drought analysis on a sequence of strokes.

    Parameters
    ----------
    strokes : sequence of dict
        Each dict must have ``"at"`` (ISO-8601 timestamp) and optionally
        ``"seq"`` (integer sequence number).
    burst_fraction : float
        Fraction of mean_gap below which a gap is a burst candidate.
    drought_multiplier : float
        Multiple of mean_gap above which a gap is a drought.
    min_burst_run : int
        Minimum number of consecutive short gaps to qualify as a burst.

    Returns
    -------
    BurstReport
    """
    gaps = inter_stroke_gaps(strokes)
    report = BurstReport(inter_stroke_gaps=gaps)

    if not gaps:
        return report

    report.mean_gap = statistics.mean(gaps)
    report.median_gap = statistics.median(gaps)

    if len(gaps) >= 2:
        report.gap_stddev = statistics.stdev(gaps)
    else:
        report.gap_stddev = 0.0

    report.cv = (report.gap_stddev / report.mean_gap) if report.mean_gap > 0 else 0.0

    # thresholds
    report.burst_threshold = report.mean_gap * burst_fraction
    report.drought_threshold = report.mean_gap * drought_multiplier

    # extract seq start from data
    seq_start = 0
    if strokes and "seq" in strokes[0]:
        try:
            seq_start = int(strokes[0]["seq"])
        except (ValueError, TypeError):
            pass

    # detect events
    report.burst_events = detect_bursts(gaps, report.burst_threshold, seq_start)
    report.drought_events = detect_droughts(gaps, report.drought_threshold, seq_start)

    # burstiness: fraction of gaps below burst threshold
    n_burst_gaps = sum(1 for g in gaps if g < report.burst_threshold)
    report.burstiness = n_burst_gaps / len(gaps) if gaps else 0.0

    # drought fraction: time spent in droughts / total time
    total_time = sum(gaps)
    drought_time = sum(e.gap_seconds for e in report.drought_events)
    report.drought_fraction = (drought_time / total_time) if total_time > 0 else 0.0

    # regularity
    report.regularity_score = _compute_regularity(report.cv)

    return report
