"""Decay counter: track freshness of repeated signals.

In a self-writing repository, many metrics decay over time if not refreshed:
commit momentum, writing cadence, push health.  A DecayCounter models this
naturally -- it increments on each event and decays exponentially toward zero
when no events arrive.

The half-life parameter controls how quickly a signal goes stale.  A short
half-life (e.g. 30 s) suits high-frequency signals like strokes; a long one
(e.g. 3600 s) suits infrequent signals like pushes.

All operations are O(1) and pure (no threads, no I/O).

Usage::

    from iamai.decay_counter import DecayCounter

    c = DecayCounter(half_life=60.0)
    c.bump(now=0.0)           # value: 1.0
    c.bump(now=10.0)          # value: ~1.89  (previous bump decayed slightly)
    c.read(now=120.0)         # value: ~0.47  (two half-lives of decay)
    c.is_fresh(now=120.0, threshold=0.5)  # True  (0.47 < 0.5 => stale => False)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class DecayCounter:
    """Exponentially decaying counter for freshness tracking.

    Parameters
    ----------
    half_life : float
        Seconds for the accumulated value to halve when no new events arrive.
    max_value : float
        Optional ceiling; bumps are clamped to this value.  0 means no ceiling.
    """

    half_life: float
    max_value: float = 0.0
    _value: float = 0.0
    _last_bump: float = -1.0
    _total_bumps: int = 0

    @property
    def decay_rate(self) -> float:
        """Continuous decay rate lambda such that value(t) = v0 * e^(-lambda*t)."""
        return math.log(2) / self.half_life

    def _decay_to(self, now: float) -> None:
        """Apply decay from last bump to *now* (internal, mutates state)."""
        if self._last_bump < 0 or now <= self._last_bump:
            return
        elapsed = now - self._last_bump
        self._value *= math.exp(-self.decay_rate * elapsed)

    def bump(self, now: float, weight: float = 1.0) -> float:
        """Record an event at time *now*.  Returns the new value.

        Parameters
        ----------
        now : float
            Current timestamp (any monotonic unit -- seconds, ms, etc.).
        weight : float
            Amount to add after decay.  Default 1.0.
        """
        self._decay_to(now)
        self._value += weight
        if self.max_value > 0:
            self._value = min(self._value, self.max_value)
        self._last_bump = now
        self._total_bumps += 1
        return self._value

    def read(self, now: float) -> float:
        """Read the current value after applying decay to *now* (no bump)."""
        if self._last_bump < 0:
            return 0.0
        elapsed = max(0.0, now - self._last_bump)
        return self._value * math.exp(-self.decay_rate * elapsed)

    def is_fresh(self, now: float, threshold: float = 0.5) -> bool:
        """True if the decayed value at *now* is at or above *threshold*."""
        return self.read(now) >= threshold

    def time_until_stale(self, now: float, threshold: float = 0.5) -> float:
        """Seconds from *now* until the value drops below *threshold*.

        Returns 0.0 if already stale.  Returns float('inf') if value is
        infinite or threshold is non-positive.
        """
        current = self.read(now)
        if current < threshold:
            return 0.0
        if threshold <= 0:
            return float("inf")
        # Solve: current * e^(-lambda * t) = threshold
        # => t = ln(current / threshold) / lambda
        return math.log(current / threshold) / self.decay_rate

    def summary(self, now: float) -> dict:
        """Snapshot of counter state."""
        return {
            "value": round(self.read(now), 6),
            "half_life": self.half_life,
            "max_value": self.max_value,
            "total_bumps": self._total_bumps,
            "is_fresh": self.is_fresh(now),
            "time_until_stale": round(self.time_until_stale(now), 2),
        }

    def reset(self) -> None:
        """Clear all state."""
        self._value = 0.0
        self._last_bump = -1.0
        self._total_bumps = 0


def freshness_score(events: list[float], half_life: float, now: float, threshold: float = 0.5) -> dict:
    """One-shot freshness analysis of a list of event timestamps.

    Parameters
    ----------
    events : list[float]
        Sorted timestamps (oldest first).
    half_life : float
        Decay half-life in seconds.
    now : float
        Current timestamp.
    threshold : float
        Freshness threshold.

    Returns
    -------
    dict with value, is_fresh, total_events, events_in_window.
    """
    counter = DecayCounter(half_life=half_life)
    for t in events:
        counter.bump(now=t)

    value = counter.read(now)
    # Count events within ~3 half-lives (captures ~87.5% of signal)
    window = half_life * 3
    cutoff = now - window
    events_in_window = sum(1 for t in events if t >= cutoff)

    return {
        "value": round(value, 6),
        "is_fresh": value >= threshold,
        "total_events": len(events),
        "events_in_window": events_in_window,
        "half_life": half_life,
    }
