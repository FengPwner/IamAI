"""restart_recovery — measure how fast a writer returns to steady cadence.

After a restart, the critical question is: did the writer actually recover,
or is it stumbling?  This module analyses the post-restart stroke stream
and produces a recovery report.

Metrics
-------
``recovery_time_s``
    Seconds from restart until the writer achieved N consecutive
    on-cadence strokes (default N=3).  ``None`` if not yet recovered.

``first_stroke_latency_s``
    Seconds from restart until the first stroke appeared.

``cadence_stability``
    Coefficient of variation (std/mean) of inter-stroke intervals in
    the recovered window.  Lower = more stable.  ``None`` if <2 strokes.

``recovery_quality``
    One of: ``fast`` (<60s), ``normal`` (60–300s), ``slow`` (300–600s),
    ``stalled`` (>600s or not recovered).

Usage::

    from iamai.restart_recovery import analyse_recovery
    report = analyse_recovery(strokes_path, restart_time, cadence_s=15)
    print(report.quality, report.recovery_time_s)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence


@dataclass
class RecoveryReport:
    """Result of a restart-recovery analysis."""

    restart_time: datetime
    first_stroke_latency_s: Optional[float]
    recovery_time_s: Optional[float]
    strokes_to_steady: int
    cadence_stability: Optional[float]
    quality: str  # fast | normal | slow | stalled
    intervals: list[float]

    def to_dict(self) -> dict:
        return {
            "restart_time": self.restart_time.isoformat(),
            "first_stroke_latency_s": self.first_stroke_latency_s,
            "recovery_time_s": self.recovery_time_s,
            "strokes_to_steady": self.strokes_to_steady,
            "cadence_stability": self.cadence_stability,
            "quality": self.quality,
            "intervals": self.intervals,
        }


def _parse_strokes(path: Path) -> list[datetime]:
    """Extract timestamps from strokes.jsonl (newest last)."""
    if not path.exists():
        return []
    times = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = obj.get("ts") or obj.get("timestamp") or obj.get("time")
        if ts is None:
            continue
        if isinstance(ts, (int, float)):
            times.append(datetime.fromtimestamp(ts, tz=timezone.utc))
        elif isinstance(ts, str):
            # try ISO format
            try:
                times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except ValueError:
                continue
    return sorted(times)


def _classify(recovery_s: Optional[float]) -> str:
    if recovery_s is None:
        return "stalled"
    if recovery_s < 60:
        return "fast"
    if recovery_s <= 300:
        return "normal"
    if recovery_s <= 600:
        return "slow"
    return "stalled"


def analyse_recovery(
    strokes_path: Path | str,
    restart_time: datetime,
    cadence_s: float = 15.0,
    consecutive: int = 3,
    tolerance: float = 2.0,
) -> RecoveryReport:
    """Analyse post-restart recovery from a strokes file.

    Parameters
    ----------
    strokes_path : path to strokes.jsonl
    restart_time : when the writer was restarted (timezone-aware)
    cadence_s : expected seconds between strokes
    consecutive : how many on-cadence strokes count as "recovered"
    tolerance : multiplier — interval must be <= cadence_s * tolerance
    """
    strokes_path = Path(strokes_path)
    all_times = _parse_strokes(strokes_path)

    # only look at strokes after restart
    post = [t for t in all_times if t >= restart_time]

    if not post:
        return RecoveryReport(
            restart_time=restart_time,
            first_stroke_latency_s=None,
            recovery_time_s=None,
            strokes_to_steady=0,
            cadence_stability=None,
            quality="stalled",
            intervals=[],
        )

    first_latency = (post[0] - restart_time).total_seconds()

    # compute inter-stroke intervals
    intervals = []
    for i in range(1, len(post)):
        intervals.append((post[i] - post[i - 1]).total_seconds())

    # find recovery point: `consecutive` intervals all <= cadence_s * tolerance
    threshold = cadence_s * tolerance
    streak = 0
    recovery_idx = None
    for i, iv in enumerate(intervals):
        if iv <= threshold:
            streak += 1
            if streak >= consecutive:
                recovery_idx = i
                break
        else:
            streak = 0

    if recovery_idx is None:
        return RecoveryReport(
            restart_time=restart_time,
            first_stroke_latency_s=first_latency,
            recovery_time_s=None,
            strokes_to_steady=len(post),
            cadence_stability=None,
            quality="stalled",
            intervals=intervals,
        )

    recovery_time = (post[recovery_idx] - restart_time).total_seconds()

    # cadence stability: CV of the last `consecutive` intervals
    window = intervals[max(0, recovery_idx - consecutive + 1): recovery_idx + 1]
    if len(window) >= 2:
        mean_iv = sum(window) / len(window)
        if mean_iv > 0:
            variance = sum((x - mean_iv) ** 2 for x in window) / len(window)
            std_iv = variance ** 0.5
            stability = std_iv / mean_iv
        else:
            stability = 0.0
    else:
        stability = None

    return RecoveryReport(
        restart_time=restart_time,
        first_stroke_latency_s=first_latency,
        recovery_time_s=recovery_time,
        strokes_to_steady=recovery_idx + 1,
        cadence_stability=stability,
        quality=_classify(recovery_time),
        intervals=intervals[: recovery_idx + 1],
    )
