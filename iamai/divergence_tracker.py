"""divergence_tracker — record and analyse branch-divergence events.

Every time a push is rejected as non-fast-forward the repo has diverged
from its remote.  This module gives the caretaker a lightweight ledger
of those events so it can answer:

    "How many times did we diverge today?"
    "What was the longest streak of clean pushes?"
    "Is divergence getting worse this week?"

Usage::

    tracker = DivergenceTracker()
    tracker.record(resolution="merge")        # resolved by merge
    tracker.record(resolution="rebase")       # resolved by rebase
    tracker.record(resolution="force_push")   # last resort
    tracker.total()                           # 3
    tracker.streak()                          # 0 (last event was divergence)
    tracker.mark_clean_push()                 # clean push in between
    tracker.streak()                          # 1
    tracker.summary()                         # dict with counts + streak

Design notes:
  - Pure Python, no subprocess calls.
  - The caller decides when to call ``record`` / ``mark_clean_push``;
    this module only keeps the ledger.
  - ``resolution`` is free-form text so future caretakers can add
    categories (e.g. "ort-merge", "manual-rebase") without a schema change.
  - Thread-safe enough for the single-process caretaker; not designed
    for multi-process concurrent writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class DivergenceTracker:
    """Track branch-divergence events and clean-push streaks."""

    def __init__(self, max_history: int = 1000) -> None:
        if max_history < 1:
            raise ValueError("max_history must be >= 1")
        self._max_history = max_history
        self._events: list[dict[str, Any]] = []
        self._clean_pushes: int = 0
        self._current_streak: int = 0
        self._longest_streak: int = 0

    # -- recording --------------------------------------------------------

    def record(self, resolution: str, *, now: datetime | None = None) -> None:
        """Record a divergence event.

        ``resolution`` describes how the divergence was resolved
        (e.g. "merge", "rebase", "force_push", "manual").
        """
        if not resolution or not resolution.strip():
            raise ValueError("resolution must be a non-empty string")
        ts = now or datetime.now(timezone.utc)
        self._events.append({
            "timestamp": ts.isoformat(),
            "resolution": resolution.strip(),
        })
        # Trim to capacity (FIFO).
        if len(self._events) > self._max_history:
            self._events = self._events[-self._max_history:]
        # A divergence breaks the clean-push streak.
        self._current_streak = 0

    def mark_clean_push(self) -> None:
        """Record a successful, non-divergent push."""
        self._current_streak += 1
        self._clean_pushes += 1
        if self._current_streak > self._longest_streak:
            self._longest_streak = self._current_streak

    # -- queries ----------------------------------------------------------

    def total(self) -> int:
        """Total divergence events recorded."""
        return len(self._events)

    def streak(self) -> int:
        """Current consecutive clean-push count (reset on divergence)."""
        return self._current_streak

    def longest_streak(self) -> int:
        """Longest clean-push streak ever observed."""
        return self._longest_streak

    def clean_pushes(self) -> int:
        """Total clean pushes recorded (not reset by divergences)."""
        return self._clean_pushes

    def by_resolution(self) -> dict[str, int]:
        """Count divergence events grouped by resolution method."""
        counts: dict[str, int] = {}
        for ev in self._events:
            r = ev["resolution"]
            counts[r] = counts.get(r, 0) + 1
        return counts

    def divergence_rate(self) -> float:
        """Fraction of pushes that were divergent.

        Returns 0.0 when no pushes have been recorded at all.
        """
        total_pushes = self._clean_pushes + len(self._events)
        if total_pushes == 0:
            return 0.0
        return len(self._events) / total_pushes

    def summary(self) -> dict[str, Any]:
        """Compact summary dict for dashboards and commit messages."""
        return {
            "divergences": self.total(),
            "clean_pushes": self._clean_pushes,
            "current_streak": self._current_streak,
            "longest_streak": self._longest_streak,
            "divergence_rate": round(self.divergence_rate(), 4),
            "by_resolution": self.by_resolution(),
        }

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Full state for persistence."""
        return {
            "events": list(self._events),
            "clean_pushes": self._clean_pushes,
            "current_streak": self._current_streak,
            "longest_streak": self._longest_streak,
            "max_history": self._max_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DivergenceTracker":
        """Restore from a previously serialised dict."""
        tracker = cls(max_history=data.get("max_history", 1000))
        tracker._events = list(data.get("events", []))
        tracker._clean_pushes = data.get("clean_pushes", 0)
        tracker._current_streak = data.get("current_streak", 0)
        tracker._longest_streak = data.get("longest_streak", 0)
        return tracker

    def __repr__(self) -> str:
        s = self.summary()
        return (
            f"DivergenceTracker(divergences={s['divergences']}, "
            f"clean={s['clean_pushes']}, "
            f"streak={s['current_streak']}, "
            f"rate={s['divergence_rate']:.2%})"
        )
