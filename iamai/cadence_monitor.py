"""cadence_monitor — track writing rhythm and detect slowdowns.

The writer aims for one stroke every *N* seconds and one batch commit
every *M* seconds.  This module measures actual cadence against targets
and classifies the result.

Public API
----------

``CadenceReport``
    Dataclass: actual_stroke_gap (float), actual_batch_gap (float),
    target_stroke_gap (float), target_batch_gap (float),
    health ('healthy' | 'slowing' | 'stalled'), reason (str).

``measure(repo_path, writer='qwen') -> CadenceReport``
    Read ``data/strokes.jsonl`` and git log to compute actual gaps.
    Pure observation — no side effects.

``is_healthy(report) -> bool``
    Quick predicate: True when health == 'healthy'.

Design choices
--------------

- Stroke gap is measured from the two most recent strokes in
  ``data/strokes.jsonl``.  If fewer than two strokes exist, the gap
  is reported as ``inf`` and health is 'stalled'.
- Batch gap is measured from the two most recent commits by the writer
  (identified by author email matching ``<writer>@iamai.local``).
- Thresholds: actual gap <= 1.5x target → healthy; <= 3x → slowing;
  beyond that → stalled.
- ``measure()`` shells out to ``git log`` only when necessary and
  reads the tail of strokes.jsonl rather than loading the whole file.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Default cadence targets (seconds)
DEFAULT_STROKE_TARGET = 15.0
DEFAULT_BATCH_TARGET = 600.0

# Health thresholds (multiplier of target)
_HEALTHY_MULT = 1.5
_SLOWING_MULT = 3.0


@dataclass(frozen=True)
class CadenceReport:
    actual_stroke_gap: float
    actual_batch_gap: float
    target_stroke_gap: float
    target_batch_gap: float
    health: str          # 'healthy' | 'slowing' | 'stalled'
    reason: str

    @property
    def stroke_ratio(self) -> float:
        """Actual / target stroke gap.  inf when target is 0."""
        if self.target_stroke_gap == 0:
            return float("inf")
        return self.actual_stroke_gap / self.target_stroke_gap

    @property
    def batch_ratio(self) -> float:
        """Actual / target batch gap.  inf when target is 0."""
        if self.target_batch_gap == 0:
            return float("inf")
        return self.actual_batch_gap / self.target_batch_gap


def _classify(actual: float, target: float) -> str:
    """Return 'healthy', 'slowing', or 'stalled' based on ratio."""
    if target <= 0:
        return "stalled"
    ratio = actual / target
    if ratio <= _HEALTHY_MULT:
        return "healthy"
    if ratio <= _SLOWING_MULT:
        return "slowing"
    return "stalled"


def _last_two_stroke_timestamps(strokes_path: Path) -> Optional[tuple[float, float]]:
    """Read the last two stroke timestamps from strokes.jsonl.

    Returns (newer, older) as Unix epoch floats, or None if fewer
    than two strokes exist.
    """
    if not strokes_path.exists():
        return None

    timestamps: list[float] = []
    try:
        with open(strokes_path, "r") as f:
            # Read from end — seek to last 4KB which should cover
            # the final two lines for typical stroke records.
            f.seek(0, 2)  # EOF
            size = f.tell()
            read_from = max(0, size - 4096)
            f.seek(read_from)
            if read_from > 0:
                f.readline()  # discard partial first line
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = record.get("ts") or record.get("timestamp")
                    if ts is not None:
                        timestamps.append(float(ts))
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return None

    if len(timestamps) < 2:
        return None

    timestamps.sort(reverse=True)
    return (timestamps[0], timestamps[1])


def _last_two_commit_timestamps(repo_path: Path, writer: str) -> Optional[tuple[float, float]]:
    """Get timestamps of the two most recent commits by writer.

    Uses ``git log`` with author filter.  Returns (newer, older)
    as Unix epoch floats, or None if fewer than two commits found.
    """
    author_pattern = f"{writer}@iamai.local"
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_path), "log",
                f"--author={author_pattern}",
                "--format=%ct",
                "-2",
            ],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None

    try:
        newer, older = float(lines[0]), float(lines[1])
    except ValueError:
        return None

    return (newer, older)


def measure(
    repo_path: str | Path,
    writer: str = "qwen",
    stroke_target: float = DEFAULT_STROKE_TARGET,
    batch_target: float = DEFAULT_BATCH_TARGET,
    now: Optional[float] = None,
) -> CadenceReport:
    """Measure current writing cadence.

    Parameters
    ----------
    repo_path : path to the git repo root.
    writer : writer name (used to filter commits by author email).
    stroke_target : expected seconds between strokes.
    batch_target : expected seconds between batch commits.
    now : override current time (for testing); defaults to time.time().

    Returns
    -------
    CadenceReport with actual gaps and health classification.
    """
    import time as _time

    repo_path = Path(repo_path)
    if now is None:
        now = _time.time()

    # --- stroke gap ---
    strokes_path = repo_path / "data" / "strokes.jsonl"
    stroke_pair = _last_two_stroke_timestamps(strokes_path)
    if stroke_pair is not None:
        stroke_gap = stroke_pair[0] - stroke_pair[1]
    else:
        stroke_gap = float("inf")

    # --- batch gap ---
    commit_pair = _last_two_commit_timestamps(repo_path, writer)
    if commit_pair is not None:
        batch_gap = commit_pair[0] - commit_pair[1]
    else:
        batch_gap = float("inf")

    # --- classify ---
    stroke_health = _classify(stroke_gap, stroke_target)
    batch_health = _classify(batch_gap, batch_target)

    # Overall health is the worse of the two
    severity = {"healthy": 0, "slowing": 1, "stalled": 2}
    overall = max(stroke_health, batch_health, key=lambda h: severity[h])

    reasons: list[str] = []
    if stroke_health != "healthy":
        reasons.append(
            f"stroke gap {stroke_gap:.0f}s (target {stroke_target:.0f}s, "
            f"ratio {stroke_gap / stroke_target:.1f}x)"
            if stroke_gap != float("inf")
            else "no stroke data"
        )
    if batch_health != "healthy":
        reasons.append(
            f"batch gap {batch_gap:.0f}s (target {batch_target:.0f}s, "
            f"ratio {batch_gap / batch_target:.1f}x)"
            if batch_gap != float("inf")
            else "no commit data for writer"
        )

    reason = "; ".join(reasons) if reasons else "all cadences on target"

    return CadenceReport(
        actual_stroke_gap=stroke_gap,
        actual_batch_gap=batch_gap,
        target_stroke_gap=stroke_target,
        target_batch_gap=batch_target,
        health=overall,
        reason=reason,
    )


def is_healthy(report: CadenceReport) -> bool:
    """True when the cadence is classified as healthy."""
    return report.health == "healthy"
