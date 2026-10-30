"""Process supervisor: automatic restart with cooldown protection.

The watchdog detects dead processes. The remote_sync module handles push
races. But neither closes the loop: who restarts the writer when it dies
at 3 AM and no caretaker is watching?

The supervisor sits above the watchdog and below the caretaker. It reads
the watchdog report, decides whether a restart is safe, and either
triggers one or escalates. The key constraint is **cooldown**: if the
writer was restarted less than N seconds ago, do not restart again.
This prevents restart loops where a misconfigured writer crashes
immediately and the supervisor keeps bringing it back forever.

The design is pure logic (no subprocess calls) so it can be tested
without spawning real processes. Callers (the caretaker, a cron job,
the batch committer) supply the watchdog report and current time; the
supervisor returns a decision.

Decisions:

- **restart**: processes are dead and cooldown has elapsed.
- **wait**: processes are dead but cooldown has not elapsed yet.
- **healthy**: everything is running, nothing to do.
- **escalate**: processes are dead, cooldown exhausted (too many
  restarts in the window), human needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Decision(Enum):
    """What the supervisor recommends."""
    HEALTHY = "healthy"
    RESTART = "restart"
    WAIT = "wait"
    ESCALATE = "escalate"


@dataclass
class RestartRecord:
    """One recorded restart event."""
    timestamp: float
    writer_id: str
    reason: str = ""


@dataclass
class SupervisorConfig:
    """Tunable parameters for the supervisor.

    Attributes:
        cooldown_seconds: minimum seconds between restarts.
        max_restarts_in_window: if more than this many restarts happen
            within ``window_seconds``, escalate instead of restarting.
        window_seconds: sliding window for counting restarts.
    """
    cooldown_seconds: int = 300
    max_restarts_in_window: int = 3
    window_seconds: int = 3600


@dataclass
class SupervisorDecision:
    """The supervisor's output for one evaluation cycle."""
    decision: Decision
    reason: str = ""
    dead_processes: List[str] = field(default_factory=list)
    restarts_in_window: int = 0
    cooldown_remaining: float = 0.0

    @property
    def should_restart(self) -> bool:
        return self.decision == Decision.RESTART


@dataclass
class SupervisorState:
    """Mutable state the supervisor carries across evaluations.

    This is the only stateful object. It is intentionally a plain
    dataclass so callers can persist it as JSON.
    """
    restarts: List[RestartRecord] = field(default_factory=list)

    def recent_restarts(self, now: float, window: float) -> List[RestartRecord]:
        """Return restarts within the window."""
        cutoff = now - window
        return [r for r in self.restarts if r.timestamp >= cutoff]

    def last_restart_time(self) -> Optional[float]:
        """Timestamp of the most recent restart, or None."""
        if not self.restarts:
            return None
        return max(r.timestamp for r in self.restarts)

    def record_restart(self, now: float, writer_id: str, reason: str = "") -> None:
        """Record that a restart happened."""
        self.restarts.append(RestartRecord(
            timestamp=now,
            writer_id=writer_id,
            reason=reason,
        ))


def evaluate(
    all_alive: bool,
    dead_names: List[str],
    state: SupervisorState,
    now: float,
    config: Optional[SupervisorConfig] = None,
    writer_id: str = "qwen",
) -> SupervisorDecision:
    """Evaluate the current situation and return a decision.

    Args:
        all_alive: whether all expected processes are running.
        dead_names: names of processes that are not running.
        state: the supervisor's mutable state.
        now: current timestamp (time.time()).
        config: supervisor parameters (uses defaults if None).
        writer_id: which writer this evaluation is for.

    Returns:
        A SupervisorDecision with the recommendation and metadata.
    """
    cfg = config or SupervisorConfig()

    if all_alive:
        return SupervisorDecision(
            decision=Decision.HEALTHY,
            reason="All processes running.",
        )

    # Something is dead. Check cooldown.
    recent = state.recent_restarts(now, cfg.window_seconds)
    restart_count = len(recent)
    last_time = state.last_restart_time()
    cooldown_remaining = 0.0

    if last_time is not None:
        elapsed = now - last_time
        if elapsed < cfg.cooldown_seconds:
            cooldown_remaining = cfg.cooldown_seconds - elapsed

    # Too many restarts in the window — escalate.
    if restart_count >= cfg.max_restarts_in_window:
        return SupervisorDecision(
            decision=Decision.ESCALATE,
            reason=(
                f"{restart_count} restarts in the last {cfg.window_seconds}s "
                f"(limit {cfg.max_restarts_in_window}). "
                f"Dead: {', '.join(dead_names)}. Human intervention needed."
            ),
            dead_processes=dead_names,
            restarts_in_window=restart_count,
        )

    # Cooldown not elapsed — wait.
    if cooldown_remaining > 0:
        return SupervisorDecision(
            decision=Decision.WAIT,
            reason=(
                f"Dead: {', '.join(dead_names)}, but cooldown has "
                f"{cooldown_remaining:.0f}s remaining. Wait."
            ),
            dead_processes=dead_names,
            restarts_in_window=restart_count,
            cooldown_remaining=cooldown_remaining,
        )

    # Dead, cooldown elapsed, under restart limit — restart.
    return SupervisorDecision(
        decision=Decision.RESTART,
        reason=f"Dead: {', '.join(dead_names)}. Cooldown elapsed. Safe to restart.",
        dead_processes=dead_names,
        restarts_in_window=restart_count,
    )


def record_restart(
    state: SupervisorState,
    now: float,
    writer_id: str,
    reason: str = "",
) -> None:
    """Record that a restart was executed.

    Call this after actually restarting processes so the cooldown
    and escalation counters stay accurate.
    """
    state.record_restart(now, writer_id, reason)
