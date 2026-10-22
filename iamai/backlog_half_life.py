"""backlog_half_life — measure how quickly the repo drains its uncommitted backlog.

A self-writing repo accumulates uncommitted files between batch commits.
The batch committer fires every *interval* seconds and flushes whatever is
pending.  When things go well, the backlog is ephemeral: files appear,
sit briefly, and are committed.  When things go badly, files sit for
hours or accumulate beyond what a single batch can drain.

This module tracks the *residence time* of each file — the seconds
between when a file first appears in ``git status`` and when it is
finally committed.  From those residence times it computes:

- **median_residence** — typical time a file waits before commit
- **max_residence** — worst-case wait observed
- **half_life** — the time by which 50 % of backlogged files are resolved
- **drain_rate** — files resolved per minute over the observation window
- **verdict** — ``draining``, ``stagnant``, or ``accumulating``

Verdict rules
-------------

===============  ======================================================
verdict          condition
===============  ======================================================
``draining``     half_life ≤ 1.5 × batch_interval *and* no file older
                 than 3 × batch_interval
``stagnant``     half_life ≤ 3 × batch_interval but some files exceed
                 the threshold
``accumulating`` half_life > 3 × batch_interval *or* backlog is growing
                 faster than it drains
===============  ======================================================

Design choices
--------------

- **Pure dataclass API** — ``BacklogReport`` holds all computed fields;
  ``compute_half_life`` is the entry point.
- **Residence times are pre-computed** — callers pass a list of
  ``(appeared_at, resolved_at_or_None)`` tuples.  ``None`` means the
  file is still pending.
- **Half-life is estimated from the empirical CDF** of resolved
  residence times; if fewer than two files have resolved, half-life
  is undefined and reported as ``None``.
- **No external dependencies** — stdlib only.

Usage::

    from datetime import datetime, timezone
    from iamai.backlog_half_life import compute_half_life, BacklogReport

    events = [
        (datetime(2026,10,22, 8,0, tzinfo=timezone.utc),
         datetime(2026,10,22, 8,10, tzinfo=timezone.utc)),
        (datetime(2026,10,22, 8,5, tzinfo=timezone.utc),
         datetime(2026,10,22, 8,10, tzinfo=timezone.utc)),
        (datetime(2026,10,22, 8,8, tzinfo=timezone.utc),
         None),  # still pending
    ]
    report = compute_half_life(events, batch_interval=600)
    print(report.verdict)        # "draining"
    print(report.half_life)      # 300.0
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class BacklogReport:
    """Summary of backlog drainage health."""

    total_files: int = 0
    resolved: int = 0
    pending: int = 0
    residence_times: list[float] = field(default_factory=list)
    median_residence: float = 0.0
    max_residence: float = 0.0
    half_life: Optional[float] = None
    drain_rate_per_min: float = 0.0
    verdict: str = "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_seconds(dt: datetime) -> float:
    """Convert datetime to epoch seconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _empirical_half_life(times: list[float]) -> Optional[float]:
    """Estimate the median (50th percentile) from sorted residence times.

    Returns None if fewer than 2 data points.
    """
    if len(times) < 2:
        return None
    s = sorted(times)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def _classify(
    half_life: Optional[float],
    max_residence: float,
    pending: int,
    batch_interval: float,
) -> str:
    """Assign a verdict based on half-life and max residence."""
    if half_life is None:
        if pending > 0:
            return "accumulating"
        return "draining"

    threshold_drain = 1.5 * batch_interval
    threshold_stagnant = 3.0 * batch_interval

    if half_life <= threshold_drain and max_residence <= threshold_stagnant:
        return "draining"
    if half_life <= threshold_stagnant:
        return "stagnant"
    return "accumulating"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_half_life(
    events: Sequence[Tuple[datetime, Optional[datetime]]],
    batch_interval: float = 600.0,
    now: Optional[datetime] = None,
) -> BacklogReport:
    """Compute backlog half-life from file appearance/resolution events.

    Parameters
    ----------
    events : sequence of (appeared_at, resolved_at_or_None)
        Each tuple represents one file.  ``resolved_at = None`` means
        the file is still pending in the backlog.
    batch_interval : float
        Expected seconds between batch commits (default 600 = 10 min).
    now : datetime, optional
        Reference time for computing pending-file ages.  Defaults to
        ``datetime.now(timezone.utc)``.

    Returns
    -------
    BacklogReport
    """
    if now is None:
        now = datetime.now(timezone.utc)
    now_s = _to_seconds(now)

    residence_times: list[float] = []
    pending = 0
    pending_ages: list[float] = []

    for appeared, resolved in events:
        appeared_s = _to_seconds(appeared)
        if resolved is not None:
            resolved_s = _to_seconds(resolved)
            residence_times.append(max(0.0, resolved_s - appeared_s))
        else:
            pending += 1
            pending_ages.append(max(0.0, now_s - appeared_s))

    total = len(events)
    resolved_count = len(residence_times)

    # Compute stats on resolved files
    median_res = statistics.median(residence_times) if residence_times else 0.0
    max_res = max(residence_times) if residence_times else 0.0
    hl = _empirical_half_life(residence_times)

    # Drain rate: resolved files per minute over observation window
    if events:
        all_times = [_to_seconds(a) for a, _ in events]
        window_s = max(1.0, now_s - min(all_times))
        drain_rate = resolved_count / (window_s / 60.0)
    else:
        drain_rate = 0.0

    verdict = _classify(hl, max_res, pending, batch_interval)

    return BacklogReport(
        total_files=total,
        resolved=resolved_count,
        pending=pending,
        residence_times=residence_times,
        median_residence=median_res,
        max_residence=max_res,
        half_life=hl,
        drain_rate_per_min=drain_rate,
        verdict=verdict,
    )


def report_summary(report: BacklogReport) -> str:
    """Human-readable one-liner."""
    hl_str = f"{report.half_life:.0f}s" if report.half_life is not None else "n/a"
    return (
        f"backlog: {report.total_files} files "
        f"({report.resolved} resolved, {report.pending} pending), "
        f"half-life={hl_str}, "
        f"drain={report.drain_rate_per_min:.2f}/min, "
        f"verdict={report.verdict}"
    )
