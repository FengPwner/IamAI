"""cadence_budget — track remaining time budget in a commit cadence cycle.

Given a cadence interval (e.g. 600s) and the timestamp of the last commit,
calculate how much budget remains, whether the cycle is overdue, and project
whether the next commit will land on time based on recent stroke velocity.

written by Qwen, caretaker visit 669, 2026-11-17.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class BudgetSnapshot:
    """Point-in-time view of a cadence cycle's budget."""

    interval: float          # target cadence in seconds
    cycle_start: float       # epoch of last commit (cycle origin)
    now: float               # epoch of observation
    strokes_in_cycle: int = 0
    expected_strokes: int = 0  # how many strokes we'd expect by now

    @property
    def elapsed(self) -> float:
        return max(0.0, self.now - self.cycle_start)

    @property
    def remaining(self) -> float:
        return max(0.0, self.interval - self.elapsed)

    @property
    def fraction_used(self) -> float:
        if self.interval <= 0:
            return 1.0
        return min(1.0, self.elapsed / self.interval)

    @property
    def is_overdue(self) -> bool:
        return self.elapsed > self.interval

    @property
    def overdue_by(self) -> float:
        return max(0.0, self.elapsed - self.interval)

    @property
    def stroke_deficit(self) -> int:
        return max(0, self.expected_strokes - self.strokes_in_cycle)

    @property
    def pace_label(self) -> str:
        f = self.fraction_used
        if f < 0.25:
            return "fresh"
        elif f < 0.50:
            return "on-track"
        elif f < 0.75:
            return "mid-cycle"
        elif f < 1.0:
            return "approaching"
        else:
            return "overdue"


def budget_snapshot(
    interval: float,
    cycle_start: float,
    now: Optional[float] = None,
    strokes_in_cycle: int = 0,
    stroke_rate: float = 0.0,
) -> BudgetSnapshot:
    """Build a BudgetSnapshot.

    Args:
        interval: target cadence seconds (e.g. 600).
        cycle_start: epoch of the last commit.
        now: observation time; defaults to time.time().
        strokes_in_cycle: strokes produced since cycle_start.
        stroke_rate: strokes per second (for expected_strokes calc).
    """
    if now is None:
        now = time.time()
    elapsed = max(0.0, now - cycle_start)
    expected = int(elapsed * stroke_rate) if stroke_rate > 0 else 0
    return BudgetSnapshot(
        interval=interval,
        cycle_start=cycle_start,
        now=now,
        strokes_in_cycle=strokes_in_cycle,
        expected_strokes=expected,
    )


def project_completion(
    interval: float,
    cycle_start: float,
    stroke_times: List[float],
    now: Optional[float] = None,
) -> Tuple[float, bool]:
    """Project when the cycle will produce its next commit.

    Uses median inter-stroke gap from recent stroke_times to estimate
    whether enough strokes will accumulate before the budget expires.

    Returns:
        (eta_epoch, will_finish_on_time)
    """
    if now is None:
        now = time.time()
    if len(stroke_times) < 2:
        # not enough data; assume cycle finishes at deadline
        return cycle_start + interval, True

    gaps = sorted(
        stroke_times[i + 1] - stroke_times[i]
        for i in range(len(stroke_times) - 1)
    )
    median_gap = gaps[len(gaps) // 2]
    if median_gap <= 0:
        median_gap = 1.0

    remaining = max(0.0, (cycle_start + interval) - now)
    # rough heuristic: need ~1 more stroke to trigger commit
    strokes_needed = 1
    eta = now + median_gap * strokes_needed
    return eta, eta <= cycle_start + interval


def cycle_report(
    interval: float,
    cycle_start: float,
    now: Optional[float] = None,
    strokes_in_cycle: int = 0,
    stroke_rate: float = 0.0,
) -> str:
    """Human-readable one-liner for the current cycle budget."""
    snap = budget_snapshot(interval, cycle_start, now, strokes_in_cycle, stroke_rate)
    parts = [
        f"cycle {snap.pace_label}",
        f"{snap.elapsed:.0f}s/{snap.interval:.0f}s",
        f"({snap.fraction_used:.0%} used)",
    ]
    if snap.is_overdue:
        parts.append(f"OVERDUE by {snap.overdue_by:.0f}s")
    if snap.stroke_deficit > 0:
        parts.append(f"deficit {snap.stroke_deficit} strokes")
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# lightweight CLI: print cycle_report given interval + cycle_start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
    cycle_start = float(sys.argv[2]) if len(sys.argv) > 2 else time.time() - 300
    print(cycle_report(interval, cycle_start))
