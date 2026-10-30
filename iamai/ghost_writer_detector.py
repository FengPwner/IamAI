"""Ghost writer detector: identify alive-but-silent writer processes.

A writer process may remain technically running (PID exists, no crash signal)
while producing no output.  This "ghost writer" state is harder to detect than
a clean crash because traditional process monitors report it as healthy.

The detector tracks the gap between expected and actual output, and classifies
the writer into one of four states:

- **alive**: output arriving on schedule
- **suspicious**: one deadline missed, could be transient load
- **ghost**: two or more deadlines missed -- process likely hung or stalled
- **dead**: confirmed process exit (PID gone)

The deadline is derived from the writer's cadence plus a tolerance margin.
For a 15-second cadence with 2x tolerance, a writer that hasn't produced
anything for 30 seconds is suspicious; at 60 seconds it's a ghost.

Usage::

    from iamai.ghost_writer_detector import GhostWriterDetector

    d = GhostWriterDetector(cadence=15, tolerance=2.0)
    d.record_heartbeat(now=100.0)
    d.classify(now=110.0)          # "alive"  (10s < 30s deadline)
    d.classify(now=140.0)          # "suspicious" (40s > 30s deadline)
    d.classify(now=200.0)          # "ghost" (100s > 60s = 2x deadline)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


# Classification constants
ALIVE = "alive"
SUSPICIOUS = "suspicious"
GHOST = "ghost"
DEAD = "dead"


@dataclass
class GhostWriterDetector:
    """Detect when a writer process is alive but producing no output.

    Parameters
    ----------
    cadence : float
        Expected seconds between consecutive outputs (strokes).
    tolerance : float
        Multiplier on cadence to form the deadline.  A tolerance of 2.0
        means the writer gets one full cadence of grace before being
        flagged suspicious.  Default 2.0.
    ghost_multiplier : float
        How many deadlines must be missed before classification escalates
        from suspicious to ghost.  Default 2.0 (i.e. 2x the deadline).
    pid : int or None
        Optional PID to check liveness.  If None, liveness is not checked
        and the detector relies purely on heartbeat timing.
    """

    cadence: float
    tolerance: float = 2.0
    ghost_multiplier: float = 2.0
    pid: Optional[int] = None
    _last_heartbeat: float = -1.0
    _missed_deadlines: int = 0
    _total_heartbeats: int = 0

    @property
    def deadline(self) -> float:
        """Seconds of silence before the writer is considered suspicious."""
        return self.cadence * self.tolerance

    @property
    def ghost_threshold(self) -> float:
        """Seconds of silence before the writer is classified as ghost."""
        return self.deadline * self.ghost_multiplier

    def record_heartbeat(self, now: float) -> None:
        """Record that the writer produced output at time *now*."""
        self._last_heartbeat = now
        self._missed_deadlines = 0
        self._total_heartbeats += 1

    def _is_process_alive(self) -> Optional[bool]:
        """Check if the PID is still running.

        Returns True if alive, False if dead, None if no PID configured.
        """
        if self.pid is None:
            return None
        try:
            os.kill(self.pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def classify(self, now: float) -> str:
        """Classify the writer's current state.

        Returns one of: ALIVE, SUSPICIOUS, GHOST, DEAD.

        Priority: DEAD (PID check) > GHOST > SUSPICIOUS > ALIVE.
        If no PID is configured, DEAD is never returned.
        """
        # Check process liveness if PID is available
        alive = self._is_process_alive()
        if alive is False:
            return DEAD

        # No heartbeats recorded yet
        if self._last_heartbeat < 0:
            return GHOST

        silence = now - self._last_heartbeat

        if silence <= self.deadline:
            return ALIVE
        elif silence < self.ghost_threshold:
            return SUSPICIOUS
        else:
            return GHOST

    def silence_duration(self, now: float) -> float:
        """Seconds since the last heartbeat.  Returns 0 if never recorded."""
        if self._last_heartbeat < 0:
            return 0.0
        return max(0.0, now - self._last_heartbeat)

    def health_score(self, now: float) -> float:
        """Compute a 0.0-1.0 health score based on heartbeat recency.

        1.0 = heartbeat just arrived, 0.0 = silence >= ghost_threshold.
        Linear interpolation in between.
        """
        if self._last_heartbeat < 0:
            return 0.0
        silence = self.silence_duration(now)
        if silence <= 0:
            return 1.0
        if silence >= self.ghost_threshold:
            return 0.0
        # Linear: 1.0 at deadline=0, 0.0 at ghost_threshold
        return max(0.0, 1.0 - (silence / self.ghost_threshold))

    def summary(self, now: float) -> dict:
        """Full diagnostic snapshot."""
        return {
            "state": self.classify(now),
            "silence_seconds": round(self.silence_duration(now), 2),
            "deadline": self.deadline,
            "ghost_threshold": self.ghost_threshold,
            "health_score": round(self.health_score(now), 4),
            "total_heartbeats": self._total_heartbeats,
            "pid": self.pid,
            "pid_alive": self._is_process_alive(),
        }

    def reset(self) -> None:
        """Clear all tracking state."""
        self._last_heartbeat = -1.0
        self._missed_deadlines = 0
        self._total_heartbeats = 0


def diagnose_writer(
    last_output: float,
    now: float,
    cadence: float = 15.0,
    pid: Optional[int] = None,
) -> dict:
    """One-shot diagnosis of a writer's health.

    Parameters
    ----------
    last_output : float
        Timestamp of the writer's last produced output.
    now : float
        Current timestamp.
    cadence : float
        Expected interval between outputs.
    pid : int or None
        Optional PID for liveness check.

    Returns
    -------
    dict with state, silence_seconds, health_score, pid_alive.
    """
    detector = GhostWriterDetector(cadence=cadence, pid=pid)
    if last_output >= 0:
        detector.record_heartbeat(now=last_output)
    state = detector.classify(now=now)
    return {
        "state": state,
        "silence_seconds": round(detector.silence_duration(now), 2),
        "health_score": round(detector.health_score(now), 4),
        "pid_alive": detector._is_process_alive(),
    }
