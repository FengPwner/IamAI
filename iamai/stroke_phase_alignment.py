#!/usr/bin/env python3
"""stroke_phase_alignment — measure how strokes align with commit-batch boundaries.

The IamAI commit batch runs on a fixed cycle (default 600 s = 10 min).
Each cycle boundary creates a natural "tick" in the repo timeline.
This module asks: do strokes distribute uniformly across the commit
cycle, or do they cluster at specific phases?

Three behavioural patterns are worth detecting:

1. **Pre-commit rush** — strokes accelerate just before a commit
   boundary, suggesting the writer is "racing to land" work before the
   batch fires.
2. **Post-commit warm-up** — strokes slow down right after a commit and
   gradually resume, indicating a restart tax on the writer loop.
3. **Phase lock** — the writer's cadence resonates with the commit
   cycle, producing a stable phase relationship (a rational ratio of
   cadence to batch period).

These patterns live at the *meso* scale — between ``stroke_cadence_drift``
(micro: inter-stroke gap fidelity) and ``stroke_zeitgeber`` (macro:
calendar rhythms).  They answer the question: does the commit cycle
exert a measurable gravitational pull on the writer's output rhythm?

Core metrics
------------

===========================  ==============================================
metric                       meaning
===========================  ==============================================
batch_period                 the commit cycle length in seconds (default 600)
phases                       normalised phase (0–1) for each stroke within
                             its enclosing batch window
phase_bins                   histogram counts across *n_bins* equal-width
                             bins (default 10 bins of 0.1 each)
entropy                      Shannon entropy of the normalised phase
                             histogram (max = log2(n_bins) ≈ 3.32)
entropy_ratio                entropy / max_entropy; 1.0 = uniform, 0.0 =
                             all strokes in one bin
peak_bin                     the bin index (0-based) with the highest count
peak_fraction                fraction of all strokes in the peak bin
rush_score                   fraction of strokes in the last 20% of the
                             cycle (phase ∈ [0.8, 1.0)); high values
                             suggest pre-commit acceleration
warmup_score                 fraction of strokes in the first 20% of the
                             cycle (phase ∈ [0.0, 0.2)); high values
                             suggest post-commit warm-up effects
alignment_class              "uniform" | "pre_commit_rush" |
                             "post_commit_warmup" | "phase_locked"
rayleigh_r                   circular uniformity statistic (0 = uniform,
                             1 = perfectly concentrated)
rayleigh_p                   p-value for the Rayleigh test of uniformity
===========================  ==============================================

Detection logic
---------------

Each stroke timestamp is reduced to a *phase* value:

    phase = (t − epoch) mod batch_period / batch_period

where *epoch* is an arbitrary reference point (default: Unix epoch).
Phases are then binned into a histogram of width ``n_bins``.

**Alignment classification** uses the following priority:

========================  ========================================
condition                 class
========================  ========================================
rush_score > 0.35         "pre_commit_rush"
warmup_score > 0.35       "post_commit_warmup"
rayleigh_r > 0.3 and
  p < 0.05               "phase_locked"
otherwise                 "uniform"
========================  ========================================

The **Rayleigh test** treats each phase as an angle (0–2π) and measures
the length of the mean resultant vector.  A value near 0 means phases
are spread uniformly around the circle; a value near 1 means they
cluster tightly at one angle.

Public API
----------
- ``PhaseAlignmentReport``: dataclass with all metrics
- ``analyze(strokes, batch_period=600, epoch=None, n_bins=10)
  -> PhaseAlignmentReport``
- ``compute_phase(timestamp, batch_period, epoch) -> float``
- ``phase_histogram(phases, n_bins) -> list[int]``
- ``shannon_entropy(counts) -> float``
- ``rayleigh_test(phases) -> tuple[float, float]``
- ``classify_alignment(rush_score, warmup_score, rayleigh_r,
  rayleigh_p) -> str``

Usage::

    from iamai.stroke_phase_alignment import analyze

    strokes = [...]  # list of stroke dicts with "at" timestamps
    report = analyze(strokes, batch_period=600)
    print(f"class: {report.alignment_class}, entropy_ratio: {report.entropy_ratio:.2f}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class PhaseAlignmentReport:
    """Container for phase-alignment analysis results."""

    batch_period: float = 600.0
    epoch: float = 0.0
    n_bins: int = 10
    total_strokes: int = 0
    phases: List[float] = field(default_factory=list)
    phase_bins: List[int] = field(default_factory=list)
    entropy: float = 0.0
    max_entropy: float = 0.0
    entropy_ratio: float = 0.0
    peak_bin: int = 0
    peak_fraction: float = 0.0
    rush_score: float = 0.0
    warmup_score: float = 0.0
    alignment_class: str = "uniform"
    rayleigh_r: float = 0.0
    rayleigh_p: float = 1.0


# ---------------------------------------------------------------------------
# Timestamp parsing (shared pattern across stroke_* modules)
# ---------------------------------------------------------------------------

def _parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        raise ValueError(f"cannot parse timestamp: {raw!r}")


def _to_epoch_seconds(dt: datetime) -> float:
    """Convert a datetime to seconds since Unix epoch."""
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------

def compute_phase(
    timestamp_seconds: float,
    batch_period: float = 600.0,
    epoch: float = 0.0,
) -> float:
    """Compute the normalised phase (0-1) of a timestamp within its batch window.

    Parameters
    ----------
    timestamp_seconds : float
        Unix timestamp in seconds.
    batch_period : float
        Length of one commit cycle in seconds (default 600).
    epoch : float
        Reference epoch in seconds (default 0 = Unix epoch).

    Returns
    -------
    float
        Phase value in [0, 1).  0.0 = exactly on a boundary,
        0.5 = halfway through the cycle.
    """
    if batch_period <= 0:
        raise ValueError(f"batch_period must be positive, got {batch_period}")
    offset = (timestamp_seconds - epoch) % batch_period
    return offset / batch_period


def phase_histogram(phases: List[float], n_bins: int = 10) -> List[int]:
    """Bin a list of normalised phases into equal-width histogram bins.

    Parameters
    ----------
    phases : list of float
        Phase values in [0, 1).
    n_bins : int
        Number of bins (default 10, each covering 0.1 of the cycle).

    Returns
    -------
    list of int
        Count of phases falling in each bin.
    """
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")
    bins = [0] * n_bins
    for p in phases:
        idx = int(p * n_bins)
        # Clamp to last bin for edge case p == 1.0 (shouldn't happen but
        # guard against floating-point rounding).
        idx = min(idx, n_bins - 1)
        bins[idx] += 1
    return bins


def shannon_entropy(counts: List[int]) -> float:
    """Compute Shannon entropy (base 2) of a discrete distribution.

    Parameters
    ----------
    counts : list of int
        Bin counts (non-negative integers).

    Returns
    -------
    float
        Entropy in bits.  Returns 0.0 if total count is 0.
    """
    total = sum(counts)
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def rayleigh_test(phases: List[float]) -> Tuple[float, float]:
    """Perform the Rayleigh test for circular uniformity.

    Treats each phase as an angle theta = 2*pi*phase and computes the mean
    resultant vector length *r* and the associated p-value.

    Parameters
    ----------
    phases : list of float
        Normalised phases in [0, 1).

    Returns
    -------
    tuple of (float, float)
        (r, p) where r in [0, 1] is the mean resultant length and p is
        the approximate p-value for the null hypothesis of uniformity.
        Small p (< 0.05) rejects uniformity.
    """
    n = len(phases)
    if n < 2:
        return 0.0, 1.0

    # Convert phases to angles in radians.
    cos_sum = sum(math.cos(2 * math.pi * p) for p in phases)
    sin_sum = sum(math.sin(2 * math.pi * p) for p in phases)

    r = math.sqrt(cos_sum ** 2 + sin_sum ** 2) / n

    # Approximate p-value using the Rayleigh formula:
    # z = n * r^2, p ~ exp(-z) * (1 + 2z - z^2/n)
    z = n * r * r
    p = math.exp(-z) * (1 + 2 * z - z ** 2 / n) if n > 0 else 1.0
    # Clamp to [0, 1].
    p = max(0.0, min(1.0, p))

    return r, p


def rush_score(phases: List[float], threshold: float = 0.8) -> float:
    """Fraction of strokes in the final portion of the commit cycle.

    Parameters
    ----------
    phases : list of float
        Normalised phases in [0, 1).
    threshold : float
        Phase value above which a stroke is considered "rushing"
        (default 0.8, i.e. the last 20% of the cycle).

    Returns
    -------
    float
        Fraction of strokes with phase >= threshold.
    """
    if not phases:
        return 0.0
    count = sum(1 for p in phases if p >= threshold)
    return count / len(phases)


def warmup_score(phases: List[float], threshold: float = 0.2) -> float:
    """Fraction of strokes in the initial portion of the commit cycle.

    Parameters
    ----------
    phases : list of float
        Normalised phases in [0, 1).
    threshold : float
        Phase value below which a stroke is considered "warming up"
        (default 0.2, i.e. the first 20% of the cycle).

    Returns
    -------
    float
        Fraction of strokes with phase < threshold.
    """
    if not phases:
        return 0.0
    count = sum(1 for p in phases if p < threshold)
    return count / len(phases)


def classify_alignment(
    rush: float,
    warmup: float,
    r: float,
    p: float,
) -> str:
    """Classify the overall alignment pattern.

    Parameters
    ----------
    rush : float
        Pre-commit rush score (fraction in last 20%).
    warmup : float
        Post-commit warm-up score (fraction in first 20%).
    r : float
        Rayleigh statistic (mean resultant length).
    p : float
        Rayleigh p-value.

    Returns
    -------
    str
        One of "pre_commit_rush", "post_commit_warmup", "phase_locked",
        or "uniform".
    """
    if rush > 0.35:
        return "pre_commit_rush"
    if warmup > 0.35:
        return "post_commit_warmup"
    if r > 0.3 and p < 0.05:
        return "phase_locked"
    return "uniform"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(
    strokes: list,
    batch_period: float = 600.0,
    epoch: Optional[float] = None,
    n_bins: int = 10,
) -> PhaseAlignmentReport:
    """Analyse phase alignment of strokes against the commit-batch cycle.

    Parameters
    ----------
    strokes : list of dict
        Stroke records, each containing at least ``"at"`` (ISO-8601
        timestamp).  Must contain >= 2 strokes for meaningful results.
    batch_period : float
        The commit cycle length in seconds (default 600.0).
    epoch : float or None
        Reference epoch as Unix seconds.  ``None`` uses 0 (Unix epoch).
    n_bins : int
        Number of histogram bins (default 10).

    Returns
    -------
    PhaseAlignmentReport
        Populated analysis report.
    """
    report = PhaseAlignmentReport(
        batch_period=batch_period,
        epoch=epoch if epoch is not None else 0.0,
        n_bins=n_bins,
    )

    # Extract and sort timestamps.
    timestamps_sec = []
    for s in strokes:
        raw = s.get("at", "")
        if raw:
            dt = _parse_ts(raw)
            timestamps_sec.append(_to_epoch_seconds(dt))
    timestamps_sec.sort()
    report.total_strokes = len(timestamps_sec)

    if len(timestamps_sec) < 2:
        return report

    # Compute phases.
    phases = [
        compute_phase(t, batch_period, report.epoch)
        for t in timestamps_sec
    ]
    report.phases = phases

    # Histogram.
    bins = phase_histogram(phases, n_bins)
    report.phase_bins = bins

    # Entropy.
    report.entropy = shannon_entropy(bins)
    report.max_entropy = math.log2(n_bins) if n_bins > 1 else 0.0
    report.entropy_ratio = (
        report.entropy / report.max_entropy
        if report.max_entropy > 0
        else 0.0
    )

    # Peak bin.
    peak_count = max(bins)
    report.peak_bin = bins.index(peak_count)
    report.peak_fraction = peak_count / len(phases) if phases else 0.0

    # Rush and warm-up scores.
    report.rush_score = rush_score(phases)
    report.warmup_score = warmup_score(phases)

    # Rayleigh test.
    r, p = rayleigh_test(phases)
    report.rayleigh_r = r
    report.rayleigh_p = p

    # Classification.
    report.alignment_class = classify_alignment(
        report.rush_score, report.warmup_score, r, p
    )

    return report
