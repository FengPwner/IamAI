"""push_debt.py — quantify the operational cost of unpushed commits.

when the push pipeline is blocked (deploy key missing, network down,
credential expired), commits accumulate locally. the longer they sit
unpushed, the higher the risk of data loss if the container recycles.

push_debt answers three questions:

  1. how many commits are unpushed right now?
  2. how old is the oldest unpushed commit?
  3. what is the aggregate risk score (debt) and its severity?

the debt score is:

    debt = unpushed_count × mean_age_hours

this captures both volume and staleness. 50 commits from the last hour
is less concerning than 50 commits from three days ago — the latter
has survived more container recycle cycles.

severity levels:

    LOW        debt < 50         — normal buffer, push when convenient
    MEDIUM     50 ≤ debt < 200   — growing backlog, investigate soon
    HIGH       200 ≤ debt < 1000 — significant risk, prioritize fix
    CRITICAL   debt ≥ 1000       — data loss likely on recycle

the trend tracker records periodic snapshots to data/push_debt.jsonl
and computes whether debt is increasing, stable, or draining.

usage:
    python3 -m iamai.push_debt              # human-readable report
    python3 -m iamai.push_debt --json       # machine-readable output
    python3 -m iamai.push_debt --trend 5    # last 5 snapshots

design: this module observes state; it never auto-fixes. fixes belong
in push_recovery_orchestrator.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
DEBT_LOG = DATA_DIR / "push_debt.jsonl"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Trend(str, Enum):
    INCREASING = "INCREASING"
    STABLE = "STABLE"
    DRAINING = "DRAINING"
    UNKNOWN = "UNKNOWN"


@dataclass
class DebtSnapshot:
    """a single measurement of push debt."""
    timestamp: str
    unpushed_count: int
    oldest_age_hours: float
    mean_age_hours: float
    debt_score: float
    severity: str
    trend: str = "UNKNOWN"


def _run_git(*args: str) -> str:
    """run a git command in the repo, return stdout."""
    result = subprocess.run(
        ["git", "-C", str(REPO)] + list(args),
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def _parse_commit_timestamp(line: str) -> Optional[datetime]:
    """parse an ISO timestamp from git log --format=%aI."""
    line = line.strip()
    if not line:
        return None
    try:
        return datetime.fromisoformat(line)
    except (ValueError, TypeError):
        return None


def get_unpushed_commits(remote: str = "origin", branch: str = "main") -> list[str]:
    """return the list of unpushed commit hashes."""
    output = _run_git("log", "--format=%H", f"{remote}/{branch}..HEAD")
    if not output:
        return []
    return [h for h in output.split("\n") if h.strip()]


def get_unpushed_ages(remote: str = "origin", branch: str = "main") -> list[float]:
    """return ages in hours for every unpushed commit."""
    output = _run_git("log", "--format=%aI", f"{remote}/{branch}..HEAD")
    if not output:
        return []

    now = datetime.now(timezone.utc)
    ages = []
    for line in output.split("\n"):
        ts = _parse_commit_timestamp(line)
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600.0
            ages.append(max(0.0, age_hours))
    return ages


def compute_severity(debt_score: float) -> Severity:
    """classify debt score into severity level."""
    if debt_score < 50:
        return Severity.LOW
    elif debt_score < 200:
        return Severity.MEDIUM
    elif debt_score < 1000:
        return Severity.HIGH
    else:
        return Severity.CRITICAL


def compute_trend(snapshots: list[DebtSnapshot], window: int = 5) -> Trend:
    """determine debt trend from recent snapshots.

    compares the mean debt of the first half vs the second half of
    the window. if the second half is >10% lower, debt is draining.
    if >10% higher, debt is increasing. otherwise stable.
    """
    if len(snapshots) < 2:
        return Trend.UNKNOWN

    recent = snapshots[-window:]
    if len(recent) < 2:
        return Trend.UNKNOWN

    mid = len(recent) // 2
    first_half = [s.debt_score for s in recent[:mid]]
    second_half = [s.debt_score for s in recent[mid:]]

    mean_first = sum(first_half) / len(first_half)
    mean_second = sum(second_half) / len(second_half)

    if mean_first == 0:
        return Trend.STABLE if mean_second == 0 else Trend.INCREASING

    ratio = mean_second / mean_first
    if ratio < 0.9:
        return Trend.DRAINING
    elif ratio > 1.1:
        return Trend.INCREASING
    else:
        return Trend.STABLE


def measure_debt(remote: str = "origin", branch: str = "main") -> DebtSnapshot:
    """take a snapshot of current push debt."""
    now = datetime.now(timezone.utc).isoformat()

    commits = get_unpushed_commits(remote, branch)
    count = len(commits)

    if count == 0:
        return DebtSnapshot(
            timestamp=now,
            unpushed_count=0,
            oldest_age_hours=0.0,
            mean_age_hours=0.0,
            debt_score=0.0,
            severity=Severity.LOW.value,
            trend=Trend.UNKNOWN.value,
        )

    ages = get_unpushed_ages(remote, branch)
    if not ages:
        return DebtSnapshot(
            timestamp=now,
            unpushed_count=count,
            oldest_age_hours=0.0,
            mean_age_hours=0.0,
            debt_score=0.0,
            severity=Severity.LOW.value,
            trend=Trend.UNKNOWN.value,
        )

    oldest = max(ages)
    mean_age = sum(ages) / len(ages)
    debt = count * mean_age
    severity = compute_severity(debt)

    history = load_snapshots()
    current = DebtSnapshot(
        timestamp=now,
        unpushed_count=count,
        oldest_age_hours=round(oldest, 2),
        mean_age_hours=round(mean_age, 2),
        debt_score=round(debt, 2),
        severity=severity.value,
    )
    history.append(current)
    trend = compute_trend(history)
    current.trend = trend.value

    return current


def record_snapshot(snapshot: DebtSnapshot) -> None:
    """append a snapshot to the debt log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEBT_LOG, "a") as f:
        f.write(json.dumps(asdict(snapshot)) + "\n")


def load_snapshots(limit: int = 0) -> list[DebtSnapshot]:
    """load snapshots from the debt log. limit=0 means all."""
    if not DEBT_LOG.exists():
        return []

    snapshots = []
    for line in DEBT_LOG.read_text().strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            snapshots.append(DebtSnapshot(**data))
        except (json.JSONDecodeError, TypeError, KeyError):
            continue

    if limit > 0:
        return snapshots[-limit:]
    return snapshots


def format_report(snapshot: DebtSnapshot) -> str:
    """format a snapshot as a human-readable report."""
    lines = [
        "=== Push Debt Report ===",
        f"  timestamp:    {snapshot.timestamp}",
        f"  unpushed:     {snapshot.unpushed_count} commits",
        f"  oldest:       {snapshot.oldest_age_hours:.1f} hours",
        f"  mean age:     {snapshot.mean_age_hours:.1f} hours",
        f"  debt score:   {snapshot.debt_score:.1f}",
        f"  severity:     {snapshot.severity}",
        f"  trend:        {snapshot.trend}",
    ]

    if snapshot.severity == Severity.CRITICAL.value:
        lines.append("")
        lines.append("  WARNING CRITICAL: data loss risk is high.")
        lines.append("  fix the push pipeline immediately.")
    elif snapshot.severity == Severity.HIGH.value:
        lines.append("")
        lines.append("  WARNING HIGH: backlog is growing.")
        lines.append("  investigate push blockage soon.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="measure push debt")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--record", action="store_true",
                        help="record snapshot to log")
    parser.add_argument("--trend", type=int, default=0,
                        help="show last N snapshots")
    parser.add_argument("--remote", default="origin", help="remote name")
    parser.add_argument("--branch", default="main", help="branch name")
    args = parser.parse_args()

    if args.trend > 0:
        snapshots = load_snapshots(limit=args.trend)
        if args.json:
            print(json.dumps([asdict(s) for s in snapshots], indent=2))
        else:
            for s in snapshots:
                print(f"{s.timestamp}  count={s.unpushed_count}  "
                      f"debt={s.debt_score:.1f}  sev={s.severity}  "
                      f"trend={s.trend}")
        return 0

    snapshot = measure_debt(remote=args.remote, branch=args.branch)

    if args.record:
        record_snapshot(snapshot)

    if args.json:
        print(json.dumps(asdict(snapshot), indent=2))
    else:
        print(format_report(snapshot))

    if snapshot.severity == Severity.CRITICAL.value:
        return 3
    elif snapshot.severity == Severity.HIGH.value:
        return 2
    elif snapshot.severity == Severity.MEDIUM.value:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
