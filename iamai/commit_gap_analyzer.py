#!/usr/bin/env python3
"""commit_gap_analyzer — classify commit gaps into health patterns.

A commit gap is the elapsed seconds between two consecutive commits.
Healthy automated repos have a characteristic gap distribution
dictated by their commit cadence; deviations signal process stalls,
container recycling, or writer back-pressure.

This module classifies each gap into one of four bands:

- **nominal**   — within expected cadence tolerance (±30 %)
- **jitter**    — outside tolerance but < 3× cadence (normal variance)
- **stall**     — 3×–10× cadence (something paused and recovered)
- **outage**    — > 10× cadence (container recycle or long downtime)

It also produces series-level diagnostics:

- **cadence_adherence**: fraction of gaps that are nominal or jitter
- **mean_gap_ratio**: average (actual_gap / expected_gap)
- **stall_rate**: fraction of gaps classified as stall or outage
- **gap_entropy**: Shannon entropy of the band distribution
  (low = predictable rhythm, high = erratic behaviour)
- **recovery_count**: number of stall→nominal or outage→nominal
  transitions (measures self-healing frequency)

Design notes
------------

- Pure functions, no I/O — timestamps in, diagnostics out.
- ``expected_cadence`` is caller-supplied (seconds); defaults to 600
  (10 min) which matches the standard batch committer interval.
- Band thresholds are multiples of expected_cadence, not absolute
  seconds — a 5-minute cadence repo and a 15-minute cadence repo
  are evaluated on the same relative scale.
- Gap entropy uses log base 2 so the unit is bits; a perfectly
  uniform rhythm across 4 bands scores 2.0 bits, while a repo
  that only ever has nominal gaps scores 0.0.
- Recovery detection is a simple transition count: band[i-1] in
  {stall, outage} and band[i] in {nominal, jitter}.  This captures
  "the system healed itself" moments without needing external state.

Relationship to other modules
-----------------------------

- **cadence_jitter** measures per-stroke timing variance; this
  module measures per-commit gap health — coarser granularity,
  different signal.
- **commit_rhythm_drift** tracks long-term trend changes in
  cadence; commit_gap_analyzer classifies individual gaps
  regardless of trend.
- **writer_recovery_monitor** detects process-level restarts;
  this module detects the *gap signature* of restarts (outage
  bands) without needing process state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# band definitions
# ---------------------------------------------------------------------------

NOMINAL = "nominal"
JITTER = "jitter"
STALL = "stall"
OUTAGE = "outage"

_BANDS = (NOMINAL, JITTER, STALL, OUTAGE)

# Multiples of expected_cadence that define band boundaries.
# A gap is NOMINAL if ratio <= NOMINAL_UPPER, etc.
NOMINAL_UPPER = 1.30   # ±30 % tolerance
JITTER_UPPER = 3.0     # up to 3× cadence
STALL_UPPER = 10.0     # 3×–10× cadence
# anything above STALL_UPPER is OUTAGE


# ---------------------------------------------------------------------------
# per-gap classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GapClass:
    """Classification of a single commit gap."""
    gap_seconds: float
    ratio: float          # gap / expected_cadence
    band: str             # one of _BANDS


def classify_gap(gap_seconds: float, expected_cadence: float = 600.0) -> GapClass:
    """Classify one gap into a health band.

    Args:
        gap_seconds: elapsed seconds between two consecutive commits.
        expected_cadence: the target commit interval in seconds.

    Returns:
        GapClass with the gap, ratio, and band.

    Raises:
        ValueError: if expected_cadence <= 0 or gap_seconds < 0.
    """
    if expected_cadence <= 0:
        raise ValueError(f"expected_cadence must be positive, got {expected_cadence}")
    if gap_seconds < 0:
        raise ValueError(f"gap_seconds must be non-negative, got {gap_seconds}")

    ratio = gap_seconds / expected_cadence

    if ratio <= NOMINAL_UPPER:
        band = NOMINAL
    elif ratio <= JITTER_UPPER:
        band = JITTER
    elif ratio <= STALL_UPPER:
        band = STALL
    else:
        band = OUTAGE

    return GapClass(gap_seconds=gap_seconds, ratio=ratio, band=band)


def classify_gaps(
    gaps: Sequence[float],
    expected_cadence: float = 600.0,
) -> List[GapClass]:
    """Classify a sequence of gaps."""
    return [classify_gap(g, expected_cadence) for g in gaps]


# ---------------------------------------------------------------------------
# gaps from timestamps
# ---------------------------------------------------------------------------


def gaps_from_timestamps(timestamps: Sequence[float]) -> List[float]:
    """Compute inter-commit gaps from a sorted timestamp sequence.

    Args:
        timestamps: monotonically non-decreasing epoch seconds.

    Returns:
        List of gap durations (len = len(timestamps) - 1).
        Returns [] if fewer than 2 timestamps.
    """
    if len(timestamps) < 2:
        return []
    return [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]


# ---------------------------------------------------------------------------
# series-level diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GapDiagnostics:
    """Aggregate health metrics for a commit gap series."""
    total_gaps: int
    band_counts: Dict[str, int]
    cadence_adherence: float     # (nominal + jitter) / total
    mean_gap_ratio: float        # avg(actual / expected)
    stall_rate: float            # (stall + outage) / total
    gap_entropy: float           # Shannon entropy in bits
    recovery_count: int          # stall/outage → nominal/jitter transitions
    worst_gap: float             # largest single gap in seconds
    worst_band: str              # band of the worst gap


def _shannon_entropy(counts: Dict[str, int]) -> float:
    """Compute Shannon entropy (bits) from a category → count mapping."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def _count_recoveries(bands: Sequence[str]) -> int:
    """Count transitions from degraded (stall/outage) to healthy (nominal/jitter)."""
    if len(bands) < 2:
        return 0
    degraded = {STALL, OUTAGE}
    healthy = {NOMINAL, JITTER}
    count = 0
    for i in range(1, len(bands)):
        if bands[i - 1] in degraded and bands[i] in healthy:
            count += 1
    return count


def diagnose(
    gaps: Sequence[float],
    expected_cadence: float = 600.0,
) -> GapDiagnostics:
    """Produce series-level diagnostics from a gap sequence.

    Args:
        gaps: inter-commit gap durations in seconds.
        expected_cadence: target commit interval in seconds.

    Returns:
        GapDiagnostics summarising the health of the commit rhythm.
        If gaps is empty, all metrics are zero.
    """
    if not gaps:
        return GapDiagnostics(
            total_gaps=0,
            band_counts={b: 0 for b in _BANDS},
            cadence_adherence=0.0,
            mean_gap_ratio=0.0,
            stall_rate=0.0,
            gap_entropy=0.0,
            recovery_count=0,
            worst_gap=0.0,
            worst_band=NOMINAL,
        )

    classified = classify_gaps(gaps, expected_cadence)
    band_counts: Dict[str, int] = {b: 0 for b in _BANDS}
    for gc in classified:
        band_counts[gc.band] += 1

    total = len(classified)
    nominal_jitter = band_counts[NOMINAL] + band_counts[JITTER]
    stall_outage = band_counts[STALL] + band_counts[OUTAGE]

    ratios = [gc.ratio for gc in classified]
    mean_ratio = sum(ratios) / total

    bands_seq = [gc.band for gc in classified]
    recovery = _count_recoveries(bands_seq)
    entropy = _shannon_entropy(band_counts)

    worst_idx = max(range(total), key=lambda i: classified[i].gap_seconds)

    return GapDiagnostics(
        total_gaps=total,
        band_counts=band_counts,
        cadence_adherence=nominal_jitter / total,
        mean_gap_ratio=mean_ratio,
        stall_rate=stall_outage / total,
        gap_entropy=entropy,
        recovery_count=recovery,
        worst_gap=classified[worst_idx].gap_seconds,
        worst_band=classified[worst_idx].band,
    )
