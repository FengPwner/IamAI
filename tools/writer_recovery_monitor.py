#!/usr/bin/env python3
"""Writer recovery monitor — detect and classify restart gaps.

When the writer process dies, there is a gap in the stroke sequence:
the last stroke before the crash and the first stroke after the
restart may be minutes or hours apart.  This module finds those gaps,
measures how well the writer recovered its cadence, and classifies
each restart event.

Recovery classifications:

- **recovered** — post-restart cadence is within tolerance of pre-crash
- **degraded**  — post-restart cadence is noticeably slower
- **failed**    — post-restart cadence is extremely slow or absent

The ``analyze`` function ties it all together: load a writer's stroke
history, find restart gaps, classify each recovery, and produce a
summary report.

Usage::

    from writer_recovery_monitor import analyze, as_markdown

    report = analyze(writer_id="qwen")
    print(as_markdown(report))

Design choices:

- **Pure computation over the stroke history.**  No subprocess calls,
  no git operations — just reads the JSON state file.
- **Configurable gap threshold.**  Default 150 s catches real stalls
  without flagging normal cadence jitter.
- **Tolerance-based classification.**  ``DEFAULT_TOLERANCE`` = 0.50
  means post-cadence within 50 % of pre-cadence counts as recovered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_TOLERANCE: float = 0.50
DEGRADED_FLOOR: float = 0.10
DEFAULT_GAP_THRESHOLD: float = 150.0
DEFAULT_SAMPLE: int = 20


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RecoveryEvent:
    """One detected restart gap with pre/post cadence analysis."""

    gap_index: int
    gap_start_iso: str
    gap_end_iso: str
    gap_seconds: float
    pre_cadence: Optional[float]
    post_cadence: Optional[float]
    recovery_ratio: Optional[float]
    status: str  # "recovered", "degraded", "failed"
    sample_pre: int
    sample_post: int

    @property
    def gap_human(self) -> str:
        """Human-readable gap duration."""
        s = self.gap_seconds
        if s < 120:
            return f"{s:.0f}s"
        if s < 3600:
            return f"{s / 60:.1f}m"
        return f"{s / 3600:.1f}h"


@dataclass
class RecoveryReport:
    """Summary of all restart gaps found in a writer's history."""

    writer_id: str
    total_strokes: int
    restarts_found: int
    events: List[RecoveryEvent] = field(default_factory=list)
    overall_status: str = "healthy"

    @property
    def recovered_count(self) -> int:
        return sum(1 for e in self.events if e.status == "recovered")

    @property
    def degraded_count(self) -> int:
        return sum(1 for e in self.events if e.status == "degraded")

    @property
    def failed_count(self) -> int:
        return sum(1 for e in self.events if e.status == "failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def state_path(writer_id: str) -> Path:
    """Default path for a writer's state file."""
    return Path("data") / f"writer_state.{writer_id}.json"


def parse_iso(ts: str) -> float:
    """Parse an ISO-8601 timestamp string to a Unix epoch float.

    Handles:
    - ``Z`` suffix → UTC
    - ``+HH:MM`` offset
    - Naive timestamps → assumed UTC
    - Leading/trailing whitespace
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def load_history(writer_id: str) -> list:
    """Load stroke history from the writer's state file.

    Raises
    ------
    FileNotFoundError
        If the state file does not exist.
    json.JSONDecodeError
        If the file contains invalid JSON.
    ValueError
        If the ``history`` field is not a list.
    """
    path = state_path(writer_id)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    history = data.get("history", [])
    if not isinstance(history, list):
        raise ValueError(f"history field is not a list (got {type(history).__name__})")
    return history


# ---------------------------------------------------------------------------
# Cadence computation
# ---------------------------------------------------------------------------


def compute_cadence(
    history: list,
    index: int,
    direction: str,
    sample: int = DEFAULT_SAMPLE,
) -> Tuple[Optional[float], int]:
    """Compute mean inter-stroke interval around a gap index.

    Parameters
    ----------
    history : list
        Stroke dicts, each with an ``"at"`` ISO-8601 field.
    index : int
        Index of the stroke at the gap boundary.
    direction : str
        ``"before"`` — look at strokes *before* this index.
        ``"after"``  — look at strokes *after* this index.
    sample : int
        Number of strokes to include in the window.

    Returns
    -------
    (mean_interval, n_intervals)
        ``mean_interval`` is None if fewer than 2 strokes are available.
    """
    if direction == "before":
        end = index + 1  # exclusive upper bound
        start = max(0, end - sample)
        window = history[start:end]
    else:  # "after"
        start = index
        end = min(len(history), start + sample)
        window = history[start:end]

    n = len(window)
    if n < 2:
        return None, max(0, n - 1)

    epochs = [parse_iso(s["at"]) for s in window]
    intervals = []
    for i in range(1, len(epochs)):
        gap = abs(epochs[i] - epochs[i - 1])
        intervals.append(gap)

    if not intervals:
        return None, 0

    return sum(intervals) / len(intervals), len(intervals)


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------


def find_restart_gaps(
    history: list,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> List[int]:
    """Find indices where a restart gap begins.

    Returns a list of indices ``i`` (the first stroke *after* the gap)
    such that the gap between ``history[i-1]`` and ``history[i]``
    exceeds *gap_threshold* seconds.

    This convention means ``i`` points at the *restart stroke* — the
    first stroke the writer produced after coming back online.
    """
    if len(history) < 2:
        return []

    gaps: List[int] = []
    for i in range(1, len(history)):
        t0 = parse_iso(history[i - 1]["at"])
        t1 = parse_iso(history[i]["at"])
        if (t1 - t0) > gap_threshold:
            gaps.append(i)
    return gaps


# ---------------------------------------------------------------------------
# Recovery classification
# ---------------------------------------------------------------------------


def classify_recovery(
    pre: Optional[float],
    post: Optional[float],
    tolerance: float = DEFAULT_TOLERANCE,
) -> str:
    """Classify a restart recovery as 'recovered', 'degraded', or 'failed'.

    Parameters
    ----------
    pre : float or None
        Mean inter-stroke interval *before* the restart (seconds).
    post : float or None
        Mean inter-stroke interval *after* the restart (seconds).
    tolerance : float
        Fractional tolerance for the 'recovered' band.
        ``ratio >= 1 − tolerance`` → recovered.
    """
    # Failed: no post data or effectively dead
    if post is None or post <= 0:
        return "failed"

    # Both unknown — assume recovered (no evidence of failure)
    if pre is None:
        # Heuristic: slow absolute cadence → degraded
        if post > 120:
            return "degraded"
        return "recovered"

    ratio = pre / post

    if ratio < DEGRADED_FLOOR:
        return "failed"
    if ratio > (1.0 - tolerance):
        return "recovered"
    return "degraded"


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


def analyze(
    writer_id: str = "qwen",
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
    sample: int = DEFAULT_SAMPLE,
    tolerance: float = DEFAULT_TOLERANCE,
) -> RecoveryReport:
    """Analyze a writer's recovery history.

    Loads the stroke history from the state file, detects restart gaps,
    classifies each recovery, and produces a ``RecoveryReport``.
    """
    try:
        history = load_history(writer_id)
    except (FileNotFoundError, json.JSONDecodeError):
        return RecoveryReport(
            writer_id=writer_id,
            total_strokes=0,
            restarts_found=0,
            overall_status="unknown",
        )
    except ValueError:
        return RecoveryReport(
            writer_id=writer_id,
            total_strokes=0,
            restarts_found=0,
            overall_status="unknown",
        )

    total = len(history)
    if total == 0:
        return RecoveryReport(
            writer_id=writer_id,
            total_strokes=0,
            restarts_found=0,
            overall_status="insufficient_data",
        )

    gap_indices = find_restart_gaps(history, gap_threshold)
    events: List[RecoveryEvent] = []

    for gi in gap_indices:
        # gi = first stroke AFTER the gap; gi-1 = last stroke BEFORE
        pre_idx = gi - 1
        t0 = parse_iso(history[pre_idx]["at"])
        t1 = parse_iso(history[gi]["at"])
        gap_sec = t1 - t0

        pre_cad, n_pre = compute_cadence(history, pre_idx, "before", sample)
        post_cad, n_post = compute_cadence(history, gi, "after", sample)

        ratio = (pre_cad / post_cad) if (pre_cad and post_cad and post_cad > 0) else None
        status = classify_recovery(pre_cad, post_cad, tolerance)

        events.append(RecoveryEvent(
            gap_index=pre_idx,
            gap_start_iso=history[pre_idx]["at"],
            gap_end_iso=history[gi]["at"],
            gap_seconds=gap_sec,
            pre_cadence=pre_cad,
            post_cadence=post_cad,
            recovery_ratio=ratio,
            status=status,
            sample_pre=n_pre,
            sample_post=n_post,
        ))

    # Determine overall status (worst wins)
    if not events:
        overall = "healthy"
    else:
        severity = {"recovered": 0, "degraded": 1, "failed": 2}
        worst = max(events, key=lambda e: severity.get(e.status, 0))
        overall = worst.status

    return RecoveryReport(
        writer_id=writer_id,
        total_strokes=total,
        restarts_found=len(events),
        events=events,
        overall_status=overall,
    )


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------


def as_markdown(report: RecoveryReport) -> str:
    """Format a RecoveryReport as a Markdown string."""
    lines = [
        f"## Writer Recovery: {report.writer_id}",
        "",
        f"- **Total strokes:** {report.total_strokes}",
        f"- **Restarts detected:** {report.restarts_found}",
        f"- **Overall status:** {report.overall_status}",
        "",
    ]

    if not report.events:
        lines.append("no restart gaps detected")
        return "\n".join(lines)

    for i, ev in enumerate(report.events, 1):
        lines.extend([
            f"### restart {i}",
            "",
            f"- **Gap:** {ev.gap_human} ({ev.gap_start_iso} → {ev.gap_end_iso})",
            f"- **Pre-cadence:** {ev.pre_cadence:.1f}s" if ev.pre_cadence else "- **Pre-cadence:** N/A",
            f"- **Post-cadence:** {ev.post_cadence:.1f}s" if ev.post_cadence else "- **Post-cadence:** N/A",
            f"- **Recovery ratio:** {ev.recovery_ratio:.3f}" if ev.recovery_ratio is not None else "- **Recovery ratio:** N/A",
            f"- **Status:** {ev.status}",
            "",
        ])

    return "\n".join(lines)
