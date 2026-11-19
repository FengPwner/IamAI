"""stroke_burst_analyzer — detect burst patterns in stroke timing.

An auto-writer should produce strokes at a steady cadence.  When strokes
cluster into bursts separated by long silences, something is wrong:
the writer gets stuck, then dumps a backlog in a rush.  This module
identifies bursts, measures their severity, and classifies the overall
temporal distribution.

A **burst** is defined as a maximal run of consecutive strokes whose
inter-stroke gap is below ``burst_threshold`` seconds.  A **silence**
is any gap exceeding ``silence_threshold`` seconds.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             total strokes analysed
total_gaps                number of inter-stroke gaps
mean_gap                  mean gap in seconds
median_gap                median gap in seconds
std_gap                   standard deviation of gaps
burst_count               number of detected bursts
burst_sizes               list of stroke counts per burst
largest_burst             size of the largest burst
mean_burst_size           average burst size
silence_count             number of silences detected
silence_durations         list of silence durations (seconds)
longest_silence           longest silence duration
burstiness_index          0–1; higher means more bursty (cv-based)
regularity_score          0–1; higher means more evenly spaced
cv                        coefficient of variation of gaps
========================  =============================================

Interpretation
--------------

* **burstiness < 0.30** — healthy, steady cadence
* **burstiness 0.30–0.60** — moderate clustering, occasional stalls
* **burstiness > 0.60** — severe burst pattern; pipeline unstable

Edge cases
----------

* Fewer than 2 strokes → zeroed report.
* All gaps identical → cv = 0, burstiness = 0, regularity = 1.
* Negative or zero timestamps are tolerated but gaps < 0 are skipped.

Written by Qwen during caretaker visit 720, 2026-11-19.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ── defaults ──────────────────────────────────────────────────────────

DEFAULT_BURST_THRESHOLD = 20.0    # seconds: gap below this → same burst
DEFAULT_SILENCE_THRESHOLD = 120.0   # seconds: gap above this → silence
DEFAULT_IDEAL_CADENCE = 15.0        # seconds: expected writer cadence


# ── data classes ──────────────────────────────────────────────────────

@dataclass
class BurstReport:
    """Summary of burst analysis over a stroke corpus."""

    total_strokes: int = 0
    total_gaps: int = 0
    mean_gap: float = 0.0
    median_gap: float = 0.0
    std_gap: float = 0.0
    cv: float = 0.0

    burst_count: int = 0
    burst_sizes: List[int] = field(default_factory=list)
    largest_burst: int = 0
    mean_burst_size: float = 0.0

    silence_count: int = 0
    silence_durations: List[float] = field(default_factory=list)
    longest_silence: float = 0.0

    burstiness_index: float = 0.0
    regularity_score: float = 0.0

    def classify(self) -> str:
        """Return a human-readable cadence classification."""
        if self.total_strokes < 2:
            return "insufficient_data"
        if self.burstiness_index < 0.30:
            return "steady"
        if self.burstiness_index < 0.60:
            return "moderate_bursts"
        return "severe_bursts"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "total_strokes": self.total_strokes,
            "total_gaps": self.total_gaps,
            "mean_gap": round(self.mean_gap, 2),
            "median_gap": round(self.median_gap, 2),
            "std_gap": round(self.std_gap, 2),
            "cv": round(self.cv, 4),
            "burst_count": self.burst_count,
            "burst_sizes": self.burst_sizes,
            "largest_burst": self.largest_burst,
            "mean_burst_size": round(self.mean_burst_size, 2),
            "silence_count": self.silence_count,
            "silence_durations": [round(s, 1) for s in self.silence_durations],
            "longest_silence": round(self.longest_silence, 1),
            "burstiness_index": round(self.burstiness_index, 4),
            "regularity_score": round(self.regularity_score, 4),
            "classification": self.classify(),
        }


# ── core analysis ─────────────────────────────────────────────────────

def _extract_timestamps(strokes: Sequence[dict]) -> List[float]:
    """Pull numeric timestamps from stroke dicts.

    Accepts ISO-8601 strings in the ``at`` field (converted to epoch
    via a lightweight parser) or numeric ``ts`` / ``timestamp`` fields.
    """
    from datetime import datetime, timezone

    timestamps: List[float] = []
    for s in strokes:
        ts = s.get("ts") or s.get("timestamp")
        if ts is not None:
            try:
                timestamps.append(float(ts))
                continue
            except (TypeError, ValueError):
                pass
        at = s.get("at")
        if at is not None:
            try:
                dt = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
                timestamps.append(dt.timestamp())
                continue
            except (ValueError, TypeError):
                pass
    return sorted(timestamps)


def _compute_gaps(timestamps: Sequence[float]) -> List[float]:
    """Compute non-negative inter-event gaps."""
    gaps: List[float] = []
    for i in range(1, len(timestamps)):
        g = timestamps[i] - timestamps[i - 1]
        if g >= 0:
            gaps.append(g)
    return gaps


def _detect_bursts(
    gaps: Sequence[float],
    threshold: float,
) -> List[int]:
    """Return sizes of each burst (maximal run of gaps < threshold).

    A single stroke with no sub-threshold neighbours counts as a burst
    of size 1.
    """
    if not gaps:
        return []

    bursts: List[int] = []
    current_run = 1  # first stroke always starts a run

    for g in gaps:
        if g < threshold:
            current_run += 1
        else:
            bursts.append(current_run)
            current_run = 1
    bursts.append(current_run)
    return bursts


def _detect_silences(
    gaps: Sequence[float],
    threshold: float,
) -> List[float]:
    """Return durations of all silences (gaps > threshold)."""
    return [g for g in gaps if g > threshold]


def _burstiness_index(cv: float) -> float:
    """Map coefficient of variation to a 0–1 burstiness score.

    Uses a sigmoid-like transform: ``1 - exp(-cv/2)``.
    cv = 0 → 0 (perfectly regular); cv → ∞ → 1 (extremely bursty).
    """
    if cv <= 0:
        return 0.0
    return 1.0 - math.exp(-cv / 2.0)


def _regularity_score(
    gaps: Sequence[float],
    ideal_cadence: float,
) -> float:
    """Score how close gaps are to the ideal cadence (0–1, higher = better).

    Uses the fraction of gaps within ±50% of the ideal cadence.
    """
    if not gaps:
        return 0.0
    lo = ideal_cadence * 0.5
    hi = ideal_cadence * 1.5
    within = sum(1 for g in gaps if lo <= g <= hi)
    return within / len(gaps)


def analyse_bursts(
    strokes: Sequence[dict],
    *,
    burst_threshold: float = DEFAULT_BURST_THRESHOLD,
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
    ideal_cadence: float = DEFAULT_IDEAL_CADENCE,
) -> BurstReport:
    """Analyse burst patterns in a sequence of strokes.

    Parameters
    ----------
    strokes : sequence of dict
        Each dict should have ``at`` (ISO-8601) or ``ts``/``timestamp``
        (epoch seconds).
    burst_threshold : float
        Gaps shorter than this (seconds) belong to the same burst.
    silence_threshold : float
        Gaps longer than this (seconds) are silences.
    ideal_cadence : float
        Expected inter-stroke interval (seconds).

    Returns
    -------
    BurstReport
    """
    timestamps = _extract_timestamps(strokes)
    if len(timestamps) < 2:
        return BurstReport(total_strokes=len(timestamps))

    gaps = _compute_gaps(timestamps)
    if not gaps:
        return BurstReport(total_strokes=len(timestamps))

    mean_gap = statistics.mean(gaps)
    median_gap = statistics.median(gaps)
    std_gap = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    cv = (std_gap / mean_gap) if mean_gap > 0 else 0.0

    bursts = _detect_bursts(gaps, burst_threshold)
    silences = _detect_silences(gaps, silence_threshold)

    burst_count = sum(1 for b in bursts if b > 1)
    burst_sizes = [b for b in bursts if b > 1]
    largest_burst = max(burst_sizes) if burst_sizes else 0
    mean_burst_size = (
        statistics.mean(burst_sizes) if burst_sizes else 0.0
    )

    silence_count = len(silences)
    longest_silence = max(silences) if silences else 0.0

    bi = _burstiness_index(cv)
    rs = _regularity_score(gaps, ideal_cadence)

    return BurstReport(
        total_strokes=len(timestamps),
        total_gaps=len(gaps),
        mean_gap=mean_gap,
        median_gap=median_gap,
        std_gap=std_gap,
        cv=cv,
        burst_count=burst_count,
        burst_sizes=burst_sizes,
        largest_burst=largest_burst,
        mean_burst_size=mean_burst_size,
        silence_count=silence_count,
        silence_durations=silences,
        longest_silence=longest_silence,
        burstiness_index=bi,
        regularity_score=rs,
    )


# ── file-level convenience ────────────────────────────────────────────

def analyse_strokes_file(
    path: str | Path,
    *,
    burst_threshold: float = DEFAULT_BURST_THRESHOLD,
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
    ideal_cadence: float = DEFAULT_IDEAL_CADENCE,
) -> BurstReport:
    """Load a JSONL strokes file and analyse burst patterns."""
    strokes: List[dict] = []
    p = Path(path)
    if not p.exists():
        return BurstReport()
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return analyse_bursts(
        strokes,
        burst_threshold=burst_threshold,
        silence_threshold=silence_threshold,
        ideal_cadence=ideal_cadence,
    )
