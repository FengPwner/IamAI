#!/usr/bin/env python3
"""Compute a composite "commit vitality" score for the writing pipeline.

Unlike commit_freshness (single-commit age) or pipeline_health_index
(end-to-end pipeline), this tool focuses on the *commit layer* — how
alive, regular, and substantive the recent commit history is.

Five dimensions, each scored 0–20, summed to 0–100:

    1. Recency    — how recent is the latest commit?
    2. Regularity — how evenly spaced are recent commits?
    3. Substance  — how many files change per commit on average?
    4. Backlog    — how much uncommitted work is sitting around?
    5. Push sync  — how far behind is the remote?

Grading:
    A  85–100   pipeline is thriving
    B  70–84    healthy with minor drift
    C  50–69    showing signs of neglect
    D  30–49    needs attention
    F   0–29    pipeline is effectively stalled

Usage:
    python3 tools/commit_vitality.py              # human-readable
    python3 tools/commit_vitality.py --json       # machine-readable
    python3 tools/commit_vitality.py --interval 600  # custom batch interval

Exit codes:
    0  grade A or B
    1  grade C
    2  grade D
    3  grade F or error
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent


# ── Data ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: float          # 0–20
    max: float = 20.0
    detail: str = ""


@dataclass(frozen=True)
class VitalityReport:
    total: float
    grade: str
    dimensions: List[DimensionScore]
    uncommitted_files: int
    unpushed_commits: int
    latest_commit_age_s: float
    median_interval_s: float
    avg_files_changed: float
    timestamp: str


# ── Scoring helpers ───────────────────────────────────────────────────


def score_recency(age_s: float, interval: int) -> DimensionScore:
    """20 pts if commit is fresh (≤ interval), decays to 0 at 5× interval."""
    if age_s <= interval:
        s = 20.0
    elif age_s >= 5 * interval:
        s = 0.0
    else:
        # linear decay from interval to 5×interval
        s = 20.0 * (1.0 - (age_s - interval) / (4.0 * interval))
    return DimensionScore(
        name="recency",
        score=round(s, 2),
        detail=f"latest commit {age_s:.0f}s ago, interval={interval}s",
    )


def score_regularity(intervals: List[float], expected: int) -> DimensionScore:
    """20 pts for perfectly regular spacing, penalise variance."""
    if not intervals:
        return DimensionScore(
            name="regularity", score=0.0, detail="no intervals to measure"
        )
    if len(intervals) == 1:
        # single interval: score by closeness to expected
        ratio = min(intervals[0], expected) / max(intervals[0], expected)
        s = 20.0 * ratio
        return DimensionScore(
            name="regularity",
            score=round(s, 2),
            detail=f"1 interval: {intervals[0]:.0f}s vs expected {expected}s",
        )
    mean = sum(intervals) / len(intervals)
    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    cv = math.sqrt(variance) / mean if mean > 0 else 1.0
    # cv=0 → perfect (20 pts), cv≥1.5 → 0 pts
    s = max(0.0, 20.0 * (1.0 - cv / 1.5))
    return DimensionScore(
        name="regularity",
        score=round(s, 2),
        detail=f"cv={cv:.2f} across {len(intervals)} intervals, mean={mean:.0f}s",
    )


def score_substance(avg_files: float) -> DimensionScore:
    """20 pts when avg ≥ 5 files/commit, decays to 0 at 0 files."""
    s = min(20.0, avg_files * 4.0)  # 5 files → 20 pts
    return DimensionScore(
        name="substance",
        score=round(s, 2),
        detail=f"avg {avg_files:.1f} files changed per commit",
    )


def score_backlog(uncommitted: int) -> DimensionScore:
    """20 pts for 0 uncommitted files, −4 per file, floor 0."""
    s = max(0.0, 20.0 - uncommitted * 4.0)
    return DimensionScore(
        name="backlog",
        score=round(s, 2),
        detail=f"{uncommitted} uncommitted file(s)",
    )


def score_push_sync(unpushed: int) -> DimensionScore:
    """20 pts for 0 unpushed commits, −5 per commit, floor 0."""
    s = max(0.0, 20.0 - unpushed * 5.0)
    return DimensionScore(
        name="push_sync",
        score=round(s, 2),
        detail=f"{unpushed} unpushed commit(s)",
    )


def grade(total: float) -> str:
    if total >= 85:
        return "A"
    if total >= 70:
        return "B"
    if total >= 50:
        return "C"
    if total >= 30:
        return "D"
    return "F"


_GRADE_EXIT = {"A": 0, "B": 0, "C": 1, "D": 2, "F": 3}


# ── Git helpers ───────────────────────────────────────────────────────


def _git(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(REPO)] + list(args),
        capture_output=True, text=True, timeout=15,
    )
    return r.stdout.strip()


def _recent_commit_age() -> float:
    ts = _git("log", "-1", "--format=%ct")
    if not ts:
        return 99999.0
    return max(0.0, time.time() - float(ts))


def _recent_intervals(n: int = 20) -> List[float]:
    raw = _git("log", f"-{n + 1}", "--format=%ct")
    if not raw:
        return []
    stamps = [float(t) for t in raw.splitlines() if t.strip()]
    stamps.sort()
    return [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]


def _avg_files_changed(n: int = 20) -> float:
    raw = _git("log", f"-{n}", "--pretty=format:COMMIT", "--numstat")
    if not raw:
        return 0.0
    commits = 0
    files = 0
    for line in raw.splitlines():
        if line.strip() == "COMMIT":
            commits += 1
        elif line.strip() and "\t" in line:
            files += 1
    return files / commits if commits > 0 else 0.0


def _count_uncommitted() -> int:
    out = _git("status", "--porcelain")
    if not out:
        return 0
    return len([l for l in out.splitlines() if l.strip()])


def _count_unpushed() -> int:
    out = _git("log", "@{upstream}..HEAD", "--oneline")
    if not out:
        return 0
    return len([l for l in out.splitlines() if l.strip()])


# ── Main ──────────────────────────────────────────────────────────────


def measure(interval: int = 600, sample: int = 20) -> VitalityReport:
    age = _recent_commit_age()
    intervals = _recent_intervals(sample)
    avg_files = _avg_files_changed(sample)
    uncommitted = _count_uncommitted()
    unpushed = _count_unpushed()

    dims = [
        score_recency(age, interval),
        score_regularity(intervals, interval),
        score_substance(avg_files),
        score_backlog(uncommitted),
        score_push_sync(unpushed),
    ]

    total = round(sum(d.score for d in dims), 2)
    g = grade(total)

    median_iv = sorted(intervals)[len(intervals) // 2] if intervals else 0.0

    return VitalityReport(
        total=total,
        grade=g,
        dimensions=dims,
        uncommitted_files=uncommitted,
        unpushed_commits=unpushed,
        latest_commit_age_s=round(age, 1),
        median_interval_s=round(median_iv, 1),
        avg_files_changed=round(avg_files, 2),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def as_text(r: VitalityReport) -> str:
    lines = [
        f"commit vitality: {r.total}/100  grade {r.grade}",
        "",
    ]
    for d in r.dimensions:
        bar = "█" * int(d.score) + "░" * (20 - int(d.score))
        lines.append(f"  {d.name:<12s} [{bar}] {d.score:5.1f}/20  {d.detail}")
    lines.append("")
    lines.append(f"  latest commit age : {r.latest_commit_age_s:.0f}s")
    lines.append(f"  median interval   : {r.median_interval_s:.0f}s")
    lines.append(f"  avg files/commit  : {r.avg_files_changed:.1f}")
    lines.append(f"  uncommitted files : {r.uncommitted_files}")
    lines.append(f"  unpushed commits  : {r.unpushed_commits}")
    return "\n".join(lines)


def run(interval: int = 600, as_json: bool = False) -> int:
    report = measure(interval)
    if as_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(as_text(report))
    return _GRADE_EXIT.get(report.grade, 3)


def main():
    ap = argparse.ArgumentParser(description="Commit vitality scorer")
    ap.add_argument("--interval", type=int, default=600, help="batch interval in seconds")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    sys.exit(run(args.interval, args.json))


if __name__ == "__main__":
    main()
