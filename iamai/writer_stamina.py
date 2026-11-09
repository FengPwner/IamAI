#!/usr/bin/env python3
"""writer_stamina — measure how long the writer sustains output before degradation.

A writer that produces strokes at a steady cadence for hours is *stamina-*
*ful*.  One that sprints for twenty minutes then stalls or degrades into
repetitive content has low stamina.  This module quantifies that property
by analysing the time-series of stroke intervals and detecting the onset
of decay.

Concepts
--------

==================  ====================================================
metric              meaning
==================  ====================================================
``sustain_s``       seconds of continuous output above quality bar
``decay_onset``     index where cadence first degrades past threshold
``decay_profile``   ``gradual`` | ``cliff`` | ``oscillating`` | ``none``
``stamina_score``   0–100 composite (higher = longer sustained output)
``peak_run``        longest consecutive run of on-cadence strokes
``efficiency``      fraction of session spent in productive output
==================  ====================================================

Decay detection
---------------

For each stroke we compute the local cadence (rolling mean of the last
*window* intervals).  If that cadence exceeds ``target_gap * drift_factor``
for at least ``min_decay_run`` consecutive strokes, we mark the onset of
decay.  The *profile* is classified by looking at how cadence behaves
after the onset:

- **cliff** — cadence jumps >3× target within 5 strokes of onset
- **gradual** — cadence creeps up monotonically for ≥10 strokes
- **oscillating** — cadence alternates between good and bad
- **none** — no sustained decay detected

Usage::

    from iamai.writer_stamina import compute_stamina

    intervals = [15.1, 14.9, 15.3, 15.0, ...]   # seconds between strokes
    report = compute_stamina(intervals, target_gap=15)
    print(report.stamina_score)     # 78
    print(report.decay_profile)     # "gradual"
    print(report.sustain_s)         # 4320.0
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StaminaReport:
    """Result of a stamina analysis."""

    total_strokes: int
    target_gap_s: float
    sustain_s: float
    sustain_strokes: int
    peak_run: int
    decay_onset: Optional[int]
    decay_profile: str
    stamina_score: int
    efficiency: float
    mean_cadence_s: float
    median_cadence_s: float

    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.total_strokes == 0:
            return "no strokes to analyse"
        onset = self.decay_onset if self.decay_onset is not None else "n/a"
        return (
            f"stamina={self.stamina_score}/100  "
            f"sustain={self.sustain_s:.0f}s ({self.sustain_strokes} strokes)  "
            f"peak_run={self.peak_run}  "
            f"decay={self.decay_profile}@{onset}  "
            f"eff={self.efficiency:.1%}"
        )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_stamina(
    intervals: Sequence[float],
    *,
    target_gap: float = 15.0,
    window: int = 20,
    drift_factor: float = 2.0,
    min_decay_run: int = 5,
) -> StaminaReport:
    """Analyse writer stamina from a series of inter-stroke intervals.

    Parameters
    ----------
    intervals : sequence of float
        Seconds between consecutive strokes.
    target_gap : float
        Expected seconds between strokes (default 15).
    window : int
        Rolling-window size for cadence estimation.
    drift_factor : float
        Cadence above ``target_gap × drift_factor`` counts as degraded.
    min_decay_run : int
        Minimum consecutive degraded strokes to declare decay onset.

    Returns
    -------
    StaminaReport
    """
    intervals = list(intervals)
    n = len(intervals)

    if n == 0:
        return StaminaReport(
            total_strokes=0,
            target_gap_s=target_gap,
            sustain_s=0.0,
            sustain_strokes=0,
            peak_run=0,
            decay_onset=None,
            decay_profile="none",
            stamina_score=0,
            efficiency=0.0,
            mean_cadence_s=0.0,
            median_cadence_s=0.0,
        )

    # --- Rolling cadence ------------------------------------------------
    cadence = _rolling_mean(intervals, window)
    threshold = target_gap * drift_factor

    # --- Good/bad classification per stroke -----------------------------
    is_good = [c <= threshold for c in cadence]

    # --- Peak run of consecutive good strokes ---------------------------
    peak_run = _max_consecutive_true(is_good)

    # --- Decay onset detection ------------------------------------------
    decay_onset = _find_decay_onset(is_good, min_decay_run)

    # --- Sustain: time from start to decay onset (or end) ---------------
    if decay_onset is not None and decay_onset > 0:
        sustain_strokes = decay_onset
        sustain_s = sum(intervals[:decay_onset])
    else:
        sustain_strokes = n
        sustain_s = sum(intervals)

    # --- Decay profile classification -----------------------------------
    decay_profile = classify_decay(
        cadence, decay_onset, target_gap, drift_factor
    )

    # --- Efficiency: fraction of strokes that are "good" ----------------
    good_count = sum(is_good)
    efficiency = good_count / n if n > 0 else 0.0

    # --- Stamina score (0-100) ------------------------------------------
    stamina_score = _compute_score(
        sustain_s, sustain_strokes, n, peak_run, efficiency, decay_profile
    )

    return StaminaReport(
        total_strokes=n,
        target_gap_s=target_gap,
        sustain_s=sustain_s,
        sustain_strokes=sustain_strokes,
        peak_run=peak_run,
        decay_onset=decay_onset,
        decay_profile=decay_profile,
        stamina_score=stamina_score,
        efficiency=efficiency,
        mean_cadence_s=mean(cadence),
        median_cadence_s=median(cadence),
    )


# ---------------------------------------------------------------------------
# Decay classification
# ---------------------------------------------------------------------------

def classify_decay(
    cadence: Sequence[float],
    onset: Optional[int],
    target_gap: float,
    drift_factor: float,
) -> str:
    """Classify the shape of cadence decay after onset.

    Returns one of: ``"none"``, ``"cliff"``, ``"gradual"``, ``"oscillating"``.
    """
    if onset is None:
        return "none"

    after = list(cadence[onset:])
    if len(after) < 3:
        return "none"

    threshold = target_gap * drift_factor

    # Cliff: cadence jumps >3× target within 5 strokes of onset
    cliff_zone = after[: min(5, len(after))]
    if any(c > target_gap * 3 for c in cliff_zone):
        return "cliff"

    # Gradual: monotonic increase for ≥10 strokes after onset
    check_len = min(len(after), max(10, len(after) // 2))
    segment = after[:check_len]
    increasing = sum(
        1 for i in range(1, len(segment)) if segment[i] >= segment[i - 1]
    )
    if increasing >= len(segment) - 2:  # allow 2 non-increasing
        return "gradual"

    # Oscillating: alternates between good and bad
    good_bad = [c <= threshold for c in after]
    transitions = sum(
        1 for i in range(1, len(good_bad)) if good_bad[i] != good_bad[i - 1]
    )
    if transitions >= len(after) * 0.3:
        return "oscillating"

    return "gradual"


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_intervals_from_jsonl(
    path: str | Path,
    max_strokes: int = 500,
) -> List[float]:
    """Load inter-stroke intervals from a JSONL strokes file.

    Reads the last *max_strokes* entries and computes intervals from
    their timestamps.
    """
    path = Path(path)
    if not path.exists():
        return []

    lines = path.read_text().strip().splitlines()
    recent = lines[-max_strokes:] if len(lines) > max_strokes else lines

    timestamps: list[float] = []
    for line in recent:
        try:
            entry = json.loads(line)
            ts = entry.get("at") or entry.get("timestamp")
            if ts is not None:
                timestamps.append(float(ts))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    timestamps.sort()
    return [
        timestamps[i] - timestamps[i - 1]
        for i in range(1, len(timestamps))
        if timestamps[i] - timestamps[i - 1] > 0
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rolling_mean(values: Sequence[float], window: int) -> List[float]:
    """Compute a rolling mean with the given window size."""
    result: list[float] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        segment = values[start : i + 1]
        result.append(mean(segment))
    return result


def _max_consecutive_true(flags: Sequence[bool]) -> int:
    """Find the longest run of consecutive True values."""
    best = 0
    current = 0
    for f in flags:
        if f:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _find_decay_onset(
    is_good: Sequence[bool],
    min_decay_run: int,
) -> Optional[int]:
    """Find the index where sustained decay begins.

    Looks for the first run of at least *min_decay_run* consecutive
    ``False`` values (bad cadence).
    """
    n = len(is_good)
    run_start: Optional[int] = None
    run_len = 0

    for i in range(n):
        if not is_good[i]:
            if run_start is None:
                run_start = i
            run_len += 1
            if run_len >= min_decay_run:
                return run_start
        else:
            run_start = None
            run_len = 0

    return None


def _compute_score(
    sustain_s: float,
    sustain_strokes: int,
    total_strokes: int,
    peak_run: int,
    efficiency: float,
    decay_profile: str,
) -> int:
    """Compute a 0–100 stamina score.

    Weights:
    - sustain duration (capped at 3 hours)     → 40%
    - peak run length                           → 20%
    - efficiency                                → 25%
    - decay profile penalty                     → 15%
    """
    # Sustain component: 3 hours = 10800s → full marks
    sustain_norm = min(sustain_s / 10800.0, 1.0)
    sustain_pts = sustain_norm * 40

    # Peak run component: 500 consecutive good strokes → full marks
    peak_norm = min(peak_run / 500.0, 1.0)
    peak_pts = peak_norm * 20

    # Efficiency component
    eff_pts = efficiency * 25

    # Decay profile penalty
    profile_penalties = {
        "none": 15,
        "oscillating": 10,
        "gradual": 6,
        "cliff": 2,
    }
    profile_pts = profile_penalties.get(decay_profile, 5)

    raw = sustain_pts + peak_pts + eff_pts + profile_pts
    return max(0, min(100, round(raw)))
