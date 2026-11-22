#!/usr/bin/env python3
"""stall_recovery_timer — measure end-to-end stall recovery performance.

when the writer stalls (process death, environment recycle, network
blip), the caretaker must detect the stall, restart processes, flush
backlog commits, resolve push conflicts, and confirm the push landed.
the wall-clock time from "stall detected" to "push confirmed" is the
recovery time — a direct measure of ops responsiveness.

this module answers:
1. how long did each recovery phase take?
2. what fraction of recovery time was spent on useful work vs waiting?
3. is recovery getting faster or slower over successive visits?

public API
----------
- ``RecoveryPhase``    – one named phase with start/end timestamps.
- ``StallRecovery``    – complete recovery event with multiple phases.
- ``RecoveryMetrics``  – computed metrics for one recovery event.
- ``compute_metrics()``  – derive metrics from a StallRecovery.
- ``grade()``          – human-friendly grade (A/B/C/D/F).
- ``RecoveryTrend``    – trend analysis over multiple recoveries.
- ``build_trend()``    – aggregate recoveries into a trend report.

exit codes (CLI):
    0  recovery grade A or B
    1  recovery grade C or worse
    2  insufficient data
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Dict, Any

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

# target: full recovery within 3 minutes of detection
TARGET_RECOVERY_SEC = 180

# grade thresholds (total recovery seconds)
GRADE_THRESHOLDS = {
    "A": 60,    # under 1 minute — excellent
    "B": 180,   # under 3 minutes — good
    "C": 300,   # under 5 minutes — acceptable
    "D": 600,   # under 10 minutes — slow
    # anything above 600s = F
}

PHASE_NAMES = [
    "detect",       # stall detection
    "restart",      # process restart
    "commit",       # backlog flush
    "pull_merge",   # remote sync / conflict resolution
    "push",         # push to remote
    "confirm",      # push confirmation
]


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecoveryPhase:
    """one phase of the recovery pipeline."""
    name: str
    started_at: datetime
    ended_at: datetime

    @property
    def duration_sec(self) -> float:
        """phase duration in seconds, floored at 0."""
        delta = (self.ended_at - self.started_at).total_seconds()
        return max(0.0, delta)

    @property
    def is_valid(self) -> bool:
        """ended_at must be >= started_at."""
        return self.ended_at >= self.started_at


@dataclass(frozen=True)
class StallRecovery:
    """complete recovery event: stall detected → push confirmed."""
    visit_id: int
    stall_detected_at: datetime
    push_confirmed_at: datetime
    phases: tuple  # tuple of RecoveryPhase (frozen for hashability)
    stall_duration_sec: float = 0.0  # how long the stall lasted before detection
    notes: str = ""

    @property
    def total_recovery_sec(self) -> float:
        """wall-clock seconds from detection to push confirmed."""
        delta = (self.push_confirmed_at - self.stall_detected_at).total_seconds()
        return max(0.0, delta)

    @property
    def phase_count(self) -> int:
        return len(self.phases)

    @property
    def is_valid(self) -> bool:
        """push confirmed must be after stall detected."""
        return self.push_confirmed_at >= self.stall_detected_at


@dataclass(frozen=True)
class RecoveryMetrics:
    """computed metrics for one recovery event."""
    visit_id: int
    total_sec: float
    phase_breakdown: Dict[str, float]  # phase_name → seconds
    longest_phase: str
    longest_phase_sec: float
    efficiency: float  # sum of phase durations / total recovery time
    grade: str  # A/B/C/D/F
    stall_duration_sec: float

    @property
    def within_target(self) -> bool:
        return self.total_sec <= TARGET_RECOVERY_SEC

    @property
    def efficiency_pct(self) -> float:
        return round(self.efficiency * 100, 1)

    def summary(self) -> Dict[str, Any]:
        return {
            "visit_id": self.visit_id,
            "total_sec": round(self.total_sec, 1),
            "grade": self.grade,
            "within_target": self.within_target,
            "efficiency_pct": self.efficiency_pct,
            "longest_phase": self.longest_phase,
            "longest_phase_sec": round(self.longest_phase_sec, 1),
            "stall_duration_sec": round(self.stall_duration_sec, 1),
            "phase_breakdown": {
                k: round(v, 1) for k, v in self.phase_breakdown.items()
            },
        }


@dataclass(frozen=True)
class RecoveryTrend:
    """trend analysis over multiple recovery events."""
    count: int
    mean_sec: float
    median_sec: float
    best_sec: float
    worst_sec: float
    grades: List[str]
    within_target_count: int
    direction: str  # improving / steady / worsening / insufficient_data

    @property
    def target_compliance_pct(self) -> float:
        if self.count == 0:
            return 0.0
        return round(self.within_target_count / self.count * 100, 1)

    def verdict(self) -> str:
        if self.count == 0:
            return "no_data"
        if self.mean_sec <= GRADE_THRESHOLDS["B"] and self.target_compliance_pct >= 80:
            return "healthy"
        if self.mean_sec <= GRADE_THRESHOLDS["C"]:
            return "acceptable"
        return "needs_improvement"

    def summary(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "mean_sec": round(self.mean_sec, 1),
            "median_sec": round(self.median_sec, 1),
            "best_sec": round(self.best_sec, 1),
            "worst_sec": round(self.worst_sec, 1),
            "direction": self.direction,
            "verdict": self.verdict(),
            "target_compliance_pct": self.target_compliance_pct,
            "grades": self.grades,
        }


# ---------------------------------------------------------------------------
# core functions
# ---------------------------------------------------------------------------

def compute_metrics(recovery: StallRecovery) -> RecoveryMetrics:
    """derive metrics from a single recovery event."""
    breakdown: Dict[str, float] = {}
    for phase in recovery.phases:
        breakdown[phase.name] = phase.duration_sec

    # find longest phase
    if breakdown:
        longest_name = max(breakdown, key=breakdown.get)
        longest_sec = breakdown[longest_name]
    else:
        longest_name = "none"
        longest_sec = 0.0

    # efficiency: sum of measured phase time / total wall clock
    phase_sum = sum(breakdown.values())
    total = recovery.total_recovery_sec
    efficiency = min(1.0, phase_sum / total) if total > 0 else 1.0

    return RecoveryMetrics(
        visit_id=recovery.visit_id,
        total_sec=total,
        phase_breakdown=breakdown,
        longest_phase=longest_name,
        longest_phase_sec=longest_sec,
        efficiency=efficiency,
        grade=grade(total),
        stall_duration_sec=recovery.stall_duration_sec,
    )


def grade(total_sec: float) -> str:
    """assign a letter grade based on total recovery time."""
    for letter, threshold in GRADE_THRESHOLDS.items():
        if total_sec <= threshold:
            return letter
    return "F"


def build_trend(recoveries: Sequence[StallRecovery]) -> RecoveryTrend:
    """aggregate multiple recovery events into a trend."""
    if not recoveries:
        return RecoveryTrend(
            count=0, mean_sec=0, median_sec=0, best_sec=0, worst_sec=0,
            grades=[], within_target_count=0, direction="insufficient_data",
        )

    totals = [r.total_recovery_sec for r in recoveries]
    grades_list = [grade(t) for t in totals]
    within = sum(1 for t in totals if t <= TARGET_RECOVERY_SEC)

    sorted_totals = sorted(totals)
    n = len(sorted_totals)
    median = (
        sorted_totals[n // 2]
        if n % 2 == 1
        else (sorted_totals[n // 2 - 1] + sorted_totals[n // 2]) / 2
    )

    # direction: compare first half vs second half
    direction = "insufficient_data"
    if n >= 4:
        half = n // 2
        first_mean = sum(sorted_totals[:half]) / half
        second_mean = sum(sorted_totals[half:]) / (n - half)
        # wait — sorted_totals is sorted by value, not by time.
        # we should use the original order (chronological).
        chrono_totals = [r.total_recovery_sec for r in recoveries]
        first_mean = sum(chrono_totals[:half]) / half
        second_mean = sum(chrono_totals[half:]) / (n - half)
        diff = second_mean - first_mean
        if diff < -10:
            direction = "improving"
        elif diff > 10:
            direction = "worsening"
        else:
            direction = "steady"
    elif n >= 2:
        if totals[-1] < totals[0] - 10:
            direction = "improving"
        elif totals[-1] > totals[0] + 10:
            direction = "worsening"
        else:
            direction = "steady"

    return RecoveryTrend(
        count=n,
        mean_sec=sum(totals) / n,
        median_sec=median,
        best_sec=min(totals),
        worst_sec=max(totals),
        grades=grades_list,
        within_target_count=within,
        direction=direction,
    )


def metrics_to_text(m: RecoveryMetrics) -> str:
    """one-liner summary of recovery metrics."""
    parts = [
        f"visit {m.visit_id}",
        f"grade={m.grade}",
        f"total={m.total_sec:.0f}s",
        f"target={'met' if m.within_target else 'missed'}",
        f"efficiency={m.efficiency_pct}%",
        f"longest={m.longest_phase}({m.longest_phase_sec:.0f}s)",
    ]
    return " | ".join(parts)


def trend_to_text(t: RecoveryTrend) -> str:
    """one-liner summary of recovery trend."""
    if t.count == 0:
        return "recovery trend: no data"
    parts = [
        f"recovery trend: {t.count} events",
        f"mean={t.mean_sec:.0f}s",
        f"best={t.best_sec:.0f}s",
        f"worst={t.worst_sec:.0f}s",
        f"direction={t.direction}",
        f"verdict={t.verdict()}",
        f"compliance={t.target_compliance_pct}%",
    ]
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """read recovery events from data/stall_recoveries.jsonl and report."""
    repo = Path(__file__).resolve().parent.parent
    data_file = repo / "data" / "stall_recoveries.jsonl"

    if not data_file.exists():
        print("no data/stall_recoveries.jsonl found")
        return 2

    recoveries = []
    with open(data_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            base = datetime.fromisoformat(obj["stall_detected_at"])
            push = datetime.fromisoformat(obj["push_confirmed_at"])
            phases = tuple(
                RecoveryPhase(
                    name=p["name"],
                    started_at=datetime.fromisoformat(p["started_at"]),
                    ended_at=datetime.fromisoformat(p["ended_at"]),
                )
                for p in obj.get("phases", [])
            )
            recoveries.append(StallRecovery(
                visit_id=obj["visit_id"],
                stall_detected_at=base,
                push_confirmed_at=push,
                phases=phases,
                stall_duration_sec=obj.get("stall_duration_sec", 0),
                notes=obj.get("notes", ""),
            ))

    if not recoveries:
        print("no recovery events found")
        return 2

    for r in recoveries:
        m = compute_metrics(r)
        print(metrics_to_text(m))

    if len(recoveries) >= 2:
        t = build_trend(recoveries)
        print(trend_to_text(t))

    # exit code based on last grade
    last = compute_metrics(recoveries[-1])
    return 0 if last.grade in ("A", "B") else 1


if __name__ == "__main__":
    sys.exit(main())
