"""DeadlineTracker — track soft and hard deadlines with grace periods.

Many systems need to distinguish between "ideally done by" and "must be
done by".  A soft deadline with a grace window lets you escalate before
a hard cutoff.  A hard deadline is absolute: past it, the work is stale.

DeadlineTracker manages a set of named deadlines, each with:

- ``soft``:  the ideal completion time
- ``grace``: seconds of buffer after soft before hard triggers
- ``hard``:  soft + grace (computed, not set directly)

States returned by ``check(name)``:

- ``"ok"``        — before soft deadline
- ``"soft"``      — past soft, within grace
- ``"hard"``      — past hard deadline (soft + grace)
- ``"done"``      — explicitly marked complete

Zero dependencies.  Stdlib only.

>>> import time
>>> dt = DeadlineTracker(now=lambda: 100.0)
>>> dt.add("report", soft=110.0, grace=5.0)
>>> dt.check("report")
'ok'
>>> dt._now = lambda: 112.0
>>> dt.check("report")
'soft'
>>> dt._now = lambda: 116.0
>>> dt.check("report")
'hard'
>>> dt.complete("report")
>>> dt.check("report")
'done'
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass
class _Deadline:
    soft: float
    grace: float
    completed: bool = False

    @property
    def hard(self) -> float:
        return self.soft + self.grace


class DeadlineTracker:
    """Track named deadlines with soft/hard boundaries."""

    def __init__(self, now: Optional[Callable[[], float]] = None):
        self._now = now or (lambda: _time.monotonic())
        self._deadlines: Dict[str, _Deadline] = {}

    def add(self, name: str, soft: float, grace: float = 0.0) -> None:
        """Register a deadline.

        Args:
            name:  unique identifier for this deadline
            soft:  the ideal completion timestamp
            grace: seconds of buffer after soft before hard triggers
        """
        if grace < 0:
            raise ValueError(f"grace must be >= 0, got {grace}")
        self._deadlines[name] = _Deadline(soft=soft, grace=grace)

    def check(self, name: str) -> str:
        """Return the current state of a deadline.

        Returns one of: "ok", "soft", "hard", "done".
        Raises KeyError if the deadline does not exist.
        """
        dl = self._deadlines[name]
        if dl.completed:
            return "done"
        t = self._now()
        if t < dl.soft:
            return "ok"
        if t < dl.hard:
            return "soft"
        return "hard"

    def complete(self, name: str) -> None:
        """Mark a deadline as completed (regardless of current time)."""
        self._deadlines[name].completed = True

    def remaining(self, name: str) -> float:
        """Seconds until the hard deadline.  Negative if past due.

        Returns float('inf') for completed deadlines.
        """
        dl = self._deadlines[name]
        if dl.completed:
            return float("inf")
        return dl.hard - self._now()

    def overdue(self) -> list[str]:
        """Return names of all deadlines past their hard deadline."""
        t = self._now()
        return [
            n for n, dl in self._deadlines.items()
            if not dl.completed and t >= dl.hard
        ]

    def approaching(self, within: float = 0.0) -> list[str]:
        """Return names of deadlines within ``within`` seconds of hard.

        Only includes non-completed deadlines that haven't passed hard yet.
        """
        t = self._now()
        return [
            n for n, dl in self._deadlines.items()
            if not dl.completed
            and t < dl.hard
            and (dl.hard - t) <= within
        ]

    def remove(self, name: str) -> None:
        """Remove a deadline entirely."""
        del self._deadlines[name]

    def names(self) -> list[str]:
        """Return all tracked deadline names."""
        return list(self._deadlines.keys())

    def summary(self) -> Dict[str, dict]:
        """Return a snapshot of all deadlines and their states."""
        t = self._now()
        out = {}
        for n, dl in self._deadlines.items():
            state = "done" if dl.completed else (
                "ok" if t < dl.soft else
                "soft" if t < dl.hard else "hard"
            )
            out[n] = {
                "state": state,
                "soft": dl.soft,
                "hard": dl.hard,
                "remaining": float("inf") if dl.completed else dl.hard - t,
            }
        return out
