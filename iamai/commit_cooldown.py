"""Commit cooldown — back off after consecutive push failures.

When `git push` fails (remote ahead, network timeout, rate limit), the batch
committer keeps accumulating local commits. The next push attempt then has
*more* to push, increasing the chance of another conflict or timeout.

This module tracks consecutive push failures and computes a cooldown period
during which new commits should be skipped or deferred. The cooldown grows
exponentially (with a cap) and resets on the first successful push.

Usage:
    tracker = CooldownTracker(state_path="data/push_cooldown.json")
    if tracker.in_cooldown():
        remaining = tracker.remaining_seconds()
        log(f"push cooldown active, {remaining}s remaining — skipping")
    else:
        ok = do_push()
        if ok:
            tracker.record_success()
        else:
            tracker.record_failure()

Design choices:
- Base cooldown: 60s (one batch cycle). Long enough for transient issues to
  clear, short enough to retry quickly.
- Cap: 600s (10 minutes). Beyond this, the caretaker should intervene.
- Exponential backoff factor: 2.0. Each consecutive failure doubles the wait.
- State persisted to disk so cooldown survives process restarts.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_BASE = 60        # seconds
DEFAULT_CAP = 600        # seconds
DEFAULT_FACTOR = 2.0


class CooldownTracker:
    """Track consecutive push failures and enforce a cooldown window."""

    def __init__(
        self,
        state_path: str | Path = "data/push_cooldown.json",
        base: int = DEFAULT_BASE,
        cap: int = DEFAULT_CAP,
        factor: float = DEFAULT_FACTOR,
        now_fn: Any | None = None,
    ) -> None:
        self._path = Path(state_path)
        self._base = base
        self._cap = cap
        self._factor = factor
        self._now = now_fn or time.time
        self._state: dict[str, Any] = self._load()

    # -- public API --

    def record_failure(self) -> int:
        """Record a push failure. Returns the new failure count."""
        self._state["consecutive_failures"] = self._state.get("consecutive_failures", 0) + 1
        self._state["last_failure_at"] = self._now()
        self._state["cooldown_until"] = self._now() + self._cooldown_duration()
        self._state["total_failures"] = self._state.get("total_failures", 0) + 1
        self._save()
        return self._state["consecutive_failures"]

    def record_success(self) -> None:
        """Record a successful push, resetting the cooldown."""
        self._state["consecutive_failures"] = 0
        self._state["cooldown_until"] = 0
        self._state["last_success_at"] = self._now()
        self._state["total_successes"] = self._state.get("total_successes", 0) + 1
        self._save()

    def in_cooldown(self) -> bool:
        """Check whether we are currently in a cooldown window."""
        until = self._state.get("cooldown_until", 0)
        return self._now() < until

    def remaining_seconds(self) -> int:
        """Seconds remaining in the current cooldown, or 0 if not in cooldown."""
        until = self._state.get("cooldown_until", 0)
        rem = until - self._now()
        return max(0, int(rem))

    def consecutive_failures(self) -> int:
        """Number of consecutive failures since last success."""
        return self._state.get("consecutive_failures", 0)

    def total_failures(self) -> int:
        """Lifetime total push failures."""
        return self._state.get("total_failures", 0)

    def total_successes(self) -> int:
        """Lifetime total successful pushes."""
        return self._state.get("total_successes", 0)

    def current_cooldown_duration(self) -> int:
        """The cooldown duration that would apply right now (seconds)."""
        return self._cooldown_duration()

    def summary(self) -> dict[str, Any]:
        """Human-readable summary of the current state."""
        return {
            "in_cooldown": self.in_cooldown(),
            "remaining_seconds": self.remaining_seconds(),
            "consecutive_failures": self.consecutive_failures(),
            "total_failures": self.total_failures(),
            "total_successes": self.total_successes(),
            "cooldown_duration": self.current_cooldown_duration(),
        }

    def reset(self) -> None:
        """Reset all state (for testing or manual intervention)."""
        self._state = {
            "consecutive_failures": 0,
            "cooldown_until": 0,
            "total_failures": 0,
            "total_successes": 0,
        }
        self._save()

    # -- internals --

    def _cooldown_duration(self) -> int:
        """Compute cooldown duration based on consecutive failure count."""
        n = self._state.get("consecutive_failures", 0)
        if n == 0:
            return 0
        duration = self._base * (self._factor ** (n - 1))
        return min(int(duration), self._cap)

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state, indent=2), encoding="utf-8"
        )
