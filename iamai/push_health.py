"""Push health tracker: monitor push success rate and detect degradation.

A self-writing repository pushes hundreds of commits per day.  When pushes
start failing repeatedly, the problem is rarely a one-off network blip --
it is usually a diverged remote, an expired token, or a lock conflict.

PushHealth tracks recent push outcomes in a fixed-size sliding window and
derives a health score (0.0 -- 1.0).  It also counts consecutive failures
to detect sustained degradation and offers actionable recovery advice.

All operations are O(1) amortised (deque with maxlen) and pure (no I/O).

Usage::

    from iamai.push_health import PushHealth

    ph = PushHealth(window=20)
    ph.record(success=True)
    ph.record(success=False)
    ph.score()                # 0.5  (1 of 2 succeeded)
    ph.consecutive_failures   # 1
    ph.diagnose()             # "degraded"
    ph.advise()               # "fetch and rebase before next push"
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


# Health tiers
HEALTHY = "healthy"
DEGRADED = "degraded"
CRITICAL = "critical"


@dataclass
class PushHealth:
    """Sliding-window push health tracker.

    Parameters
    ----------
    window : int
        Maximum number of push attempts to remember.  Older attempts are
        evicted automatically.  Default 20.
    degrade_threshold : float
        Health score below which the state becomes ``degraded``.  Default 0.6.
    critical_threshold : float
        Health score below which the state becomes ``critical``.  Default 0.3.
    consecutive_alert : int
        Number of consecutive failures that triggers ``critical`` regardless
        of the overall score.  Default 3.
    """

    window: int = 20
    degrade_threshold: float = 0.6
    critical_threshold: float = 0.3
    consecutive_alert: int = 3
    _history: deque = field(default_factory=lambda: deque(maxlen=20))
    _consecutive_failures: int = 0
    _total_pushes: int = 0
    _total_successes: int = 0

    def __post_init__(self) -> None:
        # Ensure deque respects the configured window size.
        self._history = deque(self._history, maxlen=self.window)

    # -- recording -----------------------------------------------------------

    def record(self, success: bool) -> None:
        """Record a push attempt outcome."""
        self._history.append(success)
        self._total_pushes += 1
        if success:
            self._total_successes += 1
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

    # -- queries -------------------------------------------------------------

    @property
    def attempts(self) -> int:
        """Number of push attempts currently in the window."""
        return len(self._history)

    @property
    def successes(self) -> int:
        """Number of successful pushes in the current window."""
        return sum(1 for s in self._history if s)

    @property
    def failures(self) -> int:
        """Number of failed pushes in the current window."""
        return self.attempts - self.successes

    @property
    def consecutive_failures(self) -> int:
        """Current streak of consecutive failures (reset on success)."""
        return self._consecutive_failures

    @property
    def lifetime_rate(self) -> float:
        """All-time success rate (0.0 -- 1.0).  Returns 1.0 if no pushes."""
        if self._total_pushes == 0:
            return 1.0
        return self._total_successes / self._total_pushes

    def score(self) -> float:
        """Current window health score (0.0 -- 1.0).

        The score is simply the fraction of successful pushes in the window.
        An empty window scores 1.0 (no evidence of trouble).
        """
        if not self._history:
            return 1.0
        return self.successes / self.attempts

    # -- diagnosis -----------------------------------------------------------

    def diagnose(self) -> str:
        """Classify push health into a tier.

        Returns one of ``HEALTHY``, ``DEGRADED``, or ``CRITICAL``.

        The classification considers both the overall window score and the
        consecutive failure streak.  A streak of ``consecutive_alert`` or
        more forces ``CRITICAL`` even if the window score is still above
        the critical threshold.
        """
        s = self.score()
        if self._consecutive_failures >= self.consecutive_alert:
            return CRITICAL
        if s < self.critical_threshold:
            return CRITICAL
        if s < self.degrade_threshold:
            return DEGRADED
        return HEALTHY

    def advise(self) -> str:
        """Return a one-line recovery suggestion based on current health.

        The advice is keyed to the diagnosis tier, not the specific failure
        reason (which this tracker does not inspect).
        """
        tier = self.diagnose()
        if tier == HEALTHY:
            return "push health is fine, keep going"
        if tier == DEGRADED:
            return "fetch and rebase before next push"
        # CRITICAL
        if self._consecutive_failures >= self.consecutive_alert:
            return (
                f"{self._consecutive_failures} consecutive failures — "
                "stop pushing, fetch origin, rebase, then retry"
            )
        return "push success rate critically low, check remote and credentials"

    # -- convenience ---------------------------------------------------------

    def reset(self) -> None:
        """Clear all history and counters."""
        self._history.clear()
        self._consecutive_failures = 0
        self._total_pushes = 0
        self._total_successes = 0

    def __repr__(self) -> str:
        return (
            f"PushHealth(score={self.score():.2f}, "
            f"tier={self.diagnose()}, "
            f"window={self.attempts}/{self.window}, "
            f"streak_fails={self._consecutive_failures})"
        )
