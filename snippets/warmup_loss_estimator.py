"""067 — warmup_loss_estimator: quantify the productivity cost of restarts.

every process restart has a warmup period — the gap between "process is alive"
and "process is producing at full cadence." this module measures that cost:

  - warmup_seconds: time from restart to first stroke
  - stabilization_seconds: time from restart to sustained cadence
  - strokes_lost: estimated strokes that would have been produced if the
    previous generation had not died

the estimator takes a list of generation records (each with restart_time,
first_stroke_time, and a target cadence) and produces aggregate stats.

usage:

>>> from datetime import datetime, timezone, timedelta
>>> now = datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc)
>>> gens = [
...     Generation(
...         restart_time=now,
...         first_stroke_time=now + timedelta(seconds=45),
...         target_cadence=15,
...         strokes_in_first_hour=180,
...     ),
...     Generation(
...         restart_time=now + timedelta(hours=2),
...         first_stroke_time=now + timedelta(hours=2, seconds=120),
...         target_cadence=15,
...         strokes_in_first_hour=150,
...     ),
... ]
>>> report = estimate_warmup_loss(gens)
>>> report.total_warmup_seconds
165.0
>>> report.total_strokes_lost
11.0

pure Python, no dependencies.
written by Qwen during caretaker visit 757, 2026-11-21.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class Generation:
    """Record of one process generation's startup characteristics."""

    restart_time: datetime
    first_stroke_time: Optional[datetime]
    target_cadence: float  # seconds per stroke when healthy
    strokes_in_first_hour: int = 0

    @property
    def warmup_seconds(self) -> float:
        """Seconds from restart to first stroke. None if no stroke yet."""
        if self.first_stroke_time is None:
            return float("inf")
        delta = (self.first_stroke_time - self.restart_time).total_seconds()
        return max(0.0, delta)

    @property
    def expected_strokes_in_hour(self) -> int:
        """How many strokes a healthy process produces in one hour."""
        if self.target_cadence <= 0:
            return 0
        return int(3600 / self.target_cadence)

    @property
    def strokes_lost_in_warmup(self) -> int:
        """Estimated strokes lost during the warmup period."""
        if self.first_stroke_time is None:
            return self.expected_strokes_in_hour  # worst case: entire hour lost
        warmup = self.warmup_seconds
        if self.target_cadence <= 0:
            return 0
        return int(warmup / self.target_cadence)

    @property
    def stabilization_deficit(self) -> int:
        """How far below expected output the first hour fell."""
        return max(0, self.expected_strokes_in_hour - self.strokes_in_first_hour)


@dataclass(frozen=True)
class WarmupLossReport:
    """Aggregate warmup loss across multiple generations."""

    generations: int
    total_warmup_seconds: float
    total_strokes_lost: int
    mean_warmup_seconds: float
    worst_warmup_seconds: float
    total_stabilization_deficit: int

    @property
    def avg_strokes_lost_per_restart(self) -> float:
        if self.generations == 0:
            return 0.0
        return self.total_strokes_lost / self.generations

    @property
    def hourly_cost_seconds(self) -> float:
        """If restarts happen once per hour, how many seconds of each hour
        are consumed by warmup (not producing)."""
        if self.generations == 0:
            return 0.0
        return self.mean_warmup_seconds

    def severity(self) -> str:
        """Classify warmup severity."""
        if self.generations == 0:
            return "unknown"
        avg = self.mean_warmup_seconds
        if avg <= 30:
            return "negligible"
        elif avg <= 120:
            return "moderate"
        elif avg <= 600:
            return "significant"
        else:
            return "severe"


def estimate_warmup_loss(
    generations: Sequence[Generation],
) -> WarmupLossReport:
    """Compute aggregate warmup loss from a sequence of generation records."""
    if not generations:
        return WarmupLossReport(
            generations=0,
            total_warmup_seconds=0.0,
            total_strokes_lost=0,
            mean_warmup_seconds=0.0,
            worst_warmup_seconds=0.0,
            total_stabilization_deficit=0,
        )

    warmups = []
    strokes_lost = 0
    stabilization_deficit = 0

    for gen in generations:
        w = gen.warmup_seconds
        if w != float("inf"):
            warmups.append(w)
        strokes_lost += gen.strokes_lost_in_warmup
        stabilization_deficit += gen.stabilization_deficit

    total_warmup = sum(warmups) if warmups else 0.0
    worst = max(warmups) if warmups else 0.0
    mean_warmup = total_warmup / len(warmups) if warmups else 0.0

    return WarmupLossReport(
        generations=len(generations),
        total_warmup_seconds=total_warmup,
        total_strokes_lost=strokes_lost,
        mean_warmup_seconds=mean_warmup,
        worst_warmup_seconds=worst,
        total_stabilization_deficit=stabilization_deficit,
    )


def generation_timeline(
    generations: Sequence[Generation],
) -> List[dict]:
    """Produce a per-generation timeline for visualization or logging."""
    timeline = []
    for i, gen in enumerate(generations):
        timeline.append({
            "generation": i,
            "restart_time": gen.restart_time.isoformat(),
            "warmup_seconds": gen.warmup_seconds
            if gen.warmup_seconds != float("inf")
            else None,
            "strokes_lost": gen.strokes_lost_in_warmup,
            "stabilization_deficit": gen.stabilization_deficit,
            "first_hour_output": gen.strokes_in_first_hour,
        })
    return timeline
