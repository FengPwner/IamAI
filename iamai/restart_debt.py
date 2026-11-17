#!/usr/bin/env python3
"""restart_debt — quantify cumulative productivity loss from restarts.

Every restart costs time: the writer is down during the gap, then
produces at reduced cadence during warmup.  *Restart debt* is the
total seconds lost to restarts over a given window — downtime plus
warmup overshoot.

Why it matters
--------------
A single restart is cheap.  But if the writer restarts every few
hours and each warmup costs 60 seconds, the debt compounds silently.
This module makes that cost visible.

Debt model
----------
For each restart event we record:

- ``downtime_s``:  seconds the writer was not running
- ``warmup_cost_s``:  cumulative overshoot during warmup (see writer_cadence_warmup)
- ``strokes_lost``:  estimated strokes that would have been produced at target cadence

Total debt = sum(downtime_s + warmup_cost_s) across all restarts.

Public API::

    from iamai.restart_debt import RestartDebtTracker

    tracker = RestartDebtTracker(target_cadence_s=15)
    tracker.record(
        downtime_s=120,
        warmup_cost_s=45.0,
    )
    report = tracker.report()
    print(report["total_debt_s"])       # 165.0
    print(report["strokes_lost"])       # 11
    print(report["debt_ratio_pct"])     # percentage of window consumed
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class RestartDebtTracker:
    """Accumulate restart debt over a rolling window.

    Parameters
    ----------
    target_cadence_s:
        Expected inter-stroke interval in seconds.  Used to estimate
        strokes lost during downtime + warmup.
    window_s:
        Rolling window in seconds.  Events older than this are
        excluded from the report.  Default 24 hours.
    """

    def __init__(
        self,
        target_cadence_s: float = 15.0,
        window_s: float = 86400.0,
    ) -> None:
        self.target_cadence_s = target_cadence_s
        self.window_s = window_s
        self._events: List[Dict[str, Any]] = []

    def record(
        self,
        downtime_s: float,
        warmup_cost_s: float = 0.0,
        ts: Optional[float] = None,
        label: str = "",
    ) -> Dict[str, Any]:
        """Record a single restart event.

        Parameters
        ----------
        downtime_s:
            Seconds the writer was not running (from crash/stop to restart).
        warmup_cost_s:
            Cumulative overshoot seconds during post-restart warmup.
        ts:
            Epoch timestamp of the restart.  Defaults to now.
        label:
            Optional label (e.g. "caretaker visit 676").

        Returns
        -------
        dict with the event details plus computed strokes_lost.
        """
        if ts is None:
            ts = time.time()
        total_cost = max(0.0, downtime_s) + max(0.0, warmup_cost_s)
        strokes_lost = int(total_cost / self.target_cadence_s) if self.target_cadence_s > 0 else 0

        event = {
            "ts": ts,
            "downtime_s": round(downtime_s, 2),
            "warmup_cost_s": round(warmup_cost_s, 2),
            "total_cost_s": round(total_cost, 2),
            "strokes_lost": strokes_lost,
            "label": label,
        }
        self._events.append(event)
        return event

    def _prune(self, now: float) -> List[Dict[str, Any]]:
        """Return events within the rolling window."""
        cutoff = now - self.window_s
        return [e for e in self._events if e["ts"] >= cutoff]

    def report(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Generate a debt report for the current window.

        Returns
        -------
        dict with keys:
            restart_count, total_debt_s, total_downtime_s,
            total_warmup_cost_s, strokes_lost, debt_ratio_pct,
            mean_debt_per_restart_s, events
        """
        if now is None:
            now = time.time()
        active = self._prune(now)

        if not active:
            return {
                "restart_count": 0,
                "total_debt_s": 0.0,
                "total_downtime_s": 0.0,
                "total_warmup_cost_s": 0.0,
                "strokes_lost": 0,
                "debt_ratio_pct": 0.0,
                "mean_debt_per_restart_s": 0.0,
                "events": [],
            }

        total_debt = sum(e["total_cost_s"] for e in active)
        total_down = sum(e["downtime_s"] for e in active)
        total_warm = sum(e["warmup_cost_s"] for e in active)
        total_lost = sum(e["strokes_lost"] for e in active)

        debt_ratio = (total_debt / self.window_s * 100) if self.window_s > 0 else 0.0
        mean_debt = total_debt / len(active) if active else 0.0

        return {
            "restart_count": len(active),
            "total_debt_s": round(total_debt, 2),
            "total_downtime_s": round(total_down, 2),
            "total_warmup_cost_s": round(total_warm, 2),
            "strokes_lost": total_lost,
            "debt_ratio_pct": round(debt_ratio, 4),
            "mean_debt_per_restart_s": round(mean_debt, 2),
            "events": active,
        }

    def trend(self, bucket_count: int = 4, now: Optional[float] = None) -> Dict[str, Any]:
        """Split the window into buckets and detect debt trend.

        Parameters
        ----------
        bucket_count:
            How many equal-sized buckets to split the window into.
        now:
            Override current time for testing.

        Returns
        -------
        dict with keys:
            buckets (list of debt totals per bucket),
            trend ("improving", "stable", "degrading", "insufficient_data")
        """
        if now is None:
            now = time.time()
        if bucket_count < 2:
            bucket_count = 2

        bucket_size = self.window_s / bucket_count
        buckets = [0.0] * bucket_count

        for e in self._events:
            age = now - e["ts"]
            if age > self.window_s or age < 0:
                continue
            idx = int(age / bucket_size)
            # idx 0 = oldest bucket, idx -1 = newest
            bucket_idx = bucket_count - 1 - idx
            if 0 <= bucket_idx < bucket_count:
                buckets[bucket_idx] += e["total_cost_s"]

        buckets = [round(b, 2) for b in buckets]

        if len(buckets) < 2 or sum(buckets) == 0:
            trend_label = "insufficient_data"
        else:
            first_half = sum(buckets[: len(buckets) // 2])
            second_half = sum(buckets[len(buckets) // 2 :])
            if second_half < first_half * 0.7:
                trend_label = "improving"
            elif second_half > first_half * 1.3:
                trend_label = "degrading"
            else:
                trend_label = "stable"

        return {
            "buckets": buckets,
            "trend": trend_label,
        }

    def clear(self) -> int:
        """Remove all events.  Returns the number cleared."""
        n = len(self._events)
        self._events.clear()
        return n
