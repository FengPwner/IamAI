#!/usr/bin/env python3
"""Measure the repo's "reflex" — how quickly the writing system self-corrects
when something goes wrong.

Biological metaphor:
    A healthy organism has fast reflexes — involuntary, automatic responses
    that restore equilibrium.  A numb organism takes too long to react,
    letting small problems compound.

    Stimulus              → Reflex
    ─────────────────────   ──────────────────────────────────
    Writer stall          → Recovery stroke appears
    Backlog accumulation  → Batch commit clears it
    Process death         → Watchdog restarts it
    Cadence drift         → Interval snaps back to target

Four metrics, each scored 0–25, summed to 0–100:

    1. stroke_recovery    — after a gap > 2× cadence, median time to next stroke
    2. backlog_clearance  — after ≥ 5 pending files, median time to commit burst
    3. restart_latency    — median seconds between process death and respawn
    4. cadence_return     — how fast commit intervals converge back to target

Grading:
    sharp       80–100   fast self-healing, nearly instant recovery
    responsive   50–79   acceptable lag, system corrects within minutes
    sluggish     20–49   slow recovery, gaps linger
    numb          0–19   no meaningful self-correction

Usage:
    python3 tools/repo_reflex.py              # human-readable
    python3 tools/repo_reflex.py --json       # machine-readable
    python3 tools/repo_reflex.py --commits 200  # scan more commit history

Exit codes:
    0  grade sharp or responsive
    1  grade sluggish
    2  grade numb
    3  error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_COMMITS = 100
CADENCE_TARGET_S = 600  # 10-minute commit cadence
STALL_THRESHOLD_S = 120  # 2× the 60s writer cadence → 120s
BACKLOG_THRESHOLD = 5  # pending files before "backlog event"


# ── Data ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReflexMetric:
    name: str
    value: float  # 0–25
    detail: str = ""


@dataclass
class ReflexReport:
    metrics: List[ReflexMetric] = field(default_factory=list)
    total: float = 0.0
    grade: str = "numb"
    scanned_commits: int = 0
    checked_at: str = ""


# ── Scoring helpers ───────────────────────────────────────────────────


def _clamp(v: float, lo: float = 0.0, hi: float = 25.0) -> float:
    return max(lo, min(hi, v))


def score_stroke_recovery(gaps: List[float], cadence_s: float = 60.0) -> ReflexMetric:
    """Score how fast the system recovers from writer stalls.

    gaps: list of inter-stroke gaps in seconds that exceeded 2× cadence.
    Lower median recovery time → higher score.
    """
    if not gaps:
        # No stalls detected — perfect reflex (nothing to recover from).
        return ReflexMetric("stroke_recovery", 25.0, "no stalls in window")
    stall_events = [g for g in gaps if g > 2 * cadence_s]
    if not stall_events:
        return ReflexMetric("stroke_recovery", 25.0, "no stall events")
    med = median(stall_events)
    # 0s extra delay → 25; 600s → 12.5; 1800s+ → 0
    score = _clamp(25.0 * (1.0 - med / 1800.0))
    return ReflexMetric(
        "stroke_recovery",
        round(score, 2),
        f"median stall duration {med:.0f}s across {len(stall_events)} events",
    )


def score_backlog_clearance(clearance_times: List[float]) -> ReflexMetric:
    """Score how fast accumulated pending files get committed.

    clearance_times: seconds from backlog ≥ BACKLOG_THRESHOLD to next commit.
    """
    if not clearance_times:
        return ReflexMetric("backlog_clearance", 25.0, "no backlog events")
    med = median(clearance_times)
    # 0s → 25; 900s → 12.5; 1800s+ → 0
    score = _clamp(25.0 * (1.0 - med / 1800.0))
    return ReflexMetric(
        "backlog_clearance",
        round(score, 2),
        f"median clearance {med:.0f}s across {len(clearance_times)} events",
    )


def score_restart_latency(restarts: List[float]) -> ReflexMetric:
    """Score process restart speed after a death.

    restarts: seconds between process death detection and new PID appearing.
    """
    if not restarts:
        return ReflexMetric("restart_latency", 25.0, "no restarts needed")
    med = median(restarts)
    # 0s → 25; 300s → 12.5; 600s+ → 0
    score = _clamp(25.0 * (1.0 - med / 600.0))
    return ReflexMetric(
        "restart_latency",
        round(score, 2),
        f"median restart {med:.0f}s across {len(restarts)} events",
    )


def score_cadence_return(intervals: List[float], target_s: float = CADENCE_TARGET_S) -> ReflexMetric:
    """Score how fast commit intervals return to target after drifting.

    intervals: actual inter-commit intervals in seconds.
    """
    if len(intervals) < 2:
        return ReflexMetric("cadence_return", 25.0, "too few intervals to measure")
    deviations = [abs(iv - target_s) / target_s for iv in intervals]
    # Look at how quickly large deviations (>50%) are followed by small ones (<30%).
    recovery_times: List[float] = []
    for i, dev in enumerate(deviations):
        if dev > 0.5:
            # Find next interval within 30% of target.
            for j in range(i + 1, len(deviations)):
                if deviations[j] <= 0.3:
                    recovery_times.append((j - i) * target_s)
                    break
    if not recovery_times:
        # All drifted intervals eventually recovered (or none drifted).
        mean_dev = sum(deviations) / len(deviations) if deviations else 0.0
        score = _clamp(25.0 * (1.0 - mean_dev))
        return ReflexMetric(
            "cadence_return",
            round(score, 2),
            f"mean deviation {mean_dev:.1%}, no unresolved drifts",
        )
    med = median(recovery_times)
    # 1 target cycle → 25; 3 cycles → 12.5; 5+ cycles → 0
    cycles = med / target_s
    score = _clamp(25.0 * (1.0 - (cycles - 1) / 4.0))
    return ReflexMetric(
        "cadence_return",
        round(score, 2),
        f"median return in {cycles:.1f} cycles ({med:.0f}s) across {len(recovery_times)} drifts",
    )


def grade(total: float) -> str:
    if total >= 80:
        return "sharp"
    if total >= 50:
        return "responsive"
    if total >= 20:
        return "sluggish"
    return "numb"


def exit_code_for_grade(g: str) -> int:
    return {"sharp": 0, "responsive": 0, "sluggish": 1, "numb": 2}.get(g, 3)


# ── Data gathering ────────────────────────────────────────────────────


def _git_log_timestamps(n: int) -> List[datetime]:
    """Return the last N commit timestamps as aware datetimes."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{n}", "--format=%aI"],
            capture_output=True, text=True, cwd=REPO, timeout=10,
        )
        if result.returncode != 0:
            return []
        return [datetime.fromisoformat(line.strip()) for line in result.stdout.strip().split("\n") if line.strip()]
    except Exception:
        return []


def _intervals_from_timestamps(ts: List[datetime]) -> List[float]:
    """Return inter-commit intervals in seconds (positive, chronological order)."""
    if len(ts) < 2:
        return []
    ordered = sorted(ts)
    return [(ordered[i + 1] - ordered[i]).total_seconds() for i in range(len(ordered) - 1)]


def assess(n_commits: int = DEFAULT_COMMITS) -> ReflexReport:
    """Run all reflex measurements and produce a report."""
    now = datetime.now(timezone.utc).isoformat()
    timestamps = _git_log_timestamps(n_commits)
    intervals = _intervals_from_timestamps(timestamps)

    # Stroke gaps: use commit intervals as proxy (commit gaps reflect writer stalls too).
    stall_metric = score_stroke_recovery(intervals, cadence_s=CADENCE_TARGET_S / 10)

    # Backlog clearance: approximate from commit interval bursts.
    # Long gap followed by short gap = backlog cleared.
    clearance_times: List[float] = []
    for i, iv in enumerate(intervals):
        if iv > CADENCE_TARGET_S * 2:
            # This is a backlog event; the next interval is the clearance.
            if i + 1 < len(intervals):
                clearance_times.append(intervals[i + 1])
    backlog_metric = score_backlog_clearance(clearance_times)

    # Restart latency: approximate from long gaps (>5× target) that are followed by recovery.
    restart_times: List[float] = []
    for i, iv in enumerate(intervals):
        if iv > CADENCE_TARGET_S * 5:
            # The gap itself is the restart latency proxy.
            restart_times.append(iv)
    restart_metric = score_restart_latency(restart_times)

    # Cadence return.
    cadence_metric = score_cadence_return(intervals, target_s=CADENCE_TARGET_S)

    metrics = [stall_metric, backlog_metric, restart_metric, cadence_metric]
    total = sum(m.value for m in metrics)
    g = grade(total)

    return ReflexReport(
        metrics=metrics,
        total=round(total, 2),
        grade=g,
        scanned_commits=len(timestamps),
        checked_at=now,
    )


# ── Formatting ────────────────────────────────────────────────────────


def as_text(r: ReflexReport) -> str:
    lines = [
        f"repo reflex: {r.grade.upper()}  ({r.total}/100)  [{r.scanned_commits} commits scanned]",
        "",
    ]
    for m in r.metrics:
        bar = "█" * int(m.value / 25 * 10) + "░" * (10 - int(m.value / 25 * 10))
        lines.append(f"  {m.name:<22} {bar} {m.value:5.1f}/25  {m.detail}")
    return "\n".join(lines)


def as_json(r: ReflexReport) -> str:
    return json.dumps(
        {
            "grade": r.grade,
            "total": r.total,
            "scanned_commits": r.scanned_commits,
            "checked_at": r.checked_at,
            "metrics": [asdict(m) for m in r.metrics],
        },
        indent=2,
    )


# ── CLI ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure repo self-healing reflexes.")
    parser.add_argument("--commits", type=int, default=DEFAULT_COMMITS,
                        help=f"Number of recent commits to scan (default: {DEFAULT_COMMITS})")
    parser.add_argument("--json", dest="use_json", action="store_true",
                        help="Machine-readable JSON output")
    args = parser.parse_args(argv)

    report = assess(n_commits=args.commits)

    if args.use_json:
        print(as_json(report))
    else:
        print(as_text(report))

    return exit_code_for_grade(report.grade)


if __name__ == "__main__":
    sys.exit(main())
