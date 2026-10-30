"""Track and classify push recovery attempts.

When ``git push`` fails the caretaker must decide: retry immediately,
pull-and-retry, or escalate.  This module records each attempt, classifies
the failure mode, and exposes a recovery strategy.

Failure modes
-------------

- **diverged** — remote has commits we lack (``fetch first``).
  Fix: pull (merge or rebase) then retry.
- **rejected_nonfastforward** — force-push was attempted on a protected
  branch.  Fix: never force-push; escalate.
- **network** — transient transport error (timeout, DNS, TLS).
  Fix: exponential backoff, up to ``max_retries``.
- **auth** — credentials expired or revoked.
  Fix: escalate immediately, do not retry.
- **unknown** — anything else.  Fix: log and escalate.

Public API
----------

- ``PushAttempt(success: bool, failure_mode: str | None, timestamp: float)``
  — immutable record of one push attempt.
- ``PushRecoveryTracker(max_retries: int = 3)`` — accumulates attempts,
  returns the recommended next action.
- ``next_action(tracker) -> str`` — one of ``"retry"``, ``"pull_retry"``,
  ``"backoff"``, ``"escalate"``.

Edge cases
----------

- Zero attempts → ``next_action`` returns ``"retry"`` (optimistic).
- Exceeding ``max_retries`` always returns ``"escalate"``.
- Auth failures skip straight to ``"escalate"`` regardless of retry count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import time


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

FAILURE_MODES = frozenset({
    "diverged",
    "rejected_nonfastforward",
    "network",
    "auth",
    "unknown",
})

ACTIONS = frozenset({"retry", "pull_retry", "backoff", "escalate"})

_BACKOFF_BASE_SECONDS = 5.0
_BACKOFF_MAX_SECONDS = 120.0


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PushAttempt:
    """Immutable record of a single push attempt."""

    success: bool
    failure_mode: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.failure_mode is not None and self.failure_mode not in FAILURE_MODES:
            raise ValueError(
                f"unknown failure_mode {self.failure_mode!r}; "
                f"expected one of {sorted(FAILURE_MODES)}"
            )
        if self.success and self.failure_mode is not None:
            raise ValueError("successful push must have failure_mode=None")


# ---------------------------------------------------------------------------
# tracker
# ---------------------------------------------------------------------------

class PushRecoveryTracker:
    """Accumulate push attempts and recommend the next action."""

    def __init__(self, max_retries: int = 3) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.max_retries = max_retries
        self.attempts: List[PushAttempt] = []

    # -- mutation ----------------------------------------------------------

    def record(self, attempt: PushAttempt) -> None:
        self.attempts.append(attempt)

    def record_failure(self, failure_mode: str) -> None:
        self.record(PushAttempt(success=False, failure_mode=failure_mode))

    def record_success(self) -> None:
        self.record(PushAttempt(success=True))

    # -- queries -----------------------------------------------------------

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)

    @property
    def consecutive_failures(self) -> int:
        count = 0
        for a in reversed(self.attempts):
            if a.success:
                break
            count += 1
        return count

    @property
    def last_failure_mode(self) -> Optional[str]:
        for a in reversed(self.attempts):
            if not a.success:
                return a.failure_mode
        return None

    @property
    def is_escalated(self) -> bool:
        if self.consecutive_failures > self.max_retries:
            return True
        if self.last_failure_mode == "auth":
            return True
        if self.last_failure_mode == "rejected_nonfastforward":
            return True
        return False

    # -- strategy ----------------------------------------------------------

    def next_action(self) -> str:
        """Return the recommended next action."""
        if not self.attempts:
            return "retry"

        last = self.attempts[-1]
        if last.success:
            return "retry"

        # hard escalations
        if last.failure_mode == "auth":
            return "escalate"
        if last.failure_mode == "rejected_nonfastforward":
            return "escalate"

        # exceeded budget
        if self.consecutive_failures > self.max_retries:
            return "escalate"

        # mode-specific actions
        if last.failure_mode == "diverged":
            return "pull_retry"
        if last.failure_mode == "network":
            return "backoff"

        # unknown → escalate
        return "escalate"

    def backoff_seconds(self) -> float:
        """Return the recommended backoff duration for a network retry."""
        n = self.consecutive_failures
        delay = _BACKOFF_BASE_SECONDS * (2 ** max(n - 1, 0))
        return min(delay, _BACKOFF_MAX_SECONDS)

    # -- reset -------------------------------------------------------------

    def reset(self) -> None:
        self.attempts.clear()
