"""push_retry_budget — track push attempts and enforce a retry ceiling.

When a push fails (non-fast-forward, network error, remote lock), the
caretaker should retry — but not forever.  An unbounded retry loop wastes
API calls, masks real failures, and can deadlock if the remote is
permanently unreachable.

This module provides a pure-Python, no-subprocess budget tracker:

    budget = PushRetryBudget(window_minutes=60, max_retries=5)
    budget.record_attempt(success=False)
    budget.record_attempt(success=False)
    budget.can_retry()          # True  (3 retries left)
    budget.remaining()          # 3
    budget.status()             # "2/5 retries in 60min window, 3 remaining"

Design choices:
  - Sliding window: only attempts within the last N minutes count.
    Old failures expire naturally — a bad hour doesn't poison tomorrow.
  - Thread-safe via a simple list; no external locking needed for the
    single-process caretaker use case.
  - Deterministic: callers control ``now`` so tests don't need time.sleep.

Severity:
  - ``ok``:       under half the budget used
  - ``warn``:     over half but not exhausted
  - ``exhausted``: no retries remaining
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class PushRetryBudget:
    """Track push retry attempts within a sliding time window."""

    def __init__(
        self,
        window_minutes: float = 60,
        max_retries: int = 5,
    ) -> None:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be positive")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")

        self.window_minutes = window_minutes
        self.max_retries = max_retries
        self._attempts: list[dict[str, Any]] = []

    def record_attempt(
        self,
        success: bool,
        error: str = "",
        now: datetime | None = None,
    ) -> None:
        """Record a push attempt.

        Args:
            success: True if push succeeded, False otherwise.
            error: Error message if failed (empty on success).
            now: Override current time (for testing). Defaults to utcnow.
        """
        ts = now or datetime.now(timezone.utc)
        self._attempts.append({
            "at": ts,
            "success": success,
            "error": error,
        })

    def _prune(self, now: datetime | None = None) -> None:
        """Remove attempts outside the sliding window."""
        ts = now or datetime.now(timezone.utc)
        cutoff = ts.timestamp() - self.window_minutes * 60
        self._attempts = [
            a for a in self._attempts
            if a["at"].timestamp() > cutoff
        ]

    def attempts_in_window(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return all attempts within the current window.

        Args:
            now: Override current time (for testing).

        Returns:
            List of attempt dicts (copies, safe to mutate).
        """
        self._prune(now)
        return list(self._attempts)

    def failures_in_window(self, now: datetime | None = None) -> int:
        """Count failed attempts in the current window."""
        return sum(
            1 for a in self.attempts_in_window(now)
            if not a["success"]
        )

    def successes_in_window(self, now: datetime | None = None) -> int:
        """Count successful attempts in the current window."""
        return sum(
            1 for a in self.attempts_in_window(now)
            if a["success"]
        )

    def remaining(self, now: datetime | None = None) -> int:
        """How many retries are left in the current window.

        Returns:
            Non-negative integer. Zero means budget is exhausted.
        """
        used = self.failures_in_window(now)
        return max(0, self.max_retries - used)

    def can_retry(self, now: datetime | None = None) -> bool:
        """Whether another retry is allowed.

        Returns:
            True if at least one retry remains, False if budget exhausted.
        """
        return self.remaining(now) > 0

    def severity(self, now: datetime | None = None) -> str:
        """Classify current budget usage.

        Returns:
            'ok'        — under half the budget used
            'warn'      — over half but not exhausted
            'exhausted' — no retries remaining

        Examples:
            >>> b = PushRetryBudget(max_retries=4)
            >>> b.severity()
            'ok'
        """
        used = self.failures_in_window(now)
        if used >= self.max_retries:
            return "exhausted"
        if used > self.max_retries / 2:
            return "warn"
        return "ok"

    def status(self, now: datetime | None = None) -> str:
        """Human-readable one-liner summarizing the budget state.

        Returns:
            String like "2/5 retries in 60min window, 3 remaining"

        Example:
            >>> b = PushRetryBudget(max_retries=5, window_minutes=30)
            >>> b.record_attempt(success=False, error="non-fast-forward")
            >>> s = b.status()
            >>> "1/5" in s
            True
        """
        used = self.failures_in_window(now)
        left = self.remaining(now)
        return (
            f"{used}/{self.max_retries} retries in "
            f"{self.window_minutes:.0f}min window, "
            f"{left} remaining"
        )

    def last_error(self) -> str:
        """Return the most recent error message, or empty string.

        Returns:
            Error string from the last failed attempt, or "".

        Example:
            >>> b = PushRetryBudget()
            >>> b.record_attempt(success=False, error="timeout")
            >>> b.last_error()
            'timeout'
        """
        for a in reversed(self._attempts):
            if not a["success"]:
                return a["error"]
        return ""

    def reset(self) -> None:
        """Clear all recorded attempts. Useful after a successful push."""
        self._attempts.clear()

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        """Serialize the budget state to a plain dict.

        Returns:
            Dict with keys: window_minutes, max_retries, used, remaining,
            severity, last_error, attempts.
        """
        attempts = self.attempts_in_window(now)
        return {
            "window_minutes": self.window_minutes,
            "max_retries": self.max_retries,
            "used": self.failures_in_window(now),
            "remaining": self.remaining(now),
            "severity": self.severity(now),
            "last_error": self.last_error(),
            "attempts": [
                {
                    "at": a["at"].isoformat(),
                    "success": a["success"],
                    "error": a["error"],
                }
                for a in attempts
            ],
        }
