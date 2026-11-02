#!/usr/bin/env python3
"""pipeline_timeline.py — measure the temporal health of the write-commit-push pipeline.

Three timestamps tell the story of this repo:

    1. last_stroke   — when the writer last produced content
    2. last_commit   — when git last recorded a change
    3. last_push     — when the remote last received a commit

The gaps between them reveal where the pipeline is stuck:

    stroke-to-commit gap  — writer is producing but batch isn't committing
    commit-to-push gap    — commits exist but haven't landed on remote
    stroke-to-now gap     — the writer itself may be dead

Each gap is classified as healthy / degraded / stalled based on configurable
thresholds, defaulting to the repo's standard cadence (15s writer, 600s batch).

Usage:
    python3 tools/pipeline_timeline.py
    python3 tools/pipeline_timeline.py --json
    python3 tools/pipeline_timeline.py --repo /path/to/IamAI

Exit codes:
    0 — all gaps healthy
    1 — at least one gap degraded
    2 — at least one gap stalled
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_DEFAULT = Path(__file__).resolve().parent.parent

# Default thresholds in seconds
STROKE_HEALTHY = 60       # 4x the 15s cadence
STROKE_DEGRADED = 300     # 20x cadence
COMMIT_HEALTHY = 900      # 1.5x the 600s batch interval
COMMIT_DEGRADED = 1800    # 3x batch interval
PUSH_HEALTHY = 1200       # 2x batch interval
PUSH_DEGRADED = 3600      # 6x batch interval


@dataclass
class TimelinePoint:
    """A single event in the pipeline timeline."""
    label: str
    at: float | None  # epoch seconds, None if unknown
    at_iso: str = ""
    age_seconds: float | None = None
    age_str: str = "unknown"

    def __post_init__(self) -> None:
        if self.at is not None:
            self.at_iso = datetime.fromtimestamp(
                self.at, tz=timezone.utc
            ).isoformat()


@dataclass
class Gap:
    """A gap between two pipeline events."""
    name: str
    seconds: float | None
    status: str  # healthy / degraded / stalled / unknown
    detail: str = ""


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / "data" / "strokes.jsonl").exists():
            return parent
    return p


def last_stroke_time(repo: Path) -> float | None:
    """Epoch seconds of the last stroke in strokes.jsonl."""
    strokes = repo / "data" / "strokes.jsonl"
    if not strokes.exists():
        return None
    try:
        lines = strokes.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None
        entry = json.loads(lines[-1])
        dt = datetime.fromisoformat(entry["at"])
        return dt.timestamp()
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def last_commit_time(repo: Path) -> float | None:
    """Epoch seconds of the most recent local commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None


def last_push_time(repo: Path, remote: str = "origin",
                   branch: str = "main") -> float | None:
    """Epoch seconds of the remote tracking branch's last commit."""
    ref = f"refs/remotes/{remote}/{branch}"
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", ref],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None


def format_age(seconds: float | None) -> str:
    """Human-friendly age string."""
    if seconds is None:
        return "unknown"
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m}m"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    return f"{d}d{h}h"


def classify_gap(seconds: float | None,
                 healthy_max: float,
                 degraded_max: float) -> tuple[str, str]:
    """Return (status, detail) for a gap measurement."""
    if seconds is None:
        return "unknown", "cannot determine"
    if seconds < 0:
        seconds = 0
    if seconds <= healthy_max:
        return "healthy", f"{format_age(seconds)} (within {format_age(healthy_max)})"
    if seconds <= degraded_max:
        return "degraded", f"{format_age(seconds)} exceeds {format_age(healthy_max)}"
    return "stalled", f"{format_age(seconds)} exceeds {format_age(degraded_max)}"


def build_timeline(repo: Path, now: float | None = None) -> dict:
    """Construct the full pipeline timeline report."""
    t_now = now if now is not None else datetime.now(timezone.utc).timestamp()

    stroke_at = last_stroke_time(repo)
    commit_at = last_commit_time(repo)
    push_at = last_push_time(repo)

    points = [
        TimelinePoint("last_stroke", stroke_at),
        TimelinePoint("last_commit", commit_at),
        TimelinePoint("last_push", push_at),
    ]

    # Ages relative to now
    for p in points:
        if p.at is not None:
            p.age_seconds = round(t_now - p.at, 1)
            p.age_str = format_age(p.age_seconds)

    # Gaps
    stroke_age = points[0].age_seconds
    commit_age = points[1].age_seconds
    push_age = points[2].age_seconds

    stroke_to_commit = None
    if stroke_at is not None and commit_at is not None:
        stroke_to_commit = abs(commit_at - stroke_at)

    commit_to_push = None
    if commit_at is not None and push_at is not None:
        commit_to_push = abs(commit_at - push_at)

    s_status, s_detail = classify_gap(stroke_age, STROKE_HEALTHY, STROKE_DEGRADED)
    c_status, c_detail = classify_gap(commit_age, COMMIT_HEALTHY, COMMIT_DEGRADED)
    p_status, p_detail = classify_gap(push_age, PUSH_HEALTHY, PUSH_DEGRADED)

    gaps = [
        Gap("stroke_to_now", stroke_age, s_status, s_detail),
        Gap("commit_to_now", commit_age, c_status, c_detail),
        Gap("push_to_now", push_age, p_status, p_detail),
        Gap("stroke_to_commit", stroke_to_commit,
            *classify_gap(stroke_to_commit, COMMIT_HEALTHY, COMMIT_DEGRADED)),
        Gap("commit_to_push", commit_to_push,
            *classify_gap(commit_to_push, PUSH_HEALTHY, PUSH_DEGRADED)),
    ]

    # Overall status is the worst individual gap
    severity = {"healthy": 0, "degraded": 1, "stalled": 2, "unknown": 1}
    worst = max(gaps, key=lambda g: severity.get(g.status, 0))

    return {
        "now": datetime.fromtimestamp(t_now, tz=timezone.utc).isoformat(),
        "points": [asdict(p) for p in points],
        "gaps": [asdict(g) for g in gaps],
        "overall": worst.status,
        "worst_gap": worst.name,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo = find_repo_root(args.repo)
    report = build_timeline(repo)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Pipeline timeline ({report['overall']}):")
        print()
        for p in report["points"]:
            print(f"  {p['label']:>16}: {p['age_str']:>8} ago  ({p['at_iso'] or 'never'})")
        print()
        for g in report["gaps"]:
            print(f"  {g['name']:>20}: {g['status']:>9}  {g['detail']}")
        print()
        print(f"  overall: {report['overall']}  (worst: {report['worst_gap']})")

    return {"healthy": 0, "degraded": 1, "stalled": 2, "unknown": 1}.get(
        report["overall"], 1
    )


if __name__ == "__main__":
    sys.exit(main())
