#!/usr/bin/env python3
"""process_death_detection_latency — measure how long dead processes go unnoticed.

when the writer or batch committer dies, the caretaker only finds out
on the next scheduled check.  if checks run every 10 minutes but the
process died 30 seconds after the last check, the detection latency
is ~9.5 minutes — wasted time where no strokes are produced and no
commits are made.

this module answers:
1. how long was each process dead before being detected?
2. what is the average detection latency over the last N restarts?
3. is the latency getting better or worse?

input sources:
- tools/process_graveyard.py output (death events with timestamps)
- data/strokes.jsonl (last stroke timestamp ≈ liveness proxy)
- git log (commit timestamps as another liveness proxy)

public API
----------
- ``DeathEvent``       – one recorded process death.
- ``DetectionLatency`` – analysis result for one event.
- ``DeathDetectionReport`` – aggregated report over multiple events.
- ``measure_latency()`` – compute latency for a single event.
- ``build_report()``   – aggregate latencies into a report.

exit codes (CLI):
    0  latency within budget (< 50% of check interval)
    1  latency exceeds budget
    2  insufficient data to measure
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

DEFAULT_CHECK_INTERVAL_MIN = 10  # caretaker checks every 10 minutes
LATENCY_BUDGET_RATIO = 0.5      # healthy if latency < 50% of interval

# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeathEvent:
    """one recorded process death.

    Attributes
    ----------
    process : str
        process name (e.g. "writer", "batch").
    pid : int
        PID that died.
    died_at : datetime
        estimated time of death (last known output or heartbeat).
    detected_at : datetime
        time the caretaker discovered the process was dead.
    restart_at : Optional[datetime]
        time the replacement process was started (None if not yet restarted).
    """

    process: str
    pid: int
    died_at: datetime
    detected_at: datetime
    restart_at: Optional[datetime] = None


@dataclass(frozen=True)
class DetectionLatency:
    """latency measurement for one death event.

    Attributes
    ----------
    event : DeathEvent
        the source event.
    detection_gap_sec : float
        seconds between death and detection.
    restart_gap_sec : Optional[float]
        seconds between death and restart (None if not restarted).
    total_downtime_sec : Optional[float]
        seconds between death and first output from replacement.
    """

    event: DeathEvent
    detection_gap_sec: float
    restart_gap_sec: Optional[float] = None
    total_downtime_sec: Optional[float] = None

    def within_budget(self, check_interval_min: float = DEFAULT_CHECK_INTERVAL_MIN) -> bool:
        """is the detection latency within the healthy budget?"""
        budget_sec = check_interval_min * 60 * LATENCY_BUDGET_RATIO
        return self.detection_gap_sec <= budget_sec

    def efficiency(self, check_interval_min: float = DEFAULT_CHECK_INTERVAL_MIN) -> float:
        """detection efficiency: 1.0 = instant, 0.0 = full interval wasted.

        clamped to [0, 1].
        """
        interval_sec = check_interval_min * 60
        if interval_sec <= 0:
            return 0.0
        ratio = self.detection_gap_sec / interval_sec
        return max(0.0, min(1.0, 1.0 - ratio))


@dataclass
class DeathDetectionReport:
    """aggregated report over multiple death events.

    Attributes
    ----------
    latencies : list of DetectionLatency
    check_interval_min : float
        the caretaker check interval used for budget calculations.
    """

    latencies: List[DetectionLatency]
    check_interval_min: float = DEFAULT_CHECK_INTERVAL_MIN

    @property
    def count(self) -> int:
        return len(self.latencies)

    @property
    def mean_detection_sec(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(l.detection_gap_sec for l in self.latencies) / len(self.latencies)

    @property
    def max_detection_sec(self) -> float:
        if not self.latencies:
            return 0.0
        return max(l.detection_gap_sec for l in self.latencies)

    @property
    def mean_efficiency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(l.efficiency(self.check_interval_min) for l in self.latencies) / len(self.latencies)

    @property
    def within_budget_count(self) -> int:
        return sum(1 for l in self.latencies if l.within_budget(self.check_interval_min))

    @property
    def budget_compliance(self) -> float:
        """fraction of events within budget. 1.0 = all within budget."""
        if not self.latencies:
            return 1.0
        return self.within_budget_count / len(self.latencies)

    def trend(self) -> str:
        """is detection latency improving, steady, or worsening?

        compares the first half of events to the second half.
        returns 'improving', 'steady', or 'worsening'.
        """
        if len(self.latencies) < 4:
            return "insufficient_data"
        mid = len(self.latencies) // 2
        first_half = sum(l.detection_gap_sec for l in self.latencies[:mid]) / mid
        second_half = sum(l.detection_gap_sec for l in self.latencies[mid:]) / (len(self.latencies) - mid)
        if second_half < first_half * 0.8:
            return "improving"
        elif second_half > first_half * 1.2:
            return "worsening"
        return "steady"

    def verdict(self) -> str:
        """overall health verdict."""
        if not self.latencies:
            return "no_data"
        if self.budget_compliance >= 0.9 and self.mean_efficiency >= 0.7:
            return "healthy"
        if self.budget_compliance >= 0.6:
            return "acceptable"
        return "degraded"

    def summary(self) -> dict:
        return {
            "count": self.count,
            "mean_detection_sec": round(self.mean_detection_sec, 1),
            "max_detection_sec": round(self.max_detection_sec, 1),
            "mean_efficiency": round(self.mean_efficiency, 3),
            "budget_compliance": round(self.budget_compliance, 3),
            "trend": self.trend(),
            "verdict": self.verdict(),
            "check_interval_min": self.check_interval_min,
        }


# ---------------------------------------------------------------------------
# core functions
# ---------------------------------------------------------------------------


def measure_latency(event: DeathEvent) -> DetectionLatency:
    """compute latency metrics for a single death event."""
    detection_gap = (event.detected_at - event.died_at).total_seconds()
    restart_gap = None
    if event.restart_at is not None:
        restart_gap = (event.restart_at - event.died_at).total_seconds()
    return DetectionLatency(
        event=event,
        detection_gap_sec=max(0.0, detection_gap),
        restart_gap_sec=max(0.0, restart_gap) if restart_gap is not None else None,
        total_downtime_sec=max(0.0, restart_gap) if restart_gap is not None else None,
    )


def build_report(
    events: Sequence[DeathEvent],
    check_interval_min: float = DEFAULT_CHECK_INTERVAL_MIN,
) -> DeathDetectionReport:
    """build an aggregated report from multiple death events."""
    latencies = [measure_latency(e) for e in events]
    return DeathDetectionReport(
        latencies=latencies,
        check_interval_min=check_interval_min,
    )


def report_to_text(report: DeathDetectionReport) -> str:
    """human-readable one-liner summary."""
    if not report.latencies:
        return "death detection: no events recorded"
    s = report.summary()
    return (
        f"death detection: {s['count']} events, "
        f"mean={s['mean_detection_sec']:.0f}s, "
        f"max={s['max_detection_sec']:.0f}s, "
        f"efficiency={s['mean_efficiency']:.1%}, "
        f"compliance={s['budget_compliance']:.0%}, "
        f"trend={s['trend']}, "
        f"verdict={s['verdict']}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_events_from_jsonl(path: Path) -> List[DeathEvent]:
    """parse death events from a JSONL file.

    each line: {"process": "writer", "pid": 1234,
                "died_at": "...", "detected_at": "...", "restart_at": "..."}
    """
    events = []
    if not path.exists():
        return events
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        events.append(DeathEvent(
            process=d["process"],
            pid=d["pid"],
            died_at=datetime.fromisoformat(d["died_at"]),
            detected_at=datetime.fromisoformat(d["detected_at"]),
            restart_at=datetime.fromisoformat(d["restart_at"]) if d.get("restart_at") else None,
        ))
    return events


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, help="JSONL file with death events")
    parser.add_argument("--check-interval", type=float, default=DEFAULT_CHECK_INTERVAL_MIN,
                        help="caretaker check interval in minutes")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if args.events:
        events = _parse_events_from_jsonl(args.events)
    else:
        # try default location
        default = Path(__file__).resolve().parent.parent / "data" / "process_deaths.jsonl"
        events = _parse_events_from_jsonl(default)

    if not events:
        if args.json:
            print(json.dumps({"count": 0, "verdict": "no_data"}))
        else:
            print("death detection: no events recorded")
        return 2

    report = build_report(events, check_interval_min=args.check_interval)

    if args.json:
        print(json.dumps(report.summary(), indent=2))
    else:
        print(report_to_text(report))
        for lat in report.latencies:
            e = lat.event
            status = "OK" if lat.within_budget(args.check_interval) else "OVER"
            print(f"  [{status}] {e.process} pid={e.pid} "
                  f"detection={lat.detection_gap_sec:.0f}s "
                  f"restart={lat.restart_gap_sec or 'N/A'}s")

    return 0 if report.budget_compliance >= 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
