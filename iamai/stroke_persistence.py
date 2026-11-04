"""stroke_persistence — measure continuous stroke production uptime.

While cadence monitors check *rate* and stall detectors give a binary
healthy/stalled verdict, this module answers a different question:
*how long has the writer been running continuously without a gap
exceeding threshold?*

This is analogous to "uptime" for a server — it tells you how long
the current streak of productive output has lasted.

Public API::

    from iamai.stroke_persistence import (
        StrokePersistence,
        current_streak,
        streak_report,
    )

    sp = StrokePersistence(strokes_path)
    streak = sp.current_streak(threshold_seconds=120)
    # {"duration": 3600, "strokes": 240, "started_at": "2026-11-05T04:01:00+00:00",
    #  "status": "active"}

    print(streak_report(strokes_path, threshold_seconds=120))
    # "active streak: 1h 0m (240 strokes since 04:01 UTC)"

Threshold model:

==============  ===========================================================
threshold       meaning
==============  ===========================================================
< 2x cadence    strict — any minor pause breaks the streak
2–10x cadence   moderate — tolerates brief hiccups
> 10x cadence   loose — only major stalls break the streak
==============  ===========================================================

Default threshold is 120s (8x the 15s cadence) — balances sensitivity
against noise from transient pauses.

Status values:

===========  ===========================================================
status       meaning
===========  ===========================================================
active       streak is ongoing (last stroke within threshold)
broken       streak ended — gap exceeded threshold
dormant      no strokes yet or insufficient data
===========  ===========================================================
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional


DEFAULT_THRESHOLD: float = 120.0  # seconds


@dataclass
class Streak:
    """A continuous run of strokes without a gap exceeding threshold."""
    duration: float          # seconds from first to last stroke in streak
    stroke_count: int        # number of strokes in this streak
    started_at: Optional[str]  # ISO timestamp of first stroke
    ended_at: Optional[str]    # ISO timestamp of last stroke (None if active)
    status: str              # "active", "broken", "dormant"
    max_gap: float           # largest gap within the streak
    avg_gap: float           # average gap within the streak


class StrokePersistence:
    """Measure continuous stroke production uptime."""

    def __init__(self, strokes_path: Path):
        """Initialize with path to strokes.jsonl.

        Args:
            strokes_path: Path to the strokes JSONL file.
        """
        self.strokes_path = strokes_path
        self._strokes: Optional[List[dict]] = None

    def _load_strokes(self) -> List[dict]:
        """Load and parse strokes from JSONL file."""
        if self._strokes is not None:
            return self._strokes

        if not self.strokes_path.exists():
            self._strokes = []
            return self._strokes

        strokes = []
        for line in self.strokes_path.read_text().strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
                # Normalize timestamp to epoch seconds
                ts = self._parse_ts(stroke)
                if ts is not None:
                    stroke["_epoch"] = ts
                    strokes.append(stroke)
            except (json.JSONDecodeError, KeyError):
                continue

        self._strokes = strokes
        return self._strokes

    @staticmethod
    def _parse_ts(stroke: dict) -> Optional[float]:
        """Extract epoch timestamp from a stroke record."""
        # Try "at" field (ISO format)
        at = stroke.get("at")
        if at and isinstance(at, str):
            try:
                dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, TypeError):
                pass

        # Try "ts" field (epoch seconds)
        ts = stroke.get("ts")
        if ts and isinstance(ts, (int, float)):
            return float(ts)

        return None

    def current_streak(
        self,
        threshold_seconds: float = DEFAULT_THRESHOLD,
        now: Optional[float] = None,
    ) -> Streak:
        """Calculate the current (most recent) streak.

        A streak is a sequence of consecutive strokes where no gap
        between adjacent strokes exceeds threshold_seconds.

        Args:
            threshold_seconds: Maximum gap (seconds) before a streak
                is considered broken. Default 120s.
            now: Override current time (epoch seconds). Defaults to
                time.time().

        Returns:
            Streak dataclass with duration, count, status, etc.
        """
        strokes = self._load_strokes()
        current_time = now if now is not None else time.time()

        if not strokes:
            return Streak(
                duration=0.0,
                stroke_count=0,
                started_at=None,
                ended_at=None,
                status="dormant",
                max_gap=0.0,
                avg_gap=0.0,
            )

        # Walk backwards from the most recent stroke to find streak start
        epochs = [s["_epoch"] for s in strokes]

        # Check if the most recent stroke is within threshold of now
        last_epoch = epochs[-1]
        gap_to_now = current_time - last_epoch

        if gap_to_now > threshold_seconds:
            # The current streak is broken — find the last active streak
            return self._find_last_streak(epochs, strokes, threshold_seconds)

        # Active streak: walk backwards to find where it started
        streak_start_idx = len(epochs) - 1
        for i in range(len(epochs) - 1, 0, -1):
            gap = epochs[i] - epochs[i - 1]
            if gap > threshold_seconds:
                break
            streak_start_idx = i - 1

        streak_epochs = epochs[streak_start_idx:]
        streak_strokes = strokes[streak_start_idx:]

        duration = streak_epochs[-1] - streak_epochs[0]
        gaps = [
            streak_epochs[i + 1] - streak_epochs[i]
            for i in range(len(streak_epochs) - 1)
        ]

        started_at = streak_strokes[0].get("at", streak_strokes[0].get("ts"))
        ended_at = streak_strokes[-1].get("at", streak_strokes[-1].get("ts"))

        return Streak(
            duration=duration,
            stroke_count=len(streak_strokes),
            started_at=str(started_at) if started_at else None,
            ended_at=str(ended_at) if ended_at else None,
            status="active",
            max_gap=max(gaps) if gaps else 0.0,
            avg_gap=sum(gaps) / len(gaps) if gaps else 0.0,
        )

    def _find_last_streak(
        self,
        epochs: List[float],
        strokes: List[dict],
        threshold_seconds: float,
    ) -> Streak:
        """Find the last completed streak (before the current gap)."""
        if len(epochs) < 2:
            return Streak(
                duration=0.0,
                stroke_count=len(epochs),
                started_at=str(strokes[0].get("at", strokes[0].get("ts"))) if strokes else None,
                ended_at=str(strokes[-1].get("at", strokes[-1].get("ts"))) if strokes else None,
                status="dormant" if len(epochs) < 1 else "broken",
                max_gap=0.0,
                avg_gap=0.0,
            )

        # Find the end of the last streak before the current gap
        # Walk backwards to find where a gap > threshold exists
        streak_end_idx = len(epochs) - 1
        streak_start_idx = streak_end_idx

        for i in range(len(epochs) - 1, 0, -1):
            gap = epochs[i] - epochs[i - 1]
            if gap > threshold_seconds:
                # This gap breaks the streak
                # The streak we want is BEFORE this gap
                streak_end_idx = i - 1
                streak_start_idx = i - 1
                break

        # Now walk backwards from streak_end_idx to find streak start
        for i in range(streak_end_idx, 0, -1):
            gap = epochs[i] - epochs[i - 1]
            if gap > threshold_seconds:
                break
            streak_start_idx = i - 1

        streak_epochs = epochs[streak_start_idx:streak_end_idx + 1]
        streak_strokes = strokes[streak_start_idx:streak_end_idx + 1]

        if len(streak_epochs) == 0:
            return Streak(
                duration=0.0,
                stroke_count=0,
                started_at=None,
                ended_at=None,
                status="broken",
                max_gap=0.0,
                avg_gap=0.0,
            )

        duration = streak_epochs[-1] - streak_epochs[0]
        gaps = [
            streak_epochs[i + 1] - streak_epochs[i]
            for i in range(len(streak_epochs) - 1)
        ]

        started_at = streak_strokes[0].get("at", streak_strokes[0].get("ts"))
        ended_at = streak_strokes[-1].get("at", streak_strokes[-1].get("ts"))

        return Streak(
            duration=duration,
            stroke_count=len(streak_strokes),
            started_at=str(started_at) if started_at else None,
            ended_at=str(ended_at) if ended_at else None,
            status="broken",
            max_gap=max(gaps) if gaps else 0.0,
            avg_gap=sum(gaps) / len(gaps) if gaps else 0.0,
        )

    def all_streaks(
        self,
        threshold_seconds: float = DEFAULT_THRESHOLD,
    ) -> List[Streak]:
        """Find all streaks in the stroke history.

        Returns a list of Streak objects, most recent first.
        """
        strokes = self._load_strokes()
        if not strokes:
            return []

        epochs = [s["_epoch"] for s in strokes]

        # Split into streaks by finding gaps > threshold
        streaks: List[Streak] = []
        start_idx = 0

        for i in range(1, len(epochs)):
            gap = epochs[i] - epochs[i - 1]
            if gap > threshold_seconds:
                # End current streak, start new one
                streak_epochs = epochs[start_idx:i]
                streak_strokes = strokes[start_idx:i]
                gaps = [
                    streak_epochs[j + 1] - streak_epochs[j]
                    for j in range(len(streak_epochs) - 1)
                ]
                started_at = streak_strokes[0].get("at", streak_strokes[0].get("ts"))
                ended_at = streak_strokes[-1].get("at", streak_strokes[-1].get("ts"))

                streaks.append(Streak(
                    duration=streak_epochs[-1] - streak_epochs[0],
                    stroke_count=len(streak_strokes),
                    started_at=str(started_at) if started_at else None,
                    ended_at=str(ended_at) if ended_at else None,
                    status="broken",
                    max_gap=max(gaps) if gaps else 0.0,
                    avg_gap=sum(gaps) / len(gaps) if gaps else 0.0,
                ))
                start_idx = i

        # Final streak (may be active)
        streak_epochs = epochs[start_idx:]
        streak_strokes = strokes[start_idx:]
        gaps = [
            streak_epochs[j + 1] - streak_epochs[j]
            for j in range(len(streak_epochs) - 1)
        ]
        started_at = streak_strokes[0].get("at", streak_strokes[0].get("ts"))
        ended_at = streak_strokes[-1].get("at", streak_strokes[-1].get("ts"))

        streaks.append(Streak(
            duration=streak_epochs[-1] - streak_epochs[0],
            stroke_count=len(streak_strokes),
            started_at=str(started_at) if started_at else None,
            ended_at=str(ended_at) if ended_at else None,
            status="active",
            max_gap=max(gaps) if gaps else 0.0,
            avg_gap=sum(gaps) / len(gaps) if gaps else 0.0,
        ))

        # Return most recent first
        streaks.reverse()
        return streaks

    def classify(self, threshold_seconds: float = DEFAULT_THRESHOLD) -> str:
        """Quick classification of current persistence state.

        Returns one of: "active", "broken", "dormant".
        """
        return self.current_streak(threshold_seconds).status


def streak_report(
    strokes_path: Path,
    threshold_seconds: float = DEFAULT_THRESHOLD,
    now: Optional[float] = None,
) -> str:
    """Human-readable streak report.

    Args:
        strokes_path: Path to strokes.jsonl
        threshold_seconds: Gap threshold in seconds
        now: Override current time

    Returns:
        Formatted string like "active streak: 1h 0m (240 strokes since 04:01 UTC)"
    """
    sp = StrokePersistence(strokes_path)
    streak = sp.current_streak(threshold_seconds, now=now)

    if streak.status == "dormant":
        return "dormant: no strokes recorded"

    hours = int(streak.duration // 3600)
    minutes = int((streak.duration % 3600) // 60)

    if streak.status == "active":
        since = streak.started_at or "unknown"
        return (
            f"active streak: {hours}h {minutes}m "
            f"({streak.stroke_count} strokes since {since})"
        )
    else:
        ended = streak.ended_at or "unknown"
        return (
            f"last streak: {hours}h {minutes}m "
            f"({streak.stroke_count} strokes, ended {ended})"
        )


def main() -> int:
    """CLI entry point."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Measure continuous stroke production uptime"
    )
    ap.add_argument(
        "--json", action="store_true",
        help="JSON output instead of human-readable"
    )
    ap.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Gap threshold in seconds (default {DEFAULT_THRESHOLD})"
    )
    ap.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parent.parent,
        help="Repository root path"
    )
    ap.add_argument(
        "--all", action="store_true",
        help="Show all historical streaks"
    )
    args = ap.parse_args()

    strokes_path = args.repo / "data" / "strokes.jsonl"

    if args.all:
        sp = StrokePersistence(strokes_path)
        streaks = sp.all_streaks(args.threshold)

        if args.json:
            import dataclasses
            print(json.dumps([dataclasses.asdict(s) for s in streaks[:20]], indent=2))
        else:
            if not streaks:
                print("No streaks found.")
                return 0
            print(f"{'Status':<10} {'Duration':>12} {'Strokes':>8} {'Max Gap':>10} {'Started':>24}")
            print("-" * 70)
            for s in streaks[:20]:
                dur = f"{int(s.duration // 3600)}h{int((s.duration % 3600) // 60)}m"
                print(
                    f"{s.status:<10} {dur:>12} {s.stroke_count:>8} "
                    f"{s.max_gap:>9.0f}s {s.started_at or 'N/A':>24}"
                )
    else:
        if args.json:
            import dataclasses
            sp = StrokePersistence(strokes_path)
            streak = sp.current_streak(args.threshold)
            print(json.dumps(dataclasses.asdict(streak), indent=2))
        else:
            print(streak_report(strokes_path, args.threshold))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
