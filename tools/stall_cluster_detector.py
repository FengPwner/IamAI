#!/usr/bin/env python3
"""stall_cluster_detector.py — detect clusters of stall-and-recovery events.

a single stall is a symptom. a cluster of stalls is a diagnosis.

this tool reads the devlog (or a strokes file) and identifies periods
where recovery events are accelerating — intervals between stalls are
shrinking. it reports:

1. **cluster_count**: how many distinct stall clusters exist in the
   lookback window.
2. **acceleration**: whether the most recent cluster has shorter
   intervals than the previous one (accelerating = bad).
3. **next_stall_forecast**: estimated time until the next stall if
   the current cadence holds, based on the trend.

usage:
    python3 tools/stall_cluster_detector.py
    python3 tools/stall_cluster_detector.py --lookback 7d
    python3 tools/stall_cluster_detector.py --json

exit codes:
    0 — no clusters or stable/declining cadence
    1 — accelerating cluster detected (escalation recommended)
    2 — error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DEVLOG = REPO / "docs" / "DEVLOG.md"

# A "stall gap" in the devlog: two consecutive devlog entries with a
# gap exceeding this threshold (seconds) are treated as a stall event.
STALL_GAP_THRESHOLD = 600  # 10 minutes — writer cadence is ~35s


@dataclass
class StallEvent:
    """A single detected stall event."""
    before_ts: datetime
    after_ts: datetime
    gap_seconds: float

    @property
    def midpoint(self) -> datetime:
        return self.before_ts + timedelta(seconds=self.gap_seconds / 2)


@dataclass
class StallCluster:
    """A group of stall events that are close together in time."""
    events: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def intervals(self) -> list:
        """Time between consecutive stall events within the cluster."""
        if len(self.events) < 2:
            return []
        return [
            (self.events[i + 1].midpoint - self.events[i].midpoint).total_seconds()
            for i in range(len(self.events) - 1)
        ]

    @property
    def median_interval(self) -> float:
        iv = sorted(self.intervals)
        if not iv:
            return 0.0
        n = len(iv)
        if n % 2 == 1:
            return iv[n // 2]
        return (iv[n // 2 - 1] + iv[n // 2]) / 2

    @property
    def is_accelerating(self) -> bool:
        """True if intervals are getting shorter (stalls more frequent)."""
        iv = self.intervals
        if len(iv) < 2:
            return False
        first_half = iv[: len(iv) // 2]
        second_half = iv[len(iv) // 2 :]
        if not first_half or not second_half:
            return False
        return sum(second_half) / len(second_half) < sum(first_half) / len(first_half)


def parse_devlog_timestamps(devlog_path: Path) -> list:
    """Extract timestamps from devlog entries."""
    if not devlog_path.exists():
        return []

    timestamps = []
    # Devlog format: - `TIMESTAMP` stroke NNNNN: ...
    pattern = re.compile(r"`(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00)`")

    text = devlog_path.read_text(encoding="utf-8")
    for m in pattern.finditer(text):
        try:
            ts = datetime.fromisoformat(m.group(1))
            timestamps.append(ts)
        except ValueError:
            continue

    return sorted(timestamps)


def detect_stall_events(timestamps: list, gap_threshold: float = STALL_GAP_THRESHOLD) -> list:
    """Find gaps in the timestamp sequence that exceed the threshold."""
    events = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if gap > gap_threshold:
            events.append(StallEvent(
                before_ts=timestamps[i - 1],
                after_ts=timestamps[i],
                gap_seconds=gap,
            ))
    return events


def cluster_stalls(events: list, max_cluster_gap: float = 86400) -> list:
    """Group stall events into clusters.

    Events within max_cluster_gap seconds of each other belong to the
    same cluster.
    """
    if not events:
        return []

    clusters = []
    current = StallCluster(events=[events[0]])

    for i in range(1, len(events)):
        gap = (events[i].midpoint - events[i - 1].midpoint).total_seconds()
        if gap <= max_cluster_gap:
            current.events.append(events[i])
        else:
            clusters.append(current)
            current = StallCluster(events=[events[i]])

    clusters.append(current)
    return clusters


def forecast_next_stall(clusters: list) -> dict:
    """Estimate when the next stall might occur based on recent trends."""
    if not clusters:
        return {"forecast": "no data", "confidence": "low"}

    latest = clusters[-1]
    if latest.count < 2:
        return {"forecast": "insufficient data", "confidence": "low"}

    median_iv = latest.median_interval
    last_event_ts = latest.events[-1].midpoint

    # If accelerating, forecast sooner than median
    if latest.is_accelerating:
        recent_iv = latest.intervals[-1] if latest.intervals else median_iv
        forecast_delta = timedelta(seconds=recent_iv)
        confidence = "medium"
    else:
        forecast_delta = timedelta(seconds=median_iv)
        confidence = "low"

    estimated_next = last_event_ts + forecast_delta
    return {
        "forecast": estimated_next.isoformat(),
        "seconds_until": max(0, (estimated_next - datetime.now(timezone.utc)).total_seconds()),
        "confidence": confidence,
        "accelerating": latest.is_accelerating,
    }


def main():
    parser = argparse.ArgumentParser(description="Detect stall clusters in devlog")
    parser.add_argument("--devlog", type=Path, default=DEFAULT_DEVLOG)
    parser.add_argument("--lookback", type=str, default="7d",
                        help="How far back to look (e.g. 7d, 24h, 48h)")
    parser.add_argument("--gap-threshold", type=float, default=STALL_GAP_THRESHOLD,
                        help="Minimum gap (seconds) to count as a stall")
    parser.add_argument("--cluster-gap", type=float, default=86400,
                        help="Maximum gap (seconds) between stalls in same cluster")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Parse lookback
    lookback_str = args.lookback
    if lookback_str.endswith("d"):
        lookback = timedelta(days=int(lookback_str[:-1]))
    elif lookback_str.endswith("h"):
        lookback = timedelta(hours=int(lookback_str[:-1]))
    else:
        lookback = timedelta(days=7)

    cutoff = datetime.now(timezone.utc) - lookback

    # Parse devlog
    timestamps = parse_devlog_timestamps(args.devlog)
    timestamps = [t for t in timestamps if t >= cutoff]

    if not timestamps:
        print("no devlog entries in lookback window")
        sys.exit(0)

    # Detect stalls
    events = detect_stall_events(timestamps, args.gap_threshold)
    clusters = cluster_stalls(events, args.cluster_gap)

    # Filter to multi-event clusters
    multi = [c for c in clusters if c.count >= 2]

    # Forecast
    forecast = forecast_next_stall(multi)

    # Report
    result = {
        "lookback": lookback_str,
        "total_entries": len(timestamps),
        "stall_events": len(events),
        "clusters": len(multi),
        "latest_cluster": {
            "count": multi[-1].count if multi else 0,
            "median_interval_s": round(multi[-1].median_interval, 1) if multi else 0,
            "accelerating": multi[-1].is_accelerating if multi else False,
        } if multi else None,
        "forecast": forecast,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"lookback: {lookback_str}")
        print(f"devlog entries: {len(timestamps)}")
        print(f"stall events: {len(events)}")
        print(f"multi-stall clusters: {len(multi)}")
        if multi:
            latest = multi[-1]
            print(f"latest cluster: {latest.count} stalls, median interval {latest.median_interval:.0f}s")
            print(f"  accelerating: {latest.is_accelerating}")
        print(f"forecast: {forecast['forecast']}")
        if "seconds_until" in forecast:
            print(f"  estimated in {forecast['seconds_until']:.0f}s")

    # Exit code based on acceleration
    if multi and multi[-1].is_accelerating:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
