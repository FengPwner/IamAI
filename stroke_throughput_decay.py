"""stroke_throughput_decay — detect when the writer's output rate is fading.

The writer loop ticks at a fixed cadence (one stroke every N seconds), but
the *substance* of each stroke can thin out over time: the same sentence
templates recycled, the same metrics re-reported with incremented numbers.
When the variety drops below a threshold, the repo is still "writing" but no
longer producing — a zombie cadence.

This module measures throughput decay by comparing the set of unique tokens
across a sliding window of recent strokes against a baseline window.  When
the ratio drops below `decay_floor`, a caretaker should investigate.

Public API
----------
ThroughputDecayTracker
    Main class.  Feed it stroke texts in chronological order; ask it for the
    current decay score and whether the writer has entered zombie cadence.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass
class _Window:
    tokens: Counter = field(default_factory=Counter)
    size: int = 0

    def add(self, text: str) -> None:
        for tok in _tokenize(text):
            self.tokens[tok] += 1
            self.size += 1

    def unique_ratio(self) -> float:
        if self.size == 0:
            return 0.0
        return len(self.tokens) / self.size

    def overlap_with(self, other: "_Window") -> float:
        """Jaccard-style overlap of token *sets* (ignoring counts)."""
        if not self.tokens or not other.tokens:
            return 0.0
        a, b = set(self.tokens), set(other.tokens)
        inter = a & b
        union = a | b
        return len(inter) / len(union) if union else 0.0


def _tokenize(text: str) -> List[str]:
    """Lowercase split on whitespace and punctuation-ish chars."""
    return [t.lower() for t in text.split() if t.strip()]


class ThroughputDecayTracker:
    """Track whether the writer's vocabulary variety is decaying.

    Parameters
    ----------
    baseline_window : int
        Number of strokes to keep in the reference (older) window.
    current_window : int
        Number of strokes to keep in the active (newer) window.
    decay_floor : float
        If the overlap between baseline and current exceeds this value
        (0–1), the writer is considered to be in *zombie cadence*: still
        producing output but with recycled content.
    """

    def __init__(
        self,
        baseline_window: int = 20,
        current_window: int = 20,
        decay_floor: float = 0.85,
    ) -> None:
        self._baseline_cap = max(1, baseline_window)
        self._current_cap = max(1, current_window)
        self._decay_floor = decay_floor
        self._buffer: List[str] = []
        self._history: List[float] = []  # decay scores over time

    # -- feeding ---------------------------------------------------------------

    def feed(self, stroke_text: str) -> None:
        self._buffer.append(stroke_text)
        # keep only what we need for both windows
        keep = self._baseline_cap + self._current_cap
        if len(self._buffer) > keep:
            self._buffer = self._buffer[-keep:]

    def feed_many(self, texts: Sequence[str]) -> None:
        for t in texts:
            self.feed(t)

    # -- scoring ---------------------------------------------------------------

    @property
    def ready(self) -> bool:
        return len(self._buffer) >= self._baseline_cap + self._current_cap

    def decay_score(self) -> Optional[float]:
        """Return the current decay score (0 = fresh, 1 = fully recycled).

        Returns ``None`` when there are not enough strokes to compute.
        """
        if not self.ready:
            return None
        baseline = self._build_window(-self._baseline_cap - self._current_cap,
                                      -self._current_cap)
        current = self._build_window(-self._current_cap, None)
        score = baseline.overlap_with(current)
        self._history.append(score)
        return score

    def is_zombie_cadence(self) -> bool:
        score = self.decay_score()
        if score is None:
            return False
        return score >= self._decay_floor

    # -- trend -----------------------------------------------------------------

    def trend(self, lookback: int = 5) -> Optional[str]:
        """Return 'rising', 'falling', or 'flat' for the recent trend.

        'rising' means the overlap is increasing (more decay over time).
        """
        if len(self._history) < max(2, lookback):
            return None
        recent = self._history[-lookback:]
        diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        avg = sum(diffs) / len(diffs)
        if avg > 0.01:
            return "rising"
        if avg < -0.01:
            return "falling"
        return "flat"

    def consecutive_zombie(self) -> int:
        """How many consecutive readings have been in zombie cadence."""
        count = 0
        for s in reversed(self._history):
            if s >= self._decay_floor:
                count += 1
            else:
                break
        return count

    # -- summary ---------------------------------------------------------------

    def summary(self) -> dict:
        score = self.decay_score()
        return {
            "ready": self.ready,
            "strokes_buffered": len(self._buffer),
            "baseline_window": self._baseline_cap,
            "current_window": self._current_cap,
            "decay_floor": self._decay_floor,
            "decay_score": round(score, 4) if score is not None else None,
            "zombie_cadence": self.is_zombie_cadence(),
            "consecutive_zombie": self.consecutive_zombie(),
            "trend": self.trend(),
        }

    # -- internals -------------------------------------------------------------

    def _build_window(self, start: int, end: Optional[int]) -> _Window:
        w = _Window()
        for text in self._buffer[start:end]:
            w.add(text)
        return w
