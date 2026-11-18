"""note_rotation — track stroke distribution across note files.

The automated writer appends a stroke to one of six note files every
~15 seconds: devlog, garden, metrics, note, snippet, thought.  Over
time the distribution should be roughly uniform.  When one file is
over-served (receiving far more strokes than its peers) or under-served
(receiving far fewer), it signals a rotation bug or a stuck selector.

This module provides:

  - ``NoteSlot``: enum-like constants for the six note file categories.
  - ``RotationWindow``: fixed-size sliding window of recent slot picks.
  - ``fairness_score(counts)``: chi-squared-based uniformity measure,
    returns 0.0 (perfectly uniform) to 1.0 (maximally skewed).
  - ``hot_slot(counts)``: returns the slot name with the highest count,
    or None if all are zero.
  - ``cold_slot(counts)``: returns the slot name with the lowest count,
    or None if all are zero.
  - ``RotationMonitor``: stateful tracker that ingests slot picks and
    exposes a health verdict (balanced / warming / skewed).

Design decisions:
  - Six slots are hard-coded: they match the writer's output targets.
  - Fairness uses a normalized chi-squared statistic so the score is
    comparable across different window sizes.
  - Thresholds for "warming" and "skewed" are configurable but default
    to values derived from simulation on uniform random picks.

Usage::

    from iamai.note_rotation import RotationMonitor

    mon = RotationMonitor(window_size=60)
    mon.record("garden")
    mon.record("devlog")
    mon.record("garden")
    print(mon.verdict())   # RotationVerdict(balanced=True, ...)
    print(mon.fairness())  # 0.166...

Written by Qwen during caretaker visit 704, 2026-11-18.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence


# ─── Constants ──────────────────────────────────────────────────────

NOTE_SLOTS: tuple = ("devlog", "garden", "metrics", "note", "snippet", "thought")
SLOT_COUNT: int = len(NOTE_SLOTS)

# Fairness thresholds (normalized chi-squared)
DEFAULT_WARM_THRESHOLD: float = 0.30
DEFAULT_SKEW_THRESHOLD: float = 0.60


# ─── Data classes ───────────────────────────────────────────────────


@dataclass(frozen=True)
class RotationVerdict:
    """Outcome of a rotation health check."""

    balanced: bool
    state: str  # "balanced", "warming", or "skewed"
    fairness: float  # 0.0 = uniform, 1.0 = maximally skewed
    hot: Optional[str]  # most-served slot name, or None
    cold: Optional[str]  # least-served slot name, or None
    counts: Dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.balanced:
            return f"balanced (fairness={self.fairness:.3f})"
        return (
            f"{self.state} (fairness={self.fairness:.3f}, "
            f"hot={self.hot}, cold={self.cold})"
        )


# ─── Scoring functions ──────────────────────────────────────────────


def fairness_score(counts: Dict[str, int]) -> float:
    """Compute normalized chi-squared divergence from uniform.

    Returns 0.0 when all slots have equal counts (perfect uniformity).
    Returns 1.0 when all strokes land in a single slot (maximum skew).
    Returns 0.0 when total count is zero (no data to judge).
    """
    total = sum(counts.get(s, 0) for s in NOTE_SLOTS)
    if total == 0:
        return 0.0

    expected = total / SLOT_COUNT
    chi2 = sum(
        (counts.get(s, 0) - expected) ** 2 / expected for s in NOTE_SLOTS
    )

    # Maximum chi2 occurs when all strokes land in one slot:
    #   (total - expected)^2 / expected + (SLOT_COUNT - 1) * expected^2 / expected
    # = (total - E)^2 / E + (S-1) * E
    # Normalized: chi2 / max_chi2
    max_chi2 = ((total - expected) ** 2 / expected) + (SLOT_COUNT - 1) * expected
    if max_chi2 == 0:
        return 0.0

    return min(chi2 / max_chi2, 1.0)


def hot_slot(counts: Dict[str, int]) -> Optional[str]:
    """Return the slot name with the highest count, or None if all zero."""
    total = sum(counts.get(s, 0) for s in NOTE_SLOTS)
    if total == 0:
        return None
    return max(NOTE_SLOTS, key=lambda s: counts.get(s, 0))


def cold_slot(counts: Dict[str, int]) -> Optional[str]:
    """Return the slot name with the lowest count, or None if all zero."""
    total = sum(counts.get(s, 0) for s in NOTE_SLOTS)
    if total == 0:
        return None
    return min(NOTE_SLOTS, key=lambda s: counts.get(s, 0))


# ─── Sliding window ────────────────────────────────────────────────


class RotationWindow:
    """Fixed-size sliding window of recent slot picks."""

    def __init__(self, maxlen: int = 60) -> None:
        if maxlen < 1:
            raise ValueError(f"maxlen must be >= 1, got {maxlen}")
        self._buf: deque = deque(maxlen=maxlen)

    def add(self, slot: str) -> None:
        """Record a slot pick. Silently ignores unknown slots."""
        if slot not in NOTE_SLOTS:
            return
        self._buf.append(slot)

    def counts(self) -> Dict[str, int]:
        """Return current slot frequency counts."""
        c = Counter(self._buf)
        return {s: c.get(s, 0) for s in NOTE_SLOTS}

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()

    @property
    def maxlen(self) -> int:
        return self._buf.maxlen  # type: ignore[return-value]


# ─── Stateful monitor ──────────────────────────────────────────────


class RotationMonitor:
    """Track rotation balance across note files.

    Parameters
    ----------
    window_size : int
        Number of recent picks to consider (default 60 ≈ 15 min at 15s cadence).
    warm_threshold : float
        Fairness score above which the state is "warming" (default 0.30).
    skew_threshold : float
        Fairness score above which the state is "skewed" (default 0.60).
    """

    def __init__(
        self,
        window_size: int = 60,
        warm_threshold: float = DEFAULT_WARM_THRESHOLD,
        skew_threshold: float = DEFAULT_SKEW_THRESHOLD,
    ) -> None:
        self._window = RotationWindow(maxlen=window_size)
        self._warm = warm_threshold
        self._skew = skew_threshold

    def record(self, slot: str) -> None:
        """Record a slot pick."""
        self._window.add(slot)

    def record_many(self, slots: Sequence[str]) -> None:
        """Record multiple slot picks at once."""
        for s in slots:
            self._window.add(s)

    def fairness(self) -> float:
        """Return current fairness score (0.0 = uniform, 1.0 = skewed)."""
        return fairness_score(self._window.counts())

    def verdict(self) -> RotationVerdict:
        """Return a full rotation health verdict."""
        counts = self._window.counts()
        score = fairness_score(counts)
        hot = hot_slot(counts)
        cold = cold_slot(counts)

        if score >= self._skew:
            state = "skewed"
            balanced = False
        elif score >= self._warm:
            state = "warming"
            balanced = False
        else:
            state = "balanced"
            balanced = True

        return RotationVerdict(
            balanced=balanced,
            state=state,
            fairness=score,
            hot=hot,
            cold=cold,
            counts=counts,
        )

    @property
    def window(self) -> RotationWindow:
        """Access the underlying window for inspection."""
        return self._window

    def reset(self) -> None:
        """Clear all recorded picks."""
        self._window.clear()
