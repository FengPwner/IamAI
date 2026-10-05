"""Monitor uncommitted file backlog and detect growing trends.

The batch committer runs every 10 minutes, but if it falls behind
(crashes, slow git operations, lock contention), files pile up.
A growing backlog is an early warning sign — by the time healthcheck
fires at 20 files, you've already lost data.

This module records snapshots of the uncommitted file count over time
and provides trend analysis: is the backlog growing, stable, or shrinking?

Usage pattern:
    monitor = BacklogMonitor("data/backlog.jsonl")
    monitor.record(count=12)
    trend = monitor.trend()  # "growing", "stable", "shrinking"
    if trend == "growing" and monitor.current() > 15:
        alert("backlog is growing and exceeds threshold")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BacklogMonitor:
    """Track uncommitted file counts and detect trends."""

    def __init__(self, filepath: str | Path) -> None:
        """Initialize the monitor.

        Args:
            filepath: path to the JSONL log file for backlog snapshots
        """
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def record(self, count: int, tag: str = "") -> dict[str, Any]:
        """Record a backlog snapshot.

        Args:
            count: number of uncommitted files at this moment
            tag: optional annotation (e.g., "post-restart", "before-batch")

        Returns:
            The snapshot dict that was written
        """
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": count,
            "tag": tag,
        }

        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

        return snapshot

    def load(self, limit: int = 0) -> list[dict[str, Any]]:
        """Load backlog snapshots, oldest first.

        Args:
            limit: if > 0, return only the last N snapshots

        Returns:
            List of snapshot dicts
        """
        if not self.filepath.exists():
            return []

        snapshots = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    snapshots.append(json.loads(line))

        if limit > 0 and len(snapshots) > limit:
            snapshots = snapshots[-limit:]

        return snapshots

    def current(self) -> int:
        """Get the most recent backlog count.

        Returns:
            The count from the latest snapshot, or 0 if no snapshots exist
        """
        snapshots = self.load(limit=1)
        if not snapshots:
            return 0
        return snapshots[0]["count"]

    def trend(self, window: int = 5) -> str:
        """Analyze backlog trend over recent snapshots.

        Compares the average of the last `window` snapshots to the
        average of the `window` snapshots before that.

        Args:
            window: number of recent snapshots to compare

        Returns:
            "growing" if recent average > earlier average by >20%,
            "shrinking" if recent average < earlier average by >20%,
            "stable" otherwise,
            "insufficient_data" if fewer than 2*window snapshots exist
        """
        snapshots = self.load()
        if len(snapshots) < 2 * window:
            return "insufficient_data"

        recent = snapshots[-window:]
        earlier = snapshots[-(2 * window):-window]

        recent_avg = sum(s["count"] for s in recent) / len(recent)
        earlier_avg = sum(s["count"] for s in earlier) / len(earlier)

        if earlier_avg == 0:
            return "stable" if recent_avg == 0 else "growing"

        change_ratio = (recent_avg - earlier_avg) / earlier_avg

        if change_ratio > 0.2:
            return "growing"
        elif change_ratio < -0.2:
            return "shrinking"
        else:
            return "stable"

    def peak(self, window: int = 0) -> int:
        """Get the peak backlog count.

        Args:
            window: if > 0, only consider the last N snapshots;
                    if 0, consider all snapshots

        Returns:
            The maximum count value, or 0 if no snapshots exist
        """
        snapshots = self.load(limit=window) if window > 0 else self.load()
        if not snapshots:
            return 0
        return max(s["count"] for s in snapshots)

    def summary(self) -> dict[str, Any]:
        """Generate a summary of backlog health.

        Returns:
            Dict with current count, trend, peak, and sample count
        """
        snapshots = self.load()
        return {
            "current": self.current(),
            "trend": self.trend(),
            "peak": self.peak(),
            "sample_count": len(snapshots),
        }
