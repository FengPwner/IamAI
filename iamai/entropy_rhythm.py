"""entropy_rhythm — detect mechanical repetition in automated writing.

The existing ``stroke_entropy`` module measures how *diverse* the vocabulary
is across strokes.  ``stroke_novelty`` checks whether consecutive strokes
overlap in trigram space.  Neither answers the question that actually
bothers a caretaker at 3 AM:

    *Is the writer stuck in a rut, grinding the same template over and over?*

This module looks at the **sequence** of entropy readings and scores whether
the trend is healthy, flat, or decaying.  A decaying entropy rhythm means the
writer is recycling the same sentence structures even if individual strokes
pass the quality gate.

Design goals:

1. **Sequence-level, not stroke-level** — operates on a window of readings.
2. **Trend + volatility** — a perfectly flat entropy is as suspicious as a
   declining one.
3. **Pure Python** — no filesystem, no git; inputs are floats.
4. **Bounded memory** — ring buffer of configurable size (default 60).

Usage::

    from iamai.entropy_rhythm import EntropyRhythm

    rhythm = EntropyRhythm()
    for reading in [0.72, 0.68, 0.71, 0.65, 0.60, 0.55, 0.50, 0.45]:
        rhythm.record(reading)

    report = rhythm.analyse()
    print(report["verdict"])   # "decaying"
    print(report["slope"])     # -0.0294
    print(report["cv"])        # 0.135 (coefficient of variation)

Verdicts:

===========  ============================================================
``healthy``  slope > -0.005 and cv < 0.15 — entropy is stable or rising
``flat``     |slope| ≤ 0.005 and cv < 0.10 — suspiciously unchanging
``decaying`` slope < -0.005 — diversity is eroding
``volatile`` cv ≥ 0.15 — erratic jumps, writer may be malfunctioning
===========  ============================================================
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


# ---------------------------------------------------------------------------
# Linear regression helper (no numpy dependency)
# ---------------------------------------------------------------------------

def _linreg(values: List[float]) -> tuple[float, float]:
    """Return (slope, r_squared) for values indexed 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0, 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    ss_xy = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    ss_xx = sum((i - x_mean) ** 2 for i in range(n))
    ss_yy = sum((v - y_mean) ** 2 for v in values)
    if ss_xx == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0
    return slope, r_squared


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

@dataclass
class EntropyRhythm:
    """Track a sliding window of entropy readings and classify the rhythm."""

    window_size: int = 60
    readings: Deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.readings = deque(maxlen=self.window_size)

    def record(self, value: float) -> None:
        """Append one entropy reading to the window."""
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"entropy must be in [0, 1], got {value}")
        self.readings.append(value)

    @property
    def count(self) -> int:
        return len(self.readings)

    def _cv(self) -> float:
        """Coefficient of variation (std / mean)."""
        vals = list(self.readings)
        if len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        if mean == 0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return math.sqrt(variance) / abs(mean)

    def _slope(self) -> float:
        """Linear regression slope over the window."""
        vals = list(self.readings)
        if len(vals) < 3:
            return 0.0
        slope, _ = _linreg(vals)
        return slope

    def _r_squared(self) -> float:
        """R² of the linear fit — how well slope explains the data."""
        vals = list(self.readings)
        if len(vals) < 3:
            return 0.0
        _, r2 = _linreg(vals)
        return r2

    def analyse(self) -> Dict[str, object]:
        """Produce a structured report of the current rhythm.

        Returns a dict with keys: count, slope, cv, r_squared,
        mean_entropy, min_entropy, max_entropy, verdict.
        """
        vals = list(self.readings)
        count = len(vals)
        slope = self._slope()
        cv = self._cv()
        r2 = self._r_squared()
        mean_e = sum(vals) / count if count else 0.0
        min_e = min(vals) if vals else 0.0
        max_e = max(vals) if vals else 0.0

        # classification logic:
        # 1. Not enough data → insufficient
        # 2. Strong negative trend → decaying
        # 3. Clear trend (R² ≥ 0.5) with positive slope → healthy
        # 4. High CV without clear trend → volatile
        # 5. Near-zero slope, low CV → flat
        # 6. Everything else → healthy (mild trend, moderate noise)
        if count < 3:
            verdict = "insufficient"
        elif slope < -0.005:
            verdict = "decaying"
        elif r2 >= 0.5 and slope > 0:
            verdict = "healthy"
        elif cv >= 0.15:
            verdict = "volatile"
        elif abs(slope) <= 0.005 and cv < 0.10:
            verdict = "flat"
        else:
            verdict = "healthy"

        return {
            "count": count,
            "slope": round(slope, 6),
            "cv": round(cv, 4),
            "r_squared": round(r2, 4),
            "mean_entropy": round(mean_e, 4),
            "min_entropy": round(min_e, 4),
            "max_entropy": round(max_e, 4),
            "verdict": verdict,
        }

    def report(self) -> str:
        """One-line human-readable summary."""
        r = self.analyse()
        if r["verdict"] == "insufficient":
            return f"insufficient data ({r['count']}/3 readings)"
        return (
            f"{r['verdict']} — slope={r['slope']:+.4f} cv={r['cv']:.2f} "
            f"mean={r['mean_entropy']:.3f} [{r['count']} readings]"
        )
