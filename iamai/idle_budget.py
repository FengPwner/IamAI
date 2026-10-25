"""Idle budget: how long the writer may stay silent before intervention.

A writer that pauses for maintenance is expected to resume.  A writer that
goes silent without explanation is a problem.  This module tracks the gap
between the last observed stroke and *now*, compares it to a configurable
budget, and classifies the situation:

* **healthy** — gap is within the normal cadence window
* **stretching** — gap is longer than one cadence but under the budget
* **overdue** — gap exceeds the budget; caretaker should check on the writer
* **critical** — gap is more than 2x the budget; likely a crash or deadlock

The budget itself is derived from the writer's configured cadence (``--every``
flag) plus a tolerance multiplier.  Default: cadence * 10, so a 15-second
writer gets a 150-second budget before it's "overdue."

Usage::

    from iamai.idle_budget import idle_status, IdleBudget

    budget = IdleBudget(cadence_seconds=15, tolerance=10)
    status = budget.classify(last_stroke_ago=200)
    # -> "overdue"

    print(idle_status())
    # "overdue: 200s idle, budget 150s (cadence 15s * 10x)"
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO_ROOT / "data" / "strokes.jsonl"


@dataclass(frozen=True)
class IdleBudget:
    """Configuration and classifier for writer idle time.

    >>> b = IdleBudget(cadence_seconds=15, tolerance=10)
    >>> b.budget_seconds
    150
    >>> b.classify(0)
    'healthy'
    >>> b.classify(100)
    'stretching'
    >>> b.classify(150)
    'overdue'
    >>> b.classify(300)
    'critical'
    """

    cadence_seconds: int = 15
    tolerance: int = 10

    @property
    def budget_seconds(self) -> int:
        """Maximum allowed idle time before the writer is considered overdue."""
        return self.cadence_seconds * self.tolerance

    def classify(self, idle_seconds: float) -> str:
        """Classify the current idle gap.

        Returns one of: 'healthy', 'stretching', 'overdue', 'critical'.
        Negative values (clock skew, future timestamps) map to 'healthy'.
        """
        if idle_seconds < 0:
            return "healthy"
        budget = self.budget_seconds
        if idle_seconds <= self.cadence_seconds:
            return "healthy"
        if idle_seconds < budget:
            return "stretching"
        if idle_seconds < budget * 2:
            return "overdue"
        return "critical"

    def describe(self, idle_seconds: float) -> str:
        """Human-readable one-liner for the current idle state."""
        status = self.classify(idle_seconds)
        return (
            f"{status}: {idle_seconds:.0f}s idle, "
            f"budget {self.budget_seconds}s "
            f"(cadence {self.cadence_seconds}s * {self.tolerance}x)"
        )


def _last_stroke_timestamp(strokes_file: Path | None = None) -> float | None:
    """Read the last entry from strokes.jsonl and return its epoch timestamp.

    Returns None if the file doesn't exist, is empty, or has no parseable
    timestamp on the last line.
    """
    path = strokes_file or STROKES_FILE
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None
        import json
        last = json.loads(lines[-1])
        ts = last.get("timestamp") or last.get("ts") or last.get("at")
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return float(ts)
        # ISO format string
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        return None


def _last_commit_timestamp() -> float | None:
    """Fallback: timestamp of the most recent commit."""
    try:
        raw = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        if raw.returncode == 0 and raw.stdout.strip():
            return float(raw.stdout.strip())
    except (ValueError, OSError):
        pass
    return None


def idle_status(
    cadence_seconds: int = 15,
    tolerance: int = 10,
    now: float | None = None,
) -> str:
    """Compute and return the current idle status as a human-readable string.

    Tries strokes.jsonl first, falls back to git log.  Returns a status
    message or 'unknown' if no timestamp source is available.
    """
    last_ts = _last_stroke_timestamp() or _last_commit_timestamp()
    if last_ts is None:
        return "unknown: no stroke or commit timestamp found"
    current = now or time.time()
    gap = current - last_ts
    budget = IdleBudget(cadence_seconds=cadence_seconds, tolerance=tolerance)
    return budget.describe(gap)


def budget_report(
    cadence_seconds: int = 15,
    tolerance: int = 10,
    now: float | None = None,
) -> dict[str, Any]:
    """Structured idle-budget report for programmatic consumers.

    Returns a dict with keys: status, idle_seconds, budget_seconds,
    cadence_seconds, tolerance, last_timestamp.
    """
    last_ts = _last_stroke_timestamp() or _last_commit_timestamp()
    current = now or time.time()
    budget = IdleBudget(cadence_seconds=cadence_seconds, tolerance=tolerance)

    if last_ts is None:
        return {
            "status": "unknown",
            "idle_seconds": None,
            "budget_seconds": budget.budget_seconds,
            "cadence_seconds": cadence_seconds,
            "tolerance": tolerance,
            "last_timestamp": None,
        }

    gap = current - last_ts
    return {
        "status": budget.classify(gap),
        "idle_seconds": round(gap, 1),
        "budget_seconds": budget.budget_seconds,
        "cadence_seconds": cadence_seconds,
        "tolerance": tolerance,
        "last_timestamp": last_ts,
    }
