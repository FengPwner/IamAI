"""process_zombie — detect writer/batch processes that are alive but inert.

A *zombie* process has a valid PID (the OS says it's running) yet has
not produced any observable output within a configurable grace window.
This is the most dangerous failure mode: the caretaker sees "running"
and assumes health, while nothing is actually happening.

Contrast with existing modules:

- ``stale_pid_detector`` — PID file exists but the process is *dead*.
  Zombie detection is the complement: PID is *alive* but output is dead.
- ``stall_classifier`` — looks at gaps between strokes; this module
  correlates the gap with PID liveness to distinguish "slow writer"
  from "zombie writer".
- ``writer_vitality`` — composite health score; this module is a
  single-purpose binary classifier that feeds into it.

Usage::

    from iamai.process_zombie import classify, ZombieReport

    report = classify(
        pid_alive=True,
        last_output_age_s=1800,
        grace_s=900,
    )
    print(report.status)   # "zombie"
    print(report.action)   # "restart"

Status taxonomy:

===========  ===========  ============================================
status       action       meaning
===========  ===========  ============================================
healthy      none         PID alive, output fresh
zombie       restart      PID alive, output stale past grace window
dead         restart      PID not alive
unknown      investigate  Cannot determine (missing inputs)
===========  ===========  ============================================

The module is pure-Python with no subprocess calls; all inputs are
passed as arguments so it can be used in tests and simulations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_GRACE_S = 900        # 15 minutes — writer cadence is ~15 s
DEFAULT_HARD_LIMIT_S = 3600  # 1 hour — batch interval is 600 s


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZombieReport:
    """Result of a zombie classification."""

    status: str       # healthy | zombie | dead | unknown
    action: str       # none | restart | investigate
    pid_alive: bool
    last_output_age_s: Optional[float]
    grace_s: float
    detail: str

    @property
    def needs_intervention(self) -> bool:
        return self.action in ("restart", "investigate")

    def summary(self) -> str:
        age = f"{self.last_output_age_s:.0f}s" if self.last_output_age_s is not None else "?"
        return f"{self.status} (pid={'up' if self.pid_alive else 'down'}, output={age}, grace={self.grace_s:.0f}s)"


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify(
    *,
    pid_alive: bool,
    last_output_age_s: Optional[float] = None,
    grace_s: float = DEFAULT_GRACE_S,
    hard_limit_s: float = DEFAULT_HARD_LIMIT_S,
) -> ZombieReport:
    """Classify a writer/batch process as healthy, zombie, dead, or unknown.

    Parameters
    ----------
    pid_alive : bool
        Whether the OS reports the PID as running.
    last_output_age_s : float or None
        Seconds since the process last produced observable output
        (stroke file, commit, log line).  None means we don't know.
    grace_s : float
        How many seconds of silence before a live PID becomes a zombie.
    hard_limit_s : float
        Absolute ceiling; even if the PID looks healthy, if output age
        exceeds this value we still flag it.

    Returns
    -------
    ZombieReport
    """
    # Case 1: PID is not alive → dead
    if not pid_alive:
        return ZombieReport(
            status="dead",
            action="restart",
            pid_alive=False,
            last_output_age_s=last_output_age_s,
            grace_s=grace_s,
            detail="process not running; restart required",
        )

    # Case 2: PID alive but output age unknown → can't classify
    if last_output_age_s is None:
        return ZombieReport(
            status="unknown",
            action="investigate",
            pid_alive=True,
            last_output_age_s=None,
            grace_s=grace_s,
            detail="pid alive but no output timestamp available",
        )

    # Case 3: PID alive, output fresh → healthy
    if last_output_age_s <= grace_s:
        return ZombieReport(
            status="healthy",
            action="none",
            pid_alive=True,
            last_output_age_s=last_output_age_s,
            grace_s=grace_s,
            detail=f"output {last_output_age_s:.0f}s old, within grace window",
        )

    # Case 4: PID alive, output stale but under hard limit → zombie
    if last_output_age_s <= hard_limit_s:
        return ZombieReport(
            status="zombie",
            action="restart",
            pid_alive=True,
            last_output_age_s=last_output_age_s,
            grace_s=grace_s,
            detail=f"pid alive but silent for {last_output_age_s:.0f}s (grace={grace_s:.0f}s)",
        )

    # Case 5: Hard limit exceeded → zombie (critical)
    return ZombieReport(
        status="zombie",
        action="restart",
        pid_alive=True,
        last_output_age_s=last_output_age_s,
        grace_s=grace_s,
        detail=f"pid alive but silent for {last_output_age_s:.0f}s — exceeds hard limit {hard_limit_s:.0f}s",
    )


# ---------------------------------------------------------------------------
# Batch classifier — check both writer and committer at once
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DualZombieReport:
    """Combined classification for writer + batch processes."""

    writer: ZombieReport
    batch: ZombieReport

    @property
    def all_healthy(self) -> bool:
        return self.writer.status == "healthy" and self.batch.status == "healthy"

    @property
    def any_zombie(self) -> bool:
        return self.writer.status == "zombie" or self.batch.status == "zombie"

    @property
    def any_dead(self) -> bool:
        return self.writer.status == "dead" or self.batch.status == "dead"

    def summary(self) -> str:
        return f"writer: {self.writer.summary()} | batch: {self.batch.summary()}"


def classify_dual(
    *,
    writer_pid_alive: bool,
    writer_last_output_s: Optional[float] = None,
    batch_pid_alive: bool,
    batch_last_output_s: Optional[float] = None,
    grace_s: float = DEFAULT_GRACE_S,
    hard_limit_s: float = DEFAULT_HARD_LIMIT_S,
) -> DualZombieReport:
    """Classify both writer and batch processes in one call."""
    return DualZombieReport(
        writer=classify(
            pid_alive=writer_pid_alive,
            last_output_age_s=writer_last_output_s,
            grace_s=grace_s,
            hard_limit_s=hard_limit_s,
        ),
        batch=classify(
            pid_alive=batch_pid_alive,
            last_output_age_s=batch_last_output_s,
            grace_s=grace_s,
            hard_limit_s=hard_limit_s,
        ),
    )
