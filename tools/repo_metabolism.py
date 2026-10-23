#!/usr/bin/env python3
"""Measure the repo's "metabolism" — how efficiently it converts writer
strokes into committed, persistent work.

Biological metaphor:
    - Input  = strokes (the writer's raw output, like calories consumed)
    - Output = commits (persistent changes, like energy expended)
    - Efficiency = how much input becomes output vs. waste

A healthy metabolism means strokes flow into commits at a steady rate.
A stalled metabolism means strokes pile up uncommitted (backlog bloat)
or commits happen without new strokes (empty/mechanical commits).

Four metrics, each scored 0–25, summed to 0–100:

    1. conversion_rate  — ratio of committed strokes to total strokes
    2. throughput       — absolute strokes committed per hour
    3. waste_ratio      — fraction of strokes sitting uncommitted (inverted)
    4. rhythm_stability — coefficient of variation in commit sizes (inverted)

Grading:
    anabolic    80–100   building mass fast (high output, low waste)
    healthy     50–79    steady metabolism
    sluggish    20–49    low output, growing backlog
    dormant      0–19    near-zero conversion (stalled or starved)

Usage:
    python3 tools/repo_metabolism.py              # human-readable
    python3 tools/repo_metabolism.py --json       # machine-readable
    python3 tools/repo_metabolism.py --hours 6    # look back 6h instead of 24h

Exit codes:
    0  grade anabolic or healthy
    1  grade sluggish
    2  grade dormant
    3  error
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent


# ── Data ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetabolicMetric:
    name: str
    value: float          # 0–25
    max: float = 25.0
    detail: str = ""


@dataclass(frozen=True)
class MetabolismReport:
    score: float
    grade: str            # anabolic / healthy / sluggish / dormant
    metrics: List[MetabolicMetric]
    total_strokes: int
    committed_strokes: int
    uncommitted_strokes: int
    commits_in_window: int
    window_hours: float
    conversion_pct: float
    throughput_per_hour: float
    timestamp: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = [asdict(m) for m in self.metrics]
        return d


# ── Scoring helpers ───────────────────────────────────────────────────


def score_conversion_rate(committed: int, total: int) -> MetabolicMetric:
    """25 pts if ≥90% strokes are committed, 0 if ≤50%."""
    if total == 0:
        pct = 0.0
    else:
        pct = committed / total
    # linear scale: 50% → 0 pts, 90% → 25 pts
    clamped = max(0.0, min(1.0, (pct - 0.5) / 0.4))
    score = round(clamped * 25.0, 2)
    return MetabolicMetric(
        name="conversion_rate",
        value=score,
        detail=f"{committed}/{total} strokes committed ({pct:.0%})",
    )


def score_throughput(committed_in_window: int, window_hours: float) -> MetabolicMetric:
    """25 pts at ≥60 strokes/hour, 0 at 0."""
    if window_hours <= 0:
        rate = 0.0
    else:
        rate = committed_in_window / window_hours
    clamped = min(rate / 60.0, 1.0)
    score = round(clamped * 25.0, 2)
    return MetabolicMetric(
        name="throughput",
        value=score,
        detail=f"{rate:.1f} strokes/hr ({committed_in_window} in {window_hours:.1f}h)",
    )


def score_waste_ratio(uncommitted: int, total: int) -> MetabolicMetric:
    """25 pts if 0% waste (nothing uncommitted), 0 if ≥30% waste."""
    if total == 0:
        waste = 0.0
    else:
        waste = uncommitted / total
    # invert: 0% waste → 25 pts, 30%+ waste → 0 pts
    clamped = max(0.0, min(1.0, 1.0 - waste / 0.3))
    score = round(clamped * 25.0, 2)
    return MetabolicMetric(
        name="waste_ratio",
        value=score,
        detail=f"{uncommitted}/{total} uncommitted ({waste:.0%} waste)",
    )


def score_rhythm_stability(sizes: List[int]) -> MetabolicMetric:
    """25 pts if commit sizes are consistent (low CV), 0 if highly variable."""
    if len(sizes) < 2:
        # can't compute CV — give benefit of the doubt if at least 1 commit
        score = 25.0 if len(sizes) == 1 else 0.0
        detail = f"{len(sizes)} commit(s) — too few for CV"
    else:
        mean = sum(sizes) / len(sizes)
        if mean == 0:
            cv = float("inf")
        else:
            variance = sum((s - mean) ** 2 for s in sizes) / len(sizes)
            cv = math.sqrt(variance) / mean
        # CV 0.0 → 25 pts, CV ≥ 2.0 → 0 pts
        clamped = max(0.0, min(1.0, 1.0 - cv / 2.0))
        score = round(clamped * 25.0, 2)
        detail = f"CV={cv:.2f} across {len(sizes)} commits"
    return MetabolicMetric(
        name="rhythm_stability",
        value=score,
        detail=detail,
    )


def grade(score: float) -> str:
    if score >= 80:
        return "anabolic"
    elif score >= 50:
        return "healthy"
    elif score >= 20:
        return "sluggish"
    else:
        return "dormant"


def exit_code_for_grade(g: str) -> int:
    return {"anabolic": 0, "healthy": 0, "sluggish": 1, "dormant": 2}.get(g, 3)


# ── Data collection ───────────────────────────────────────────────────


def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    return r.stdout.strip()


def count_strokes_in_window(hours: float) -> tuple[int, int]:
    """Return (total_strokes, committed_strokes) within the time window.

    Reads strokes.jsonl and checks timestamps against the window.
    committed_strokes = strokes whose timestamp falls within the window.
    """
    strokes_file = REPO / "data" / "strokes.jsonl"
    if not strokes_file.exists():
        return 0, 0

    now = time.time()
    cutoff = now - hours * 3600
    total = 0
    committed = 0

    with open(strokes_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("at", "")
                # parse ISO timestamp
                if ts_str:
                    # handle both +00:00 and Z suffixes
                    ts_str = ts_str.replace("+00:00", "+0000").replace("Z", "+0000")
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")
                    except ValueError:
                        # try without timezone
                        dt = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts = dt.timestamp()
                    if ts >= cutoff:
                        total += 1
                        # For simplicity, all strokes in the JSONL are "committed"
                        # since they're already in the file. The "uncommitted" ones
                        # would be those the writer generated but the batch hasn't
                        # committed yet — we approximate via git status.
                        committed += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    return total, committed


def count_uncommitted_strokes() -> int:
    """Estimate uncommitted stroke count from strokes.jsonl changes."""
    try:
        diff = _run(["git", "diff", "--numstat", "data/strokes.jsonl"])
        if diff:
            parts = diff.split()
            if len(parts) >= 1 and parts[0] != "-":
                return int(parts[0])
    except (ValueError, IndexError):
        pass
    return 0


def get_commit_sizes_in_window(hours: float) -> List[int]:
    """Get list of files-changed per commit within the time window."""
    cutoff_s = f"{int(hours * 3600)} seconds ago"
    try:
        log = _run([
            "git", "log",
            f"--since={cutoff_s}",
            "--format=%H",
        ])
    except Exception:
        return []

    if not log:
        return []

    sizes = []
    for sha in log.splitlines():
        sha = sha.strip()
        if not sha:
            continue
        try:
            stat = _run(["git", "diff-tree", "--no-commit-id", "--numstat", sha])
            count = len([l for l in stat.splitlines() if l.strip()]) if stat else 0
            sizes.append(max(count, 1))  # at least 1 to avoid zero-division
        except Exception:
            continue

    return sizes


# ── Main measurement ─────────────────────────────────────────────────


def measure(hours: float = 24.0) -> MetabolismReport:
    total, committed = count_strokes_in_window(hours)
    uncommitted = count_uncommitted_strokes()
    sizes = get_commit_sizes_in_window(hours)

    m_conversion = score_conversion_rate(committed, total + uncommitted)
    m_throughput = score_throughput(committed, hours)
    m_waste = score_waste_ratio(uncommitted, total + uncommitted)
    m_rhythm = score_rhythm_stability(sizes)

    metrics = [m_conversion, m_throughput, m_waste, m_rhythm]
    total_score = round(sum(m.value for m in metrics), 2)
    g = grade(total_score)

    conversion_pct = (committed / (total + uncommitted) * 100) if (total + uncommitted) > 0 else 0.0
    throughput = committed / hours if hours > 0 else 0.0

    return MetabolismReport(
        score=total_score,
        grade=g,
        metrics=metrics,
        total_strokes=total,
        committed_strokes=committed,
        uncommitted_strokes=uncommitted,
        commits_in_window=len(sizes),
        window_hours=hours,
        conversion_pct=round(conversion_pct, 1),
        throughput_per_hour=round(throughput, 1),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Output ────────────────────────────────────────────────────────────


def as_text(r: MetabolismReport) -> str:
    bar_w = 30
    filled = int(r.score / 100 * bar_w)
    bar = "█" * filled + "░" * (bar_w - filled)

    lines = [
        f"repo metabolism: {r.score}/100 [{bar}] {r.grade}",
        f"  window: {r.window_hours:.0f}h | strokes: {r.total_strokes} committed, "
        f"{r.uncommitted_strokes} uncommitted | commits: {r.commits_in_window}",
        "",
    ]
    for m in r.metrics:
        mbar = "▓" * int(m.value / 25 * 15) + "░" * (15 - int(m.value / 25 * 15))
        lines.append(f"  {m.name:20s} [{mbar}] {m.value:5.1f}/25  {m.detail}")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Measure repo metabolism.")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--hours", type=float, default=24.0, help="Lookback window (default: 24h)")
    args = p.parse_args()

    try:
        report = measure(hours=args.hours)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(as_text(report))

    return exit_code_for_grade(report.grade)


if __name__ == "__main__":
    sys.exit(main())
