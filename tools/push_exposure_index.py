#!/usr/bin/env python3
"""CLI: push_exposure_index — quantify data-loss risk from unpushed commits.

Usage:
    python3 tools/push_exposure_index.py
    python3 tools/push_exposure_index.py --json

Exit codes:
    0  safe (score < 20)
    1  caution (score 20–49)
    2  warning (score 50–74)
    3  critical (score >= 75)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.push_exposure_index import exposure_index  # noqa: E402


def _git_unpushed_count(remote: str = "origin", branch: str = "main") -> int:
    try:
        out = subprocess.check_output(
            ["git", "rev-list", "--count", f"{remote}/{branch}..HEAD"],
            cwd=REPO, stderr=subprocess.DEVNULL, text=True,
        )
        return int(out.strip())
    except Exception:
        return 0


def _oldest_unpushed_hours(remote: str = "origin", branch: str = "main") -> float:
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%aI", "--reverse",
             f"{remote}/{branch}..HEAD"],
            cwd=REPO, stderr=subprocess.DEVNULL, text=True,
        )
        lines = out.strip().splitlines()
        if not lines:
            return 0.0
        oldest = datetime.fromisoformat(lines[0])
        now = datetime.now(timezone.utc)
        return (now - oldest).total_seconds() / 3600.0
    except Exception:
        return 0.0


def _estimate_work_hours(unpushed: int) -> float:
    """rough heuristic: 15 min per commit as average work time."""
    return unpushed * 0.25


def _blockage_hours() -> float:
    """read from push_blockage_state.json if available."""
    state_file = REPO / "data" / "push_blockage_state.json"
    if not state_file.exists():
        return 0.0
    try:
        data = json.loads(state_file.read_text())
        started = data.get("started_at", "")
        if not started:
            return 0.0
        start_dt = datetime.fromisoformat(started)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - start_dt).total_seconds() / 3600.0
    except Exception:
        return 0.0


_EXIT_CODES = {"safe": 0, "caution": 1, "warning": 2, "critical": 3}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute push exposure index."
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output JSON instead of human text.",
    )
    args = parser.parse_args()

    unpushed = _git_unpushed_count()
    oldest_h = _oldest_unpushed_hours()
    work_h = _estimate_work_hours(unpushed)
    block_h = _blockage_hours()

    result = exposure_index(
        unpushed_count=unpushed,
        oldest_unpushed_hours=oldest_h,
        estimated_work_hours=work_h,
        blockage_hours=block_h,
    )

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"push exposure index: {result['score']}/100  [{result['band'].upper()}]")
        print(f"  commit_volume:   {result['dimensions']['commit_volume']:.1f}")
        print(f"  time_span:       {result['dimensions']['time_span_hours']:.1f}")
        print(f"  work_hours_lost: {result['dimensions']['work_hours_lost']:.1f}")
        print(f"  blockage_age:    {result['dimensions']['blockage_age']:.1f}")
        print(f"  summary: {result['summary']}")

    return _EXIT_CODES.get(result["band"], 0)


if __name__ == "__main__":
    raise SystemExit(main())
