#!/usr/bin/env python3
"""restart_settling_monitor.py — measure how quickly the writer regains
steady cadence after a process restart.

A restart is detected as a gap in the stroke timeline that exceeds
`--gap-threshold` seconds (default: 5× the expected cadence).  After
each gap the tool measures how many subsequent strokes it takes — and
how many seconds elapse — before the rolling average interval returns
to within `--tolerance` (default: 30 %) of the target cadence.

Usage:
    python3 tools/restart_settling_monitor.py                 # human output
    python3 tools/restart_settling_monitor.py --json          # machine-readable
    python3 tools/restart_settling_monitor.py --cadence 15    # expected 15 s
    python3 tools/restart_settling_monitor.py --gap-threshold 120
    python3 tools/restart_settling_monitor.py --tail 500      # scan last 500 strokes

Exit codes:
    0  settled    — all detected restarts recovered within settle_window
    1  unsettled  — at least one restart has not yet settled
    2  no data    — fewer than 3 strokes available
    3  no restart — no restart gaps found in the scanned window
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Status constants
SETTLED = "settled"
UNSETTLED = "unsettled"
NO_RESTART = "no_restart"
NO_DATA = "no_data"


@dataclass
class SettlingEvent:
    """One detected restart and its settling metrics."""
    gap_seconds: float          # duration of the silence (restart gap)
    gap_end_iso: str            # ISO timestamp of the first stroke after the gap
    strokes_to_settle: int      # how many strokes until cadence normalised
    seconds_to_settle: float    # wall-clock seconds until cadence normalised
    settled: bool               # did it settle within the window?
    post_gap_intervals: list    # the first N intervals after the gap (seconds)


@dataclass
class SettlingReport:
    """Aggregate report across all detected restarts."""
    status: str                 # settled | unsettled | no_restart | no_data
    target_cadence: float       # expected seconds per stroke
    events: List[SettlingEvent]
    total_restarts: int
    settled_count: int
    unsettled_count: int
    median_settle_seconds: Optional[float]
    max_settle_seconds: Optional[float]


def parse_stroke_times(path: Path) -> List[datetime]:
    """Read strokes.jsonl and return sorted list of stroke timestamps."""
    if not path.exists():
        return []
    times: list[datetime] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts = obj.get("at", "")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    times.append(dt)
            except (json.JSONDecodeError, ValueError):
                continue
    times.sort()
    return times


def detect_restart_gaps(
    times: List[datetime],
    gap_threshold: float,
) -> List[int]:
    """Return indices i where interval(times[i-1], times[i]) >= gap_threshold.

    Each such index marks the first stroke after a suspected restart.
    """
    indices: list[int] = []
    for i in range(1, len(times)):
        delta = (times[i] - times[i - 1]).total_seconds()
        if delta >= gap_threshold:
            indices.append(i)
    return indices


def measure_settling(
    times: List[datetime],
    restart_idx: int,
    target_cadence: float,
    tolerance: float,
    settle_window: int,
) -> SettlingEvent:
    """Measure how quickly cadence normalises after the stroke at restart_idx.

    settle_window: max number of post-restart intervals to examine.
    tolerance: fraction of target_cadence within which the rolling average
               is considered "settled"  (e.g. 0.3 → ±30 %).

    Returns a SettlingEvent.
    """
    gap_seconds = (times[restart_idx] - times[restart_idx - 1]).total_seconds()
    gap_end_iso = times[restart_idx].isoformat()

    # Collect intervals after the restart
    post_intervals: list[float] = []
    end = min(restart_idx + settle_window + 1, len(times))
    for i in range(restart_idx + 1, end):
        iv = (times[i] - times[i - 1]).total_seconds()
        post_intervals.append(iv)

    # Walk through intervals with a rolling window of size 5
    win = 5
    strokes_to_settle = 0
    seconds_to_settle = 0.0
    settled_flag = False

    if len(post_intervals) >= win:
        for j in range(win, len(post_intervals) + 1):
            window = post_intervals[j - win : j]
            avg = sum(window) / len(window)
            lo = target_cadence * (1 - tolerance)
            hi = target_cadence * (1 + tolerance)
            if lo <= avg <= hi:
                strokes_to_settle = j
                seconds_to_settle = sum(post_intervals[:j])
                settled_flag = True
                break

    # If we never settled within the available data
    if not settled_flag:
        strokes_to_settle = len(post_intervals)
        seconds_to_settle = sum(post_intervals) if post_intervals else 0.0

    return SettlingEvent(
        gap_seconds=gap_seconds,
        gap_end_iso=gap_end_iso,
        strokes_to_settle=strokes_to_settle,
        seconds_to_settle=round(seconds_to_settle, 2),
        settled=settled_flag,
        post_gap_intervals=[round(iv, 2) for iv in post_intervals[:settle_window]],
    )


def analyze(
    times: List[datetime],
    target_cadence: float,
    gap_threshold: float,
    tolerance: float,
    settle_window: int,
) -> SettlingReport:
    """Run the full settling analysis."""
    if len(times) < 3:
        return SettlingReport(
            status=NO_DATA,
            target_cadence=target_cadence,
            events=[],
            total_restarts=0,
            settled_count=0,
            unsettled_count=0,
            median_settle_seconds=None,
            max_settle_seconds=None,
        )

    restart_indices = detect_restart_gaps(times, gap_threshold)
    if not restart_indices:
        return SettlingReport(
            status=NO_RESTART,
            target_cadence=target_cadence,
            events=[],
            total_restarts=0,
            settled_count=0,
            unsettled_count=0,
            median_settle_seconds=None,
            max_settle_seconds=None,
        )

    events: list[SettlingEvent] = []
    for idx in restart_indices:
        ev = measure_settling(times, idx, target_cadence, tolerance, settle_window)
        events.append(ev)

    settled_count = sum(1 for e in events if e.settled)
    unsettled_count = len(events) - settled_count

    settled_seconds = [e.seconds_to_settle for e in events if e.settled]
    median_s: Optional[float] = None
    max_s: Optional[float] = None
    if settled_seconds:
        settled_seconds.sort()
        n = len(settled_seconds)
        if n % 2 == 1:
            median_s = settled_seconds[n // 2]
        else:
            median_s = (settled_seconds[n // 2 - 1] + settled_seconds[n // 2]) / 2
        max_s = max(settled_seconds)

    overall_status = SETTLED if unsettled_count == 0 else UNSETTLED

    return SettlingReport(
        status=overall_status,
        target_cadence=target_cadence,
        events=events,
        total_restarts=len(events),
        settled_count=settled_count,
        unsettled_count=unsettled_count,
        median_settle_seconds=median_s,
        max_settle_seconds=max_s,
    )


def format_human(report: SettlingReport) -> str:
    """Produce a human-readable summary."""
    lines = [
        f"restart settling monitor",
        f"  target cadence : {report.target_cadence}s",
        f"  status         : {report.status}",
        f"  restarts found : {report.total_restarts}",
        f"  settled        : {report.settled_count}",
        f"  unsettled      : {report.unsettled_count}",
    ]
    if report.median_settle_seconds is not None:
        lines.append(f"  median settle  : {report.median_settle_seconds}s")
    if report.max_settle_seconds is not None:
        lines.append(f"  max settle     : {report.max_settle_seconds}s")

    for i, ev in enumerate(report.events):
        lines.append("")
        lines.append(f"  restart #{i + 1}")
        lines.append(f"    gap           : {ev.gap_seconds:.0f}s")
        lines.append(f"    ended at      : {ev.gap_end_iso}")
        lines.append(f"    strokes       : {ev.strokes_to_settle}")
        lines.append(f"    seconds       : {ev.seconds_to_settle}")
        lines.append(f"    settled       : {'yes' if ev.settled else 'no'}")
        if ev.post_gap_intervals:
            preview = ev.post_gap_intervals[:10]
            lines.append(f"    intervals     : {preview}")

    return "\n".join(lines)


# Exit-code mapping
_EXIT = {SETTLED: 0, UNSETTLED: 1, NO_DATA: 2, NO_RESTART: 3}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--strokes", type=Path, default=DEFAULT_STROKES)
    p.add_argument("--cadence", type=float, default=15.0, help="expected seconds per stroke")
    p.add_argument("--gap-threshold", type=float, default=None,
                   help="seconds of silence to count as restart (default: 5× cadence)")
    p.add_argument("--tolerance", type=float, default=0.3,
                   help="fraction of cadence for settled band (default: 0.3)")
    p.add_argument("--settle-window", type=int, default=30,
                   help="max post-restart intervals to examine (default: 30)")
    p.add_argument("--tail", type=int, default=0,
                   help="only scan last N strokes (0 = all)")
    p.add_argument("--json", action="store_true", dest="json_out")
    args = p.parse_args(argv)

    gap_threshold = args.gap_threshold or args.cadence * 5

    times = parse_stroke_times(args.strokes)
    if args.tail and len(times) > args.tail:
        times = times[-args.tail:]

    report = analyze(times, args.cadence, gap_threshold, args.tolerance, args.settle_window)

    if args.json_out:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(format_human(report))

    return _EXIT.get(report.status, 0)


if __name__ == "__main__":
    sys.exit(main())
