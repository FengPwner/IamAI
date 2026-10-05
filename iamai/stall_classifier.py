"""Classify writer stall severity based on gap duration.

A stall is when the writer stops producing strokes. The heartbeat detector
flags it, but not all stalls are equal:

- **recoverable**: gap < 2x cadence, likely transient (GC pause, momentary load)
- **concerning**: gap 2x-4x cadence, probably reclamation or crash
- **critical**: gap > 4x cadence, extended outage, data loss risk

The thresholds are multiples of the writer's cadence (default 15s) because
a stall is only meaningful relative to how often the writer should be ticking.
"""

from __future__ import annotations


def classify_stall(gap_seconds: int, cadence_seconds: int = 15) -> str:
    """Classify stall severity.

    Args:
        gap_seconds: seconds since last stroke
        cadence_seconds: expected interval between strokes

    Returns:
        One of: "ok", "recoverable", "concerning", "critical"

    Examples:
        >>> classify_stall(10, 15)
        'ok'
        >>> classify_stall(30, 15)
        'recoverable'
        >>> classify_stall(60, 15)
        'concerning'
        >>> classify_stall(120, 15)
        'critical'
    """
    if gap_seconds < cadence_seconds:
        return "ok"
    ratio = gap_seconds / cadence_seconds
    if ratio < 2:
        return "recoverable"
    if ratio < 4:
        return "concerning"
    return "critical"


def stall_advice(severity: str) -> str:
    """Human-readable advice for a given stall severity.

    Args:
        severity: output from classify_stall()

    Returns:
        Actionable advice string
    """
    advice = {
        "ok": "No stall detected. Writer is healthy.",
        "recoverable": "Brief pause. Monitor; likely transient. No action needed.",
        "concerning": "Extended stall. Check process status; may need restart.",
        "critical": "Long outage. Restart writer immediately; verify no data loss.",
    }
    return advice.get(severity, f"Unknown severity: {severity}")
