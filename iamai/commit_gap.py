"""commit_gap — detect writer stalls by measuring time since last commit.

The writer emits a stroke every ~15 s and the batch committer bundles them
every ~600 s.  When the gap between *now* and the last commit exceeds a
configurable threshold, something has broken: the process died, the sandbox
was recycled, or a git operation deadlocked.

This module provides a pure-Python, no-subprocess API so it can be tested
without touching a real repository.  Callers (heartbeat.py, caretaker
scripts, process supervisors) pass in the epoch of the last commit and get
back a structured report.

Design choices:
  - Thresholds are configurable: cadence=15s writer, interval=600s batch.
    Default thresholds are 2× and 4× the batch interval.
  - Severity levels: 'healthy' / 'warn' / 'stall' — maps to caretaker
    escalation tiers (log → alert → restart).
  - Includes a 'gap_seconds' field so callers can build their own UI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


# Default thresholds (seconds).
WARN_THRESHOLD = 1200.0   # 2× batch interval (20 min)
STALL_THRESHOLD = 2400.0  # 4× batch interval (40 min)


@dataclass(frozen=True)
class GapReport:
    """Structured result of a gap measurement."""

    gap_seconds: float
    severity: str          # 'healthy' | 'warn' | 'stall'
    message: str
    needs_restart: bool

    @property
    def is_healthy(self) -> bool:
        return self.severity == "healthy"

    def as_dict(self) -> dict:
        return {
            "gap_seconds": round(self.gap_seconds, 1),
            "severity": self.severity,
            "message": self.message,
            "needs_restart": self.needs_restart,
        }


def measure_gap(
    last_commit_epoch: float,
    now: Optional[float] = None,
    warn_threshold: float = WARN_THRESHOLD,
    stall_threshold: float = STALL_THRESHOLD,
) -> GapReport:
    """Measure the time since the last commit and classify severity.

    Parameters
    ----------
    last_commit_epoch : float
        Unix timestamp of the most recent commit.
    now : float, optional
        Current time (defaults to ``time.time()``).
    warn_threshold : float
        Gap in seconds before severity becomes 'warn'.
    stall_threshold : float
        Gap in seconds before severity becomes 'stall'.

    Returns
    -------
    GapReport
    """
    _now = now if now is not None else time.time()
    gap = max(0.0, _now - last_commit_epoch)

    if gap < warn_threshold:
        return GapReport(
            gap_seconds=gap,
            severity="healthy",
            message=f"last commit {gap:.0f}s ago — within normal cadence",
            needs_restart=False,
        )

    if gap < stall_threshold:
        return GapReport(
            gap_seconds=gap,
            severity="warn",
            message=f"last commit {gap:.0f}s ago — approaching stall threshold",
            needs_restart=False,
        )

    return GapReport(
        gap_seconds=gap,
        severity="stall",
        message=f"last commit {gap:.0f}s ago — writer likely stalled",
        needs_restart=True,
    )


def gap_from_log(
    log_path: str,
    now: Optional[float] = None,
    warn_threshold: float = WARN_THRESHOLD,
    stall_threshold: float = STALL_THRESHOLD,
) -> GapReport:
    """Read the last commit time from a git log one-liner file.

    Expects the file to contain lines like::

        2026-10-07T02:45:12+08:00  abc1234  some message

    Only the first whitespace-delimited token of the *last* line is parsed.
    """
    from datetime import datetime, timezone

    with open(log_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        return GapReport(
            gap_seconds=float("inf"),
            severity="stall",
            message="commit log is empty — no commits recorded",
            needs_restart=True,
        )

    last_line = lines[-1]
    ts_str = last_line.split()[0]
    try:
        dt = datetime.fromisoformat(ts_str)
        epoch = dt.timestamp()
    except (ValueError, IndexError):
        return GapReport(
            gap_seconds=float("inf"),
            severity="stall",
            message=f"could not parse timestamp from: {last_line!r}",
            needs_restart=True,
        )

    return measure_gap(epoch, now=now,
                       warn_threshold=warn_threshold,
                       stall_threshold=stall_threshold)
