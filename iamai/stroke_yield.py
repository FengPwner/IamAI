"""stroke_yield — measure actual vs expected stroke production rate.

Where cadence_adherence asks "is the rhythm steady?" and writer_vitality
asks "how healthy is the process overall?", stroke_yield asks the
simplest question: **are we producing the expected volume?**

Yield = actual_strokes / expected_strokes, measured over a sliding
window.  A yield of 1.0 means the writer hit every expected beat;
0.5 means half were missed; >1.0 means the writer is outpacing its
configured cadence (rare but possible after a burst catch-up).

Design:

1. **Windowed** — caller specifies window size in seconds (default
   3600 = one hour).  Older observations fall off the ring.
2. **Lightweight** — no filesystem I/O; all data passed as arguments.
3. **Actionable** — exposes a ``classify()`` method that maps yield
   to human-readable bands: ``thriving | healthy | degraded | starved``.
4. **Cumulative** — keeps a running total so the caretaker can ask
   about lifetime yield, not just recent.

Usage::

    from iamai.stroke_yield import StrokeYield

    sy = StrokeYield(cadence_s=15, window_s=3600)
    sy.observe(count=4, elapsed_s=60)   # 4 strokes in 60 seconds
    sy.observe(count=3, elapsed_s=60)   # 3 strokes in next 60 seconds
    sy.yield_ratio()                     # ~0.875 (7 actual / 8 expected)
    sy.classify()                        # "healthy"
    sy.summary()                         # "healthy: 87.5% yield (7/8)"

Bands:

- **thriving** — yield ≥ 1.0 (at or above expected rate)
- **healthy**  — yield ≥ 0.75 (occasional gaps, nothing to worry about)
- **degraded** — yield ≥ 0.40 (significant underproduction)
- **starved**  — yield < 0.40 (writer is mostly silent)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Band thresholds
# ---------------------------------------------------------------------------

_THRIVING_THRESHOLD = 1.0
_HEALTHY_THRESHOLD  = 0.75
_DEGRADED_THRESHOLD = 0.40

# Maximum number of observation slots in the ring buffer.
_MAX_SLOTS = 10_000


@dataclass
class YieldSnapshot:
    """Immutable snapshot of yield state at a point in time."""

    actual: int
    expected: float
    ratio: float
    band: str

    def to_dict(self) -> dict:
        return asdict(self)


class StrokeYield:
    """Sliding-window stroke yield tracker.

    Parameters
    ----------
    cadence_s : float
        Expected seconds between strokes (default 15).
    window_s : float
        Sliding window width in seconds (default 3600 = one hour).
    """

    def __init__(self, cadence_s: float = 15.0, window_s: float = 3600.0):
        if cadence_s <= 0:
            raise ValueError(f"cadence_s must be positive, got {cadence_s}")
        if window_s <= 0:
            raise ValueError(f"window_s must be positive, got {window_s}")

        self._cadence_s = float(cadence_s)
        self._window_s = float(window_s)

        # Each slot: (elapsed_s, actual_count)
        self._slots: deque[tuple[float, int]] = deque(maxlen=_MAX_SLOTS)
        self._total_elapsed: float = 0.0
        self._total_actual: int = 0

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def observe(self, count: int, elapsed_s: float) -> None:
        """Record an observation: ``count`` strokes in ``elapsed_s`` seconds.

        Negative counts are clamped to zero.  Zero elapsed is ignored
        (avoids division-by-zero in yield calculation).
        """
        if elapsed_s <= 0:
            return
        count = max(0, count)
        self._slots.append((elapsed_s, count))
        self._total_elapsed += elapsed_s
        self._total_actual += count
        self._evict()

    def yield_ratio(self) -> float:
        """Return the yield ratio over the current window.

        Returns 1.0 when no observations exist (vacuously healthy).
        """
        actual, expected = self._window_totals()
        if expected <= 0:
            return 1.0
        return min(actual / expected, 2.0)  # cap at 2.0 to avoid wild spikes

    def classify(self) -> str:
        """Map the current yield ratio to a health band."""
        r = self.yield_ratio()
        if r >= _THRIVING_THRESHOLD:
            return "thriving"
        if r >= _HEALTHY_THRESHOLD:
            return "healthy"
        if r >= _DEGRADED_THRESHOLD:
            return "degraded"
        return "starved"

    def snapshot(self) -> YieldSnapshot:
        """Return an immutable snapshot of the current state."""
        actual, expected = self._window_totals()
        ratio = self.yield_ratio()
        return YieldSnapshot(
            actual=actual,
            expected=expected,
            ratio=round(ratio, 4),
            band=self.classify(),
        )

    def summary(self) -> str:
        """Human-readable one-liner."""
        snap = self.snapshot()
        pct = f"{snap.ratio * 100:.1f}%"
        return f"{snap.band}: {pct} yield ({snap.actual}/{snap.expected:.0f} expected)"

    # ------------------------------------------------------------------
    # Cumulative stats
    # ------------------------------------------------------------------

    @property
    def total_actual(self) -> int:
        """Lifetime total strokes observed."""
        return self._total_actual

    @property
    def total_elapsed(self) -> float:
        """Lifetime total elapsed seconds observed."""
        return self._total_elapsed

    def lifetime_ratio(self) -> float:
        """Yield ratio over all observations (not just the window)."""
        expected = self._total_elapsed / self._cadence_s
        if expected <= 0:
            return 1.0
        return min(self._total_actual / expected, 2.0)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all observations."""
        self._slots.clear()
        self._total_elapsed = 0.0
        self._total_actual = 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict(self) -> None:
        """Remove slots that have fallen outside the sliding window."""
        # Walk from the left (oldest) and stop when cumulative elapsed
        # from the right would still fit in the window.
        total = sum(e for e, _ in self._slots)
        while total > self._window_s and len(self._slots) > 1:
            e, _ = self._slots.popleft()
            total -= e

    def _window_totals(self) -> tuple[int, float]:
        """Return (actual_count, expected_count) for the current window."""
        if not self._slots:
            return 0, 0.0
        total_elapsed = sum(e for e, _ in self._slots)
        total_actual = sum(c for _, c in self._slots)
        expected = total_elapsed / self._cadence_s
        return total_actual, expected
