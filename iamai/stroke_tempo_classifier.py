"""stroke_tempo_classifier — classify the writer's current operating tempo.

Rhythm (stroke_rhythm) tells you *how* the writer breathes.
Pacing (stroke_pacer) tells you *whether* it will hit a daily target.
But neither answers the simpler question a caretaker asks on arrival:

    "What mode is this writer in right now?"

This module classifies the current tempo into one of five regimes:

    ┌────────────┬────────────────────┬───────────────────────────────┐
    │ Regime     │ Median interval    │ Typical meaning               │
    ├────────────┼────────────────────┼───────────────────────────────┤
    │ sprint     │ < 5 s              │ burst output, template-driven  │
    │ steady     │ 5–30 s             │ healthy working pace           │
    │ drip       │ 30 s – 5 min       │ low-activity trickle           │
    │ dormant    │ 5–30 min           │ writer alive but barely firing │
    │ stalled    │ > 30 min           │ effective stall                │
    └────────────┴────────────────────┴───────────────────────────────┘

The classifier uses the *median* inter-stroke interval over a recent
window rather than the mean, so a single long gap (e.g. a restart pause)
does not skew the verdict.

Confidence is reported as 0.0–1.0 based on sample size:
  - ≥ 20 intervals → 1.0 (high confidence)
  - 10–19          → 0.7
  - 5–9            → 0.4
  - < 5            → 0.1 (too few to trust)

Transitions
-----------
Calling ``classify()`` repeatedly is cheap.  The helper ``transition()``
compares two consecutive classifications and returns a human-readable
label:

    "steady→drip"   — writer slowing down
    "dormant→sprint" — writer woke up hard
    "steady→steady"  — no change

Usage
-----
    from iamai.stroke_tempo_classifier import StrokeTempoClassifier

    tc = StrokeTempoClassifier()
    for ts in recent_timestamps:
        tc.record(ts)

    print(tc.classify())       # "steady"
    print(tc.confidence())     # 0.7
    print(tc.summary())        # "tempo=steady (conf=0.70, median=12.3s, n=15)"
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional


# Regime boundaries (seconds).
SPRINT_CEILING = 5.0
STEADY_CEILING = 30.0
DRIP_CEILING = 300.0        # 5 min
DORMANT_CEILING = 1800.0    # 30 min
# Anything above DORMANT_CEILING is "stalled".

# Regime labels (kept as constants so callers can import them).
REGIME_SPRINT = "sprint"
REGIME_STEADY = "steady"
REGIME_DRIP = "drip"
REGIME_DORMANT = "dormant"
REGIME_STALLED = "stalled"
REGIME_UNKNOWN = "unknown"


@dataclass
class TempoSnapshot:
    """Point-in-time tempo reading."""
    regime: str
    median_interval: float
    confidence: float
    sample_count: int


class StrokeTempoClassifier:
    """Classify the writer's operating tempo from recent stroke timestamps."""

    def __init__(self, window_size: int = 60):
        """
        Args:
            window_size: maximum number of timestamps to retain (FIFO).
        """
        self.window_size = window_size
        self._timestamps: Deque[float] = deque(maxlen=window_size)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, timestamp: Optional[float] = None) -> None:
        """Record a stroke timestamp.  Defaults to ``time.time()``."""
        if timestamp is None:
            timestamp = time.time()
        self._timestamps.append(float(timestamp))

    def record_batch(self, timestamps: List[float]) -> None:
        """Record multiple timestamps in order."""
        for ts in timestamps:
            self.record(ts)

    def clear(self) -> None:
        """Drop all recorded timestamps."""
        self._timestamps.clear()

    # ------------------------------------------------------------------
    # Interval math
    # ------------------------------------------------------------------

    def intervals(self) -> List[float]:
        """Sorted list of positive inter-stroke intervals."""
        ts = sorted(self._timestamps)
        if len(ts) < 2:
            return []
        return [ts[i + 1] - ts[i] for i in range(len(ts) - 1) if ts[i + 1] > ts[i]]

    def median_interval(self) -> float:
        """Median inter-stroke interval (seconds).  Returns 0.0 if < 2 samples."""
        ivs = self.intervals()
        n = len(ivs)
        if n == 0:
            return 0.0
        ivs_sorted = sorted(ivs)
        mid = n // 2
        if n % 2 == 1:
            return ivs_sorted[mid]
        return (ivs_sorted[mid - 1] + ivs_sorted[mid]) / 2.0

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self) -> str:
        """Return the current tempo regime.

        Returns one of: sprint, steady, drip, dormant, stalled, unknown.
        """
        ivs = self.intervals()
        if len(ivs) < 2:
            return REGIME_UNKNOWN

        med = self.median_interval()
        return self._regime_from_median(med)

    @staticmethod
    def _regime_from_median(median_iv: float) -> str:
        """Map a median interval to a regime label."""
        if median_iv < SPRINT_CEILING:
            return REGIME_SPRINT
        if median_iv < STEADY_CEILING:
            return REGIME_STEADY
        if median_iv < DRIP_CEILING:
            return REGIME_DRIP
        if median_iv < DORMANT_CEILING:
            return REGIME_DORMANT
        return REGIME_STALLED

    def confidence(self) -> float:
        """Confidence in the current classification (0.0–1.0)."""
        n = len(self.intervals())
        if n >= 20:
            return 1.0
        if n >= 10:
            return 0.7
        if n >= 5:
            return 0.4
        return 0.1

    # ------------------------------------------------------------------
    # Transition detection
    # ------------------------------------------------------------------

    def transition(self, previous_regime: str) -> str:
        """Compare a previous regime to the current one.

        Returns a string like "steady→drip" or "sprint→sprint".
        """
        current = self.classify()
        return f"{previous_regime}\u2192{current}"

    @staticmethod
    def is_slowdown(transition_label: str) -> bool:
        """True if the transition represents a slowdown.

        E.g. "steady→drip", "sprint→dormant".
        """
        order = [REGIME_SPRINT, REGIME_STEADY, REGIME_DRIP, REGIME_DORMANT, REGIME_STALLED]
        if "\u2192" not in transition_label:
            return False
        prev, curr = transition_label.split("\u2192")
        if prev not in order or curr not in order:
            return False
        return order.index(curr) > order.index(prev)

    @staticmethod
    def is_speedup(transition_label: str) -> bool:
        """True if the transition represents a speedup."""
        order = [REGIME_SPRINT, REGIME_STEADY, REGIME_DRIP, REGIME_DORMANT, REGIME_STALLED]
        if "\u2192" not in transition_label:
            return False
        prev, curr = transition_label.split("\u2192")
        if prev not in order or curr not in order:
            return False
        return order.index(curr) < order.index(prev)

    # ------------------------------------------------------------------
    # Snapshot & summary
    # ------------------------------------------------------------------

    def snapshot(self) -> TempoSnapshot:
        """Return a point-in-time tempo snapshot."""
        return TempoSnapshot(
            regime=self.classify(),
            median_interval=self.median_interval(),
            confidence=self.confidence(),
            sample_count=len(self.intervals()),
        )

    def summary(self) -> str:
        """One-line human-readable summary."""
        snap = self.snapshot()
        return (
            f"tempo={snap.regime} "
            f"(conf={snap.confidence:.2f}, median={snap.median_interval:.1f}s, "
            f"n={snap.sample_count})"
        )
