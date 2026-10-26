"""process_continuity_monitor — detect and record process lifecycle gaps.

when a container recycles, the writer and batch processes die silently.
the gap between "last stroke" and "next stroke after restart" can stretch
to minutes or hours. existing modules detect stalls after the fact, but
none record the *lifecycle* — the exact moments a process was born, died,
and was reborn, paired with the data loss that gap implies.

this module fills that gap by:
  1. recording process start/stop events to JSONL
  2. computing continuity scores: what fraction of expected strokes
     were actually produced during a given window
  3. detecting container recycle patterns (process died without graceful
     shutdown, restarted within seconds of death)
  4. producing a continuity report that a caretaker can use to decide
     whether to backfill, alert, or just note the gap

design choices:
  - events are append-only JSONL (survives container recycles if on
     persistent volume)
  - no external dependencies beyond stdlib
  - the continuity score is intentionally simple: actual strokes /
     expected strokes in a window. no weighting, no decay. complexity
     here would obscure the signal.

usage:
    from iamai.process_continuity_monitor import ProcessContinuityMonitor

    monitor = ProcessContinuityMonitor(events_path="data/process_events.jsonl")
    monitor.record_start(pid=1234, process_type="writer")
    monitor.record_stop(pid=1234, process_type="writer", reason="container_recycle")
    report = monitor.continuity_report(window_hours=24, expected_cadence_sec=15)
    print(report.score)          # 0.0 to 1.0
    print(report.gap_count)      # number of detected gaps
    print(report.recycle_events) # count of container recycle detections
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ProcessEvent:
    """a single lifecycle event for a process."""

    timestamp: str  # ISO 8601
    event_type: str  # "start" | "stop" | "heartbeat"
    process_type: str  # "writer" | "batch"
    pid: int
    reason: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "process_type": self.process_type,
            "pid": self.pid,
        }
        if self.reason:
            d["reason"] = self.reason
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class ContinuityReport:
    """summary of process continuity over a time window."""

    window_start: str
    window_end: str
    window_hours: float
    expected_strokes: int
    actual_strokes: int
    score: float  # actual / expected, clamped to [0, 1]
    gap_count: int
    gap_durations_sec: list[float] = field(default_factory=list)
    recycle_events: int = 0
    unclean_shutdowns: int = 0
    longest_gap_sec: float = 0.0

    @property
    def health_label(self) -> str:
        if self.score >= 0.95:
            return "excellent"
        if self.score >= 0.80:
            return "good"
        if self.score >= 0.50:
            return "degraded"
        if self.score >= 0.20:
            return "poor"
        return "critical"


@dataclass
class Gap:
    """a detected gap in process activity."""

    start: str  # ISO 8601
    end: str  # ISO 8601
    duration_sec: float
    cause: str  # "container_recycle" | "unknown" | "graceful_stop"
    strokes_lost: int  # estimated strokes lost during this gap


class ProcessContinuityMonitor:
    """track process lifecycle events and compute continuity metrics."""

    def __init__(
        self,
        events_path: str | Path = "data/process_events.jsonl",
        stroke_cadence_sec: int = 15,
    ):
        self.events_path = Path(events_path)
        self.stroke_cadence_sec = stroke_cadence_sec

    # ------------------------------------------------------------------
    # event recording
    # ------------------------------------------------------------------

    def record_event(
        self,
        event_type: str,
        process_type: str,
        pid: int,
        reason: str = "",
        metadata: dict | None = None,
        timestamp: str | None = None,
    ) -> ProcessEvent:
        """record a lifecycle event and append to JSONL."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        event = ProcessEvent(
            timestamp=ts,
            event_type=event_type,
            process_type=process_type,
            pid=pid,
            reason=reason,
            metadata=metadata or {},
        )
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.events_path, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
        return event

    def record_start(
        self, pid: int, process_type: str = "writer", timestamp: str | None = None
    ) -> ProcessEvent:
        return self.record_event("start", process_type, pid, timestamp=timestamp)

    def record_stop(
        self,
        pid: int,
        process_type: str = "writer",
        reason: str = "",
        timestamp: str | None = None,
    ) -> ProcessEvent:
        return self.record_event(
            "stop", process_type, pid, reason=reason, timestamp=timestamp
        )

    def record_heartbeat(
        self, pid: int, process_type: str = "writer", timestamp: str | None = None
    ) -> ProcessEvent:
        return self.record_event(
            "heartbeat", process_type, pid, timestamp=timestamp
        )

    # ------------------------------------------------------------------
    # event loading
    # ------------------------------------------------------------------

    def load_events(self) -> list[ProcessEvent]:
        """load all events from the JSONL file."""
        if not self.events_path.exists():
            return []
        events = []
        for line in self.events_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                events.append(
                    ProcessEvent(
                        timestamp=d["timestamp"],
                        event_type=d["event_type"],
                        process_type=d["process_type"],
                        pid=d["pid"],
                        reason=d.get("reason", ""),
                        metadata=d.get("metadata", {}),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return events

    def load_events_in_window(
        self, window_hours: float = 24, now: datetime | None = None
    ) -> list[ProcessEvent]:
        """load events within a time window ending at `now`."""
        all_events = self.load_events()
        cutoff = now or datetime.now(timezone.utc)
        from datetime import timedelta

        window_start = cutoff - timedelta(hours=window_hours)
        result = []
        for e in all_events:
            try:
                ts = datetime.fromisoformat(e.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= window_start:
                    result.append(e)
            except (ValueError, TypeError):
                continue
        return result

    # ------------------------------------------------------------------
    # gap detection
    # ------------------------------------------------------------------

    def detect_gaps(
        self,
        events: list[ProcessEvent] | None = None,
        max_gap_sec: float = 60.0,
    ) -> list[Gap]:
        """detect gaps between consecutive start events.

        a gap is any interval between a stop (or last heartbeat) and the
        next start that exceeds max_gap_sec. gaps shorter than that are
        considered normal restarts.
        """
        if events is None:
            events = self.load_events()

        if len(events) < 2:
            return []

        # sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        gaps = []
        last_stop: ProcessEvent | None = None

        for event in sorted_events:
            if event.event_type == "stop":
                last_stop = event
            elif event.event_type == "start" and last_stop is not None:
                try:
                    stop_ts = datetime.fromisoformat(last_stop.timestamp)
                    start_ts = datetime.fromisoformat(event.timestamp)
                    if stop_ts.tzinfo is None:
                        stop_ts = stop_ts.replace(tzinfo=timezone.utc)
                    if start_ts.tzinfo is None:
                        start_ts = start_ts.replace(tzinfo=timezone.utc)
                    duration = (start_ts - stop_ts).total_seconds()
                except (ValueError, TypeError):
                    continue

                if duration > max_gap_sec:
                    cause = self._classify_gap(last_stop, duration)
                    strokes_lost = max(0, int(duration / self.stroke_cadence_sec))
                    gaps.append(
                        Gap(
                            start=last_stop.timestamp,
                            end=event.timestamp,
                            duration_sec=duration,
                            cause=cause,
                            strokes_lost=strokes_lost,
                        )
                    )
                last_stop = None

        return gaps

    def _classify_gap(self, stop_event: ProcessEvent, duration: float) -> str:
        """classify a gap based on the stop event's reason."""
        reason = stop_event.reason.lower()
        if "recycle" in reason or "container" in reason:
            return "container_recycle"
        if "graceful" in reason or "shutdown" in reason:
            return "graceful_stop"
        # if no stop event reason, and the gap is short, likely a recycle
        if duration < 120:
            return "container_recycle"
        return "unknown"

    # ------------------------------------------------------------------
    # continuity report
    # ------------------------------------------------------------------

    def continuity_report(
        self,
        window_hours: float = 24,
        expected_cadence_sec: int | None = None,
        now: datetime | None = None,
    ) -> ContinuityReport:
        """compute continuity metrics for a time window.

        expected_cadence_sec defaults to self.stroke_cadence_sec.
        the score is actual_strokes / expected_strokes, clamped to [0, 1].
        """
        cadence = expected_cadence_sec or self.stroke_cadence_sec
        window_seconds = window_hours * 3600
        expected = max(1, int(window_seconds / cadence))

        events = self.load_events_in_window(window_hours=window_hours, now=now)
        gaps = self.detect_gaps(events)

        total_gap_sec = sum(g.duration_sec for g in gaps)
        recycle_count = sum(1 for g in gaps if g.cause == "container_recycle")
        unclean = sum(
            1
            for e in events
            if e.event_type == "stop" and e.reason == ""
        )

        # actual strokes: expected minus lost
        actual = max(0, expected - int(total_gap_sec / cadence))
        score = min(1.0, max(0.0, actual / expected))

        window_start_dt = (now or datetime.now(timezone.utc))
        from datetime import timedelta

        window_start_dt = window_start_dt - timedelta(hours=window_hours)

        longest_gap = max((g.duration_sec for g in gaps), default=0.0)

        return ContinuityReport(
            window_start=window_start_dt.isoformat(),
            window_end=(now or datetime.now(timezone.utc)).isoformat(),
            window_hours=window_hours,
            expected_strokes=expected,
            actual_strokes=actual,
            score=score,
            gap_count=len(gaps),
            gap_durations_sec=[g.duration_sec for g in gaps],
            recycle_events=recycle_count,
            unclean_shutdowns=unclean,
            longest_gap_sec=longest_gap,
        )

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------

    def is_likely_recycled(self, stop_event: ProcessEvent, next_start: ProcessEvent) -> bool:
        """heuristic: if stop has no reason and restart happened within 60s,
        it's probably a container recycle."""
        try:
            stop_ts = datetime.fromisoformat(stop_event.timestamp)
            start_ts = datetime.fromisoformat(next_start.timestamp)
            if stop_ts.tzinfo is None:
                stop_ts = stop_ts.replace(tzinfo=timezone.utc)
            if start_ts.tzinfo is None:
                start_ts = start_ts.replace(tzinfo=timezone.utc)
            delta = abs((start_ts - stop_ts).total_seconds())
        except (ValueError, TypeError):
            return False

        return delta < 60 and stop_event.reason == ""

    def summarize(self) -> str:
        """one-line human summary of current continuity state."""
        report = self.continuity_report(window_hours=24)
        return (
            f"24h continuity: {report.health_label} ({report.score:.0%}), "
            f"{report.gap_count} gaps, "
            f"{report.recycle_events} recycles, "
            f"longest gap {report.longest_gap_sec:.0f}s"
        )


if __name__ == "__main__":
    import sys

    monitor = ProcessContinuityMonitor()
    if "--record-start" in sys.argv:
        pid = int(sys.argv[sys.argv.index("--record-start") + 1]) if "--record-start" in sys.argv else 0
        monitor.record_start(pid=pid, process_type="writer")
        print(f"recorded start for pid {pid}")
    elif "--record-stop" in sys.argv:
        pid = int(sys.argv[sys.argv.index("--record-stop") + 1]) if "--record-stop" in sys.argv else 0
        reason = sys.argv[sys.argv.index("--reason") + 1] if "--reason" in sys.argv else ""
        monitor.record_stop(pid=pid, process_type="writer", reason=reason)
        print(f"recorded stop for pid {pid}: {reason or '(no reason)'}")
    else:
        print(monitor.summarize())
