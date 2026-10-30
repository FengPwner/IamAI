#!/usr/bin/env python3
"""push_debt_calculator.py — quantify the cost of unpushed commits.

push debt is the gap between local work and remote visibility. When the
deploy key breaks or the network hiccups, commits pile up locally. They
are real work, but to the rest of the world they do not exist.

this tool measures three dimensions of push debt:

  1. VOLUME   — how many commits are unpushed
  2. AGE      — how old is the oldest unpushed commit (in hours)
  3. DENSITY  — commits per hour since the last successful push

combined into a single "push debt score" from 0.0 to 1.0:

  score = min(1.0, 0.4*volume_frac + 0.3*age_frac + 0.3*density_frac)

  where:
    volume_frac = min(1.0, unpushed / 100)       — 100 commits is max debt
    age_frac    = min(1.0, hours_since_push / 48) — 48 hours is max age
    density_frac = min(1.0, commits_per_hour / 20) — 20/hr is dense

the score answers one question: how bad is the backup?

  0.0 - 0.2 : healthy (normal operating lag)
  0.2 - 0.5 : concerning (push is noticeably behind)
  0.5 - 0.8 : critical (significant work at risk)
  0.8 - 1.0 : emergency (days of work invisible to remote)

usage:
    python3 tools/push_debt_calculator.py              # human-readable
    python3 tools/push_debt_calculator.py --json        # machine-readable
    python3 tools/push_debt_calculator.py --timeline     # show oldest/newest unpushed

exit codes:
    0 — score < 0.5 (manageable)
    1 — score >= 0.5 (needs attention)
    2 — error (could not read git state)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent


@dataclass
class PushDebt:
    unpushed_count: int
    oldest_unpushed_ts: Optional[str]
    newest_unpushed_ts: Optional[str]
    hours_since_last_push: float
    commits_per_hour: float
    volume_frac: float
    age_frac: float
    density_frac: float
    score: float
    severity: str
    total_local_commits: int


def _git(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return result.returncode, result.stdout.strip()


def _count_unpushed() -> int:
    """Count commits ahead of origin/main."""
    code, out = _git("rev-list", "--count", "origin/main..HEAD")
    if code != 0:
        # fallback: count all commits if no remote tracking
        code2, out2 = _git("rev-list", "--count", "HEAD")
        return int(out2) if code2 == 0 else 0
    return int(out) if out.isdigit() else 0


def _count_total_commits() -> int:
    code, out = _git("rev-list", "--count", "HEAD")
    return int(out) if code == 0 and out.isdigit() else 0


def _oldest_unpushed() -> Optional[str]:
    """Get timestamp of the oldest unpushed commit."""
    code, out = _git("log", "--reverse", "--format=%aI", "origin/main..HEAD")
    if code != 0 or not out:
        return None
    lines = out.strip().split("\n")
    return lines[0] if lines else None


def _newest_unpushed() -> Optional[str]:
    """Get timestamp of the newest unpushed commit."""
    code, out = _git("log", "-1", "--format=%aI", "origin/main..HEAD")
    if code != 0 or not out:
        return None
    return out.strip()


def _last_push_time() -> Optional[str]:
    """Get timestamp of the most recent commit on origin/main."""
    code, out = _git("log", "-1", "--format=%aI", "origin/main")
    if code != 0 or not out:
        return None
    return out.strip()


def _parse_ts(ts_str: str) -> Optional[float]:
    """Parse ISO timestamp to epoch seconds."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def calculate_debt() -> PushDebt:
    """Calculate the full push debt profile."""
    unpushed = _count_unpushed()
    total = _count_total_commits()
    oldest = _oldest_unpushed()
    newest = _newest_unpushed()
    last_push = _last_push_time()

    now = time.time()

    # hours since last successful push
    hours_since_push = 0.0
    if last_push:
        push_epoch = _parse_ts(last_push)
        if push_epoch:
            hours_since_push = max(0.0, (now - push_epoch) / 3600.0)

    # commits per hour
    commits_per_hour = 0.0
    if hours_since_push > 0 and unpushed > 0:
        commits_per_hour = unpushed / hours_since_push

    # fractional scores
    volume_frac = min(1.0, unpushed / 100.0)
    age_frac = min(1.0, hours_since_push / 48.0)
    density_frac = min(1.0, commits_per_hour / 20.0)

    # combined score
    score = min(1.0, 0.4 * volume_frac + 0.3 * age_frac + 0.3 * density_frac)

    # severity label
    if score < 0.2:
        severity = "healthy"
    elif score < 0.5:
        severity = "concerning"
    elif score < 0.8:
        severity = "critical"
    else:
        severity = "emergency"

    return PushDebt(
        unpushed_count=unpushed,
        oldest_unpushed_ts=oldest,
        newest_unpushed_ts=newest,
        hours_since_last_push=round(hours_since_push, 2),
        commits_per_hour=round(commits_per_hour, 2),
        volume_frac=round(volume_frac, 4),
        age_frac=round(age_frac, 4),
        density_frac=round(density_frac, 4),
        score=round(score, 4),
        severity=severity,
        total_local_commits=total,
    )


def format_human(debt: PushDebt) -> str:
    """Format push debt for human reading."""
    lines = [
        "=== Push Debt Report ===",
        f"  unpushed commits : {debt.unpushed_count} / {debt.total_local_commits} total",
        f"  oldest unpushed  : {debt.oldest_unpushed_ts or 'N/A'}",
        f"  newest unpushed  : {debt.newest_unpushed_ts or 'N/A'}",
        f"  hours since push : {debt.hours_since_last_push}",
        f"  commits/hour     : {debt.commits_per_hour}",
        "",
        f"  volume fraction  : {debt.volume_frac:.2%}",
        f"  age fraction     : {debt.age_frac:.2%}",
        f"  density fraction : {debt.density_frac:.2%}",
        "",
        f"  PUSH DEBT SCORE  : {debt.score:.4f}  [{debt.severity.upper()}]",
    ]

    if debt.severity in ("critical", "emergency"):
        lines.append("")
        lines.append("  ACTION REQUIRED: register deploy key or restore push access.")
        lines.append(f"  {debt.unpushed_count} commits of work are invisible to remote.")

    return "\n".join(lines)


def format_json(debt: PushDebt) -> str:
    """Format push debt as JSON."""
    return json.dumps(asdict(debt), indent=2)


def format_timeline(debt: PushDebt) -> str:
    """Format a timeline view of the unpushed range."""
    lines = [
        "=== Push Debt Timeline ===",
        f"  last push        : {debt.hours_since_last_push}h ago",
        f"  oldest unpushed  : {debt.oldest_unpushed_ts or 'N/A'}",
        f"  newest unpushed  : {debt.newest_unpushed_ts or 'N/A'}",
        f"  unpushed count   : {debt.unpushed_count}",
        f"  accumulation rate: {debt.commits_per_hour} commits/hour",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Calculate push debt score")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--timeline", action="store_true", help="Timeline view")
    args = parser.parse_args()

    try:
        debt = calculate_debt()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(format_json(debt))
    elif args.timeline:
        print(format_timeline(debt))
    else:
        print(format_human(debt))

    # exit code based on severity
    sys.exit(1 if debt.score >= 0.5 else 0)


if __name__ == "__main__":
    main()
