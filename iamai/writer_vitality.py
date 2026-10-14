"""writer_vitality — rolling health score for an AI writer process.

Existing modules answer binary questions:

- ``stall_classifier``: is the writer dead *right now*?
- ``cadence_adherence``: is the rhythm steady over a window?
- ``stroke_freshness``: how stale is the latest stroke?

None of them produce a single, glanceable **vitality score** that
trends over time.  This module fills that gap.

Design goals:

1. **Single number** — vitality ∈ [0.0, 1.0]; 1.0 = perfectly healthy.
2. **Multi-signal** — combines freshness, cadence adherence, and
   recent stall count into one reading.
3. **Trend-aware** — keeps a ring buffer of recent scores so the
   caretaker can ask "is vitality improving or declining?"
4. **Pure Python** — no subprocess, no filesystem side-effects;
   all inputs are passed as arguments.

Usage::

    from iamai.writer_vitality import WriterVitality

    vit = WriterVitality()
    vit.record(freshness_s=12, cadence_pct=0.95, stalls=0)
    vit.record(freshness_s=45, cadence_pct=0.80, stalls=1)
    vit.score()                # latest composite score
    vit.trend()                # "improving" | "declining" | "flat"
    vit.summary()              # human-readable one-liner

Scoring weights (sum to 1.0):

- **freshness** (0.40) — penalised linearly; 0 s → 1.0, ≥300 s → 0.0.
- **cadence**   (0.35) — ``cadence_pct`` passed through directly.
- **stall penalty** (0.25) — ``max(0, 1 - stalls * 0.25)``;
  four or more stalls in the window zeroes this component.

The final score is the weighted sum, clamped to [0, 1].
"""

from __future__ import annotations

from collections import deque
from typing import Optional


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

_STALENESS_CEILING_S = 300.0   # 5 min → freshness component = 0
_STALL_PENALTY_STEP  = 0.25    # each stall removes 25 % of stall component
_MAX_HISTORY         = 60      # ring-buffer capacity


def _freshness_score(freshness_s: float) -> float:
    """Convert seconds-since-last-stroke into a 0-1 score."""
    if freshness_s < 0:
        freshness_s = 0
    return max(0.0, 1.0 - freshness_s / _STALENESS_CEILING_S)


def _stall_score(stalls: int) -> float:
    """Convert stall count into a 0-1 score."""
    if stalls < 0:
        stalls = 0
    return max(0.0, 1.0 - stalls * _STALL_PENALTY_STEP)


def _composite(freshness_s: float, cadence_pct: float, stalls: int) -> float:
    """Weighted composite, clamped to [0, 1]."""
    f = _freshness_score(freshness_s)
    c = max(0.0, min(1.0, cadence_pct))
    s = _stall_score(stalls)
    raw = 0.40 * f + 0.35 * c + 0.25 * s
    return round(max(0.0, min(1.0, raw)), 4)


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

def _trend_label(scores: list[float]) -> str:
    """Classify the direction of recent scores.

    Uses the slope of a simple linear regression over the last
    ``min(len(scores), 10)`` data points.  Threshold: ±0.005 per
    reading — anything flatter is "flat".
    """
    n = min(len(scores), 10)
    if n < 3:
        return "insufficient_data"
    window = scores[-n:]
    # Simple OLS slope: Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
    x_mean = (n - 1) / 2.0
    y_mean = sum(window) / n
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(window))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return "flat"
    slope = num / den
    if slope > 0.005:
        return "improving"
    if slope < -0.005:
        return "declining"
    return "flat"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class WriterVitality:
    """Rolling vitality monitor for a single writer process."""

    def __init__(self, history: int = _MAX_HISTORY) -> None:
        self._history = max(5, min(history, _MAX_HISTORY))
        self._scores: deque[float] = deque(maxlen=self._history)
        self._last: Optional[dict] = None

    # -- recording --------------------------------------------------------

    def record(
        self,
        freshness_s: float,
        cadence_pct: float,
        stalls: int,
    ) -> float:
        """Record a vitality reading and return the composite score."""
        score = _composite(freshness_s, cadence_pct, stalls)
        self._scores.append(score)
        self._last = {
            "freshness_s": freshness_s,
            "cadence_pct": cadence_pct,
            "stalls": stalls,
            "score": score,
        }
        return score

    # -- queries ----------------------------------------------------------

    def score(self) -> Optional[float]:
        """Latest composite score, or ``None`` if no readings yet."""
        return self._scores[-1] if self._scores else None

    def trend(self) -> str:
        """Direction label over recent readings."""
        return _trend_label(list(self._scores))

    def history(self) -> list[float]:
        """All buffered scores, oldest first."""
        return list(self._scores)

    def readings(self) -> int:
        """Number of recorded readings."""
        return len(self._scores)

    def summary(self) -> str:
        """One-line human-readable status."""
        if not self._scores:
            return "no readings yet"
        s = self._scores[-1]
        t = self.trend()
        n = len(self._scores)
        lo = min(self._scores)
        hi = max(self._scores)
        avg = sum(self._scores) / n
        return (
            f"vitality {s:.2f} ({t}) | "
            f"{n} readings, avg {avg:.2f}, "
            f"range [{lo:.2f}, {hi:.2f}]"
        )

    # -- dunder -----------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"WriterVitality(readings={self.readings()}, "
            f"score={self.score()}, trend={self.trend()!r})"
        )
