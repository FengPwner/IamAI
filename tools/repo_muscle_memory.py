#!/usr/bin/env python3
"""repo_muscle_memory.py — measure which repo tools are practiced vs atrophied.

Biological metaphor: muscle memory is the capacity built through repeated
practice.  Skills you exercise regularly become automatic; skills you neglect
fade.  A repository has the same dynamic — tools that are actively maintained
sharpen over time, while untouched tools rot into technical debt.

This tool analyses the commit history to classify each tracked Python tool
into one of four fitness levels:

    WELL_PRACTICED  — committed ≥ 5 times, touched within last 7 days
    EXERCISED       — committed ≥ 2 times, touched within last 14 days
    NEGLECTED       — committed ≥ 1 time,  last touched 14–30 days ago
    ATROPHIED       — never committed, or last touched > 30 days ago

Aggregate metrics:
    muscle_score    — weighted average across all tools (0–100)
    practiced_ratio — fraction of tools that are WELL_PRACTICED or EXERCISED
    atrophy_count   — number of tools classified ATROPHIED
    strongest       — most practiced tool (by commit count)
    weakest         — most neglected tool (longest since last touch)

Usage:
    python3 tools/repo_muscle_memory.py
    python3 tools/repo_muscle_memory.py --days 60
    python3 tools/repo_muscle_memory.py --json

Exit codes:
    0 — analysis complete
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"


@dataclass
class ToolFitness:
    """Fitness record for a single tool file."""
    name: str
    path: str
    commit_count: int = 0
    days_since_touch: float = float("inf")
    intervals_days: list[float] = field(default_factory=list)
    classification: str = "ATROPHIED"

    @property
    def consistency(self) -> float:
        """Stddev of touch intervals in days. Lower = more regular practice."""
        if len(self.intervals_days) < 2:
            return float("inf")
        n = len(self.intervals_days)
        mean = sum(self.intervals_days) / n
        variance = sum((x - mean) ** 2 for x in self.intervals_days) / n
        return variance ** 0.5


def discover_tools(tools_dir: Path = TOOLS_DIR) -> list[str]:
    """List all .py files in the tools directory (excluding test files)."""
    if not tools_dir.exists():
        return []
    return sorted(
        f.name for f in tools_dir.iterdir()
        if f.suffix == ".py" and not f.name.startswith("test_")
    )


def parse_git_log_batch(
    repo_path: Path,
    filepaths: list[str],
    now: datetime,
) -> dict[str, list[datetime]]:
    """Get commit timestamps for multiple files using a single git log call.

    Uses --name-only to associate commits with files in one pass, which is
    far faster than running git log per file with --follow.
    """
    result_map: dict[str, list[datetime]] = {fp: [] for fp in filepaths}
    try:
        # Single git call: get all commits with timestamps and changed files
        proc = subprocess.run(
            ["git", "log", "--format=COMMIT:%at", "--name-only",
             "--"] + filepaths,
            capture_output=True,
            text=True,
            cwd=str(repo_path),
            timeout=120,
        )
        if proc.returncode != 0:
            return result_map

        current_ts: int | None = None
        for line in proc.stdout.split("\n"):
            line = line.strip()
            if line.startswith("COMMIT:"):
                try:
                    current_ts = int(line[7:])
                except ValueError:
                    current_ts = None
            elif current_ts is not None and line:
                # This is a filename touched in the current commit
                if line in result_map:
                    result_map[line].append(
                        datetime.fromtimestamp(current_ts, tz=timezone.utc)
                    )

        # Sort each file's commit list
        for fp in result_map:
            result_map[fp].sort()

        return result_map
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return result_map


def classify(
    commit_count: int,
    days_since_touch: float,
) -> str:
    """Classify a tool's fitness level based on activity."""
    if commit_count >= 5 and days_since_touch <= 7:
        return "WELL_PRACTICED"
    if commit_count >= 2 and days_since_touch <= 14:
        return "EXERCISED"
    if commit_count >= 1 and days_since_touch <= 30:
        return "NEGLECTED"
    return "ATROPHIED"


def fitness_score(cls: str) -> int:
    """Numeric score for a classification (for aggregate averaging)."""
    return {
        "WELL_PRACTICED": 100,
        "EXERCISED": 70,
        "NEGLECTED": 30,
        "ATROPHIED": 0,
    }.get(cls, 0)


def analyze(
    repo_path: Path = REPO,
    tools_dir: Path = TOOLS_DIR,
    days: int = 90,
    now: datetime | None = None,
) -> dict:
    """Run full muscle memory analysis across all tools."""
    if now is None:
        now = datetime.now(tz=timezone.utc)

    tool_names = discover_tools(tools_dir)
    if not tool_names:
        return {
            "tool_count": 0,
            "muscle_score": 0,
            "practiced_ratio": 0.0,
            "atrophy_count": 0,
            "strongest": "",
            "weakest": "",
            "tools": [],
        }

    cutoff = now - timedelta(days=days)

    # Batch git log for all files in one call
    rel_paths = [f"tools/{name}" for name in tool_names]
    git_data = parse_git_log_batch(repo_path, rel_paths, now)

    fitnesses: list[ToolFitness] = []

    for name, rel_path in zip(tool_names, rel_paths):
        commits = git_data.get(rel_path, [])

        # Filter to within the analysis window
        recent = [c for c in commits if c >= cutoff]
        commit_count = len(recent)

        if recent:
            last_touch = max(recent)
            days_since = (now - last_touch).total_seconds() / 86400

            # Compute intervals between consecutive commits
            intervals = []
            sorted_commits = sorted(recent)
            for i in range(1, len(sorted_commits)):
                gap = (sorted_commits[i] - sorted_commits[i - 1]).total_seconds() / 86400
                intervals.append(gap)
        else:
            days_since = float("inf")
            intervals = []

        cls = classify(commit_count, days_since)
        fitnesses.append(ToolFitness(
            name=name,
            path=rel_path,
            commit_count=commit_count,
            days_since_touch=round(days_since, 1) if days_since != float("inf") else float("inf"),
            intervals_days=intervals,
            classification=cls,
        ))

    # Aggregate metrics
    scores = [fitness_score(f.classification) for f in fitnesses]
    muscle_score = sum(scores) / len(scores) if scores else 0

    practiced = sum(1 for f in fitnesses if f.classification in ("WELL_PRACTICED", "EXERCISED"))
    practiced_ratio = practiced / len(fitnesses) if fitnesses else 0.0
    atrophy_count = sum(1 for f in fitnesses if f.classification == "ATROPHIED")

    # Strongest (most commits) and weakest (longest since touch)
    strongest = max(fitnesses, key=lambda f: f.commit_count).name if fitnesses else ""
    touched = [f for f in fitnesses if f.days_since_touch != float("inf")]
    weakest = max(fitnesses, key=lambda f: f.days_since_touch if f.days_since_touch != float("inf") else -1).name if fitnesses else ""

    return {
        "tool_count": len(fitnesses),
        "muscle_score": round(muscle_score, 1),
        "practiced_ratio": round(practiced_ratio, 4),
        "atrophy_count": atrophy_count,
        "strongest": strongest,
        "weakest": weakest,
        "tools": [
            {
                "name": f.name,
                "commit_count": f.commit_count,
                "days_since_touch": f.days_since_touch,
                "consistency": round(f.consistency, 2) if f.consistency != float("inf") else None,
                "classification": f.classification,
            }
            for f in sorted(fitnesses, key=lambda f: fitness_score(f.classification), reverse=True)
        ],
    }


def format_text(result: dict) -> str:
    """Produce a human-readable report."""
    lines = [
        "=== Repo Muscle Memory ===",
        f"  tools analyzed:   {result['tool_count']}",
        f"  muscle score:     {result['muscle_score']:.1f} / 100",
        f"  practiced ratio:  {result['practiced_ratio']:.0%}",
        f"  atrophy count:    {result['atrophy_count']}",
        f"  strongest:        {result['strongest']}",
        f"  weakest:          {result['weakest']}",
        "",
        "  Fitness breakdown:",
    ]
    for t in result["tools"]:
        touch = f"{t['days_since_touch']:.1f}d ago" if t["days_since_touch"] != float("inf") else "never"
        cons = f"±{t['consistency']:.1f}d" if t["consistency"] is not None else "n/a"
        lines.append(
            f"    {t['classification']:15s}  {t['name']:40s}  "
            f"{t['commit_count']:3d} commits  {touch:12s}  consistency {cons}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=90, help="analysis window in days")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--repo", type=str, default=str(REPO), help="repo root path")
    args = ap.parse_args()

    try:
        result = analyze(
            repo_path=Path(args.repo),
            tools_dir=Path(args.repo) / "tools",
            days=args.days,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
