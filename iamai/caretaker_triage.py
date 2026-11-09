#!/usr/bin/env python3
"""caretaker_triage — decide what the caretaker should do *right now*.

The repo has dozens of modules that **describe** the current state:
``stall_classifier`` says whether the writer is stalled, ``cadence_drift``
says how far it has drifted, ``process_liveness`` says whether PIDs are
alive, and ``commit_staleness`` says how old the last commit is.  Each
one is correct.  None of them tells the caretaker **what to do**.

This module collects every relevant signal into a single ``TriageReport``
with prioritised, actionable recommendations.  The caretaker reads the
report top-down and executes the first action that applies.

Signal dimensions
-----------------

==================  =====================================================
signal              source / meaning
==================  =====================================================
writer_alive        bool — is the writer process running?
batch_alive         bool — is the batch committer running?
stall_class         str — NONE / MILD / MODERATE / SEVERE
drift_class         str — tight / warm / hot
uncommitted         int — number of uncommitted files
unpushed            int — commits ahead of origin
loop_severity       str — NONE / MILD / MODERATE / SEVERE
uptime_s            float — seconds since last restart
==================  =====================================================

Decision logic
--------------

1. **RESTART_WRITER** — writer is dead, or stall is SEVERE with hot drift.
2. **RESTART_BATCH** — batch committer is dead while writer is alive.
3. **COMMIT_BACKLOG** — uncommitted files exceed the stale threshold (5).
4. **PUSH** — unpushed commits exceed 0 and push has not been attempted.
5. **BREAK_LOOP** — loop severity is MODERATE or SEVERE.
6. **INVESTIGATE_DRIFT** — drift class is hot but writer is still alive.
7. **MONITOR** — nothing actionable; writer is healthy.

Each ``Decision`` carries a **priority** (1 = do first) and a short
human-readable **reason** so the caretaker log stays informative.

Public API
----------

- ``triage(signals) -> TriageReport``
- ``TriageReport.actions()``  — list of ``Decision``, priority-sorted
- ``TriageReport.top_action()`` — single highest-priority ``Decision``
- ``TriageReport.summary()`` — one-line human-readable summary

Usage::

    from iamai.caretaker_triage import triage

    signals = {
        "writer_alive": False,
        "batch_alive": False,
        "stall_class": "SEVERE",
        "drift_class": "hot",
        "uncommitted": 7,
        "unpushed": 1,
        "loop_severity": "NONE",
        "uptime_s": 0,
    }
    report = triage(signals)
    print(report.top_action())   # Decision(RESTART_WRITER, ...)
    print(report.summary())      # "RESTART_WRITER: process dead, ..."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------

class Priority(IntEnum):
    """Action priority — lower number = higher urgency."""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    INFO = 5


@dataclass(frozen=True)
class Decision:
    """A single recommended caretaker action."""
    action: str
    priority: Priority
    reason: str

    def __str__(self) -> str:
        return f"{self.action} [{self.priority.name}]: {self.reason}"


@dataclass(frozen=True)
class TriageReport:
    """Prioritised list of caretaker actions."""
    decisions: list[Decision] = field(default_factory=list)
    healthy: bool = False

    def actions(self) -> list[Decision]:
        """Return decisions sorted by priority (most urgent first)."""
        return sorted(self.decisions, key=lambda d: d.priority)

    def top_action(self) -> Decision | None:
        """Return the single highest-priority decision, or None if healthy."""
        acts = self.actions()
        return acts[0] if acts else None

    def summary(self) -> str:
        """One-line human-readable summary of the triage result."""
        if self.healthy and not self.decisions:
            return "HEALTHY: no action needed"
        top = self.top_action()
        if top is None:
            return "HEALTHY: no action needed"
        parts = [str(d) for d in self.actions()[:3]]
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Thresholds (module-level, overridable via signals dict)
# ---------------------------------------------------------------------------

DEFAULT_UNCOMMITTED_THRESHOLD = 5
DEFAULT_UPTIME_WARN_S = 300  # 5 minutes — if recently restarted, note it


# ---------------------------------------------------------------------------
# Core triage logic
# ---------------------------------------------------------------------------

def triage(signals: dict[str, Any]) -> TriageReport:
    """Evaluate *signals* and return a ``TriageReport``.

    Parameters
    ----------
    signals : dict
        Must contain the keys listed in "Signal dimensions" above.
        Missing keys are treated as their most benign default:
        ``writer_alive=True``, ``batch_alive=True``, ``stall_class="NONE"``,
        ``drift_class="tight"``, ``uncommitted=0``, ``unpushed=0``,
        ``loop_severity="NONE"``, ``uptime_s=0``.
    """
    writer_alive: bool = signals.get("writer_alive", True)
    batch_alive: bool = signals.get("batch_alive", True)
    stall_class: str = signals.get("stall_class", "NONE")
    drift_class: str = signals.get("drift_class", "tight")
    uncommitted: int = signals.get("uncommitted", 0)
    unpushed: int = signals.get("unpushed", 0)
    loop_severity: str = signals.get("loop_severity", "NONE")
    uptime_s: float = signals.get("uptime_s", 0)

    uncommitted_threshold: int = signals.get(
        "uncommitted_threshold", DEFAULT_UNCOMMITTED_THRESHOLD
    )

    decisions: list[Decision] = []

    # 1. Writer dead → restart (CRITICAL)
    if not writer_alive:
        decisions.append(Decision(
            action="RESTART_WRITER",
            priority=Priority.CRITICAL,
            reason="writer process is not running",
        ))

    # 2. Writer alive but SEVERE stall + hot drift → restart (CRITICAL)
    if writer_alive and stall_class == "SEVERE" and drift_class == "hot":
        decisions.append(Decision(
            action="RESTART_WRITER",
            priority=Priority.CRITICAL,
            reason="severe stall with hot drift — writer degraded beyond recovery",
        ))

    # 3. Batch dead while writer alive → restart batch (HIGH)
    if not batch_alive and writer_alive:
        decisions.append(Decision(
            action="RESTART_BATCH",
            priority=Priority.HIGH,
            reason="batch committer dead while writer is alive — commits will pile up",
        ))

    # 4. Both dead → also restart batch (HIGH, but after writer)
    if not batch_alive and not writer_alive:
        decisions.append(Decision(
            action="RESTART_BATCH",
            priority=Priority.HIGH,
            reason="batch committer is not running",
        ))

    # 5. Uncommitted backlog exceeds threshold (HIGH)
    if uncommitted > uncommitted_threshold:
        decisions.append(Decision(
            action="COMMIT_BACKLOG",
            priority=Priority.HIGH,
            reason=f"{uncommitted} uncommitted files exceed threshold ({uncommitted_threshold})",
        ))
    elif uncommitted > 0:
        decisions.append(Decision(
            action="COMMIT_BACKLOG",
            priority=Priority.MEDIUM,
            reason=f"{uncommitted} uncommitted file(s) pending",
        ))

    # 6. Unpushed commits (MEDIUM)
    if unpushed > 0:
        decisions.append(Decision(
            action="PUSH",
            priority=Priority.MEDIUM,
            reason=f"{unpushed} commit(s) not yet pushed to remote",
        ))

    # 7. Content loop (MEDIUM–HIGH depending on severity)
    if loop_severity in ("SEVERE", "MODERATE"):
        prio = Priority.HIGH if loop_severity == "SEVERE" else Priority.MEDIUM
        decisions.append(Decision(
            action="BREAK_LOOP",
            priority=prio,
            reason=f"content loop severity is {loop_severity} — writer is recycling patterns",
        ))

    # 8. Drift investigation (LOW–MEDIUM)
    if drift_class == "hot" and writer_alive:
        decisions.append(Decision(
            action="INVESTIGATE_DRIFT",
            priority=Priority.MEDIUM,
            reason="cadence drift is hot — writer may be degrading",
        ))
    elif drift_class == "warm":
        decisions.append(Decision(
            action="INVESTIGATE_DRIFT",
            priority=Priority.LOW,
            reason="cadence drift is warm — within tolerance but trending up",
        ))

    # 9. Recent restart note (INFO)
    if 0 < uptime_s < DEFAULT_UPTIME_WARN_S:
        decisions.append(Decision(
            action="MONITOR",
            priority=Priority.INFO,
            reason=f"writer restarted {uptime_s:.0f}s ago — watch for early crash",
        ))

    healthy = len([d for d in decisions if d.priority <= Priority.MEDIUM]) == 0
    return TriageReport(decisions=decisions, healthy=healthy)
