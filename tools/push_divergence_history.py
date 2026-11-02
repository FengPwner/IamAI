#!/usr/bin/env python3
"""push_divergence_history.py — analyze push rejection patterns from git history.

Scans caretaker visit notes in the commit log to find push-rejection events,
then produces a statistical report: how often pushes fail, which hours see the
most rejections, and what recovery methods were used.

This is a read-only diagnostic tool — it never modifies the repo.

Usage:
    python3 tools/push_divergence_history.py
    python3 tools/push_divergence_history.py --days 30
    python3 tools/push_divergence_history.py --json
    python3 tools/push_divergence_history.py --days 14 --json
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


# patterns that indicate a push rejection event in commit messages
REJECTION_PATTERNS = [
    re.compile(r"push\s+(?:was\s+)?rejected", re.IGNORECASE),
    re.compile(r"fetch\s+first", re.IGNORECASE),
    re.compile(r"rejected.*fetch\s+first", re.IGNORECASE),
    re.compile(r"push.*diverge", re.IGNORECASE),
    re.compile(r"remote.*ahead", re.IGNORECASE),
    re.compile(r"non-fast-forward", re.IGNORECASE),
    re.compile(r"Updates were rejected", re.IGNORECASE),
]

# patterns for recovery methods
RECOVERY_PATTERNS = {
    "stash-rebase-push": re.compile(
        r"stash.*rebase|rebase.*stash|stash-pull_rebase|auto.rebase", re.IGNORECASE
    ),
    "reset-hard": re.compile(
        r"reset\s+--hard|reset.*origin", re.IGNORECASE
    ),
    "pull-merge": re.compile(
        r"pull\s+--(?:no-rebase|merge)|merge.*origin", re.IGNORECASE
    ),
    "manual": re.compile(
        r"manual.*recovery|hand.*resolve|manual.*merge", re.IGNORECASE
    ),
    "retry": re.compile(
        r"retry|re-attempt|attempted\s+again", re.IGNORECASE
    ),
}


@dataclass
class RejectionEvent:
    """A single push rejection event extracted from git history."""
    commit_sha: str
    date: datetime
    visit_number: int | None
    recovery_method: str  # one of RECOVERY_PATTERNS keys or "unknown"
    message_snippet: str


@dataclass
class DivergenceReport:
    """Summary report of push divergence history."""
    total_rejections: int = 0
    total_visits: int = 0
    rejection_rate: float = 0.0  # rejections per visit
    by_hour: dict = field(default_factory=dict)
    by_recovery_method: dict = field(default_factory=dict)
    by_date: dict = field(default_factory=dict)
    recent_trend: str = "unknown"  # "improving" | "stable" | "worsening"
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_rejections": self.total_rejections,
            "total_visits": self.total_visits,
            "rejection_rate": round(self.rejection_rate, 3),
            "by_hour": self.by_hour,
            "by_recovery_method": self.by_recovery_method,
            "by_date": self.by_date,
            "recent_trend": self.recent_trend,
            "event_count": len(self.events),
        }


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory."""
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


def extract_visit_number(message: str) -> int | None:
    """Extract caretaker visit number from a commit message."""
    m = re.search(r"visit\s+(\d+)", message, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"caretaker[- ]visit[- ](\d+)", message, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def detect_recovery_method(message: str) -> str:
    """Determine the recovery method used from the commit message."""
    for method, pattern in RECOVERY_PATTERNS.items():
        if pattern.search(message):
            return method
    return "unknown"


def is_rejection_event(message: str) -> bool:
    """Check if a commit message describes a push rejection."""
    return any(p.search(message) for p in REJECTION_PATTERNS)


def get_visit_commits(repo: Path, days: int | None = None) -> list[tuple[str, datetime, str]]:
    """Get all caretaker visit commits with their SHA, date, and message.

    Returns list of (sha, datetime, message) tuples sorted by date ascending.
    """
    since_arg = []
    if days:
        since_date = datetime.now(timezone.utc) - timedelta(days=days)
        since_arg = [f"--since={since_date.strftime('%Y-%m-%d')}"]

    result = run_git(
        repo, "log", "--all", "--oneline", "--format=%H|%ai|%s",
        *since_arg,
    )
    if result.returncode != 0:
        return []

    commits = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, date_str, message = parts
        try:
            dt = datetime.strptime(date_str.strip()[:19], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        commits.append((sha.strip(), dt, message.strip()))

    commits.sort(key=lambda x: x[1])
    return commits


def get_commit_body(repo: Path, sha: str) -> str:
    """Get the full commit message body (not just subject)."""
    result = run_git(repo, "log", "-1", "--format=%B", sha)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def analyze_divergence(repo: Path, days: int | None = None) -> DivergenceReport:
    """Analyze push divergence history from git log."""
    report = DivergenceReport()

    commits = get_visit_commits(repo, days)
    if not commits:
        return report

    # count total visits
    visit_commits = [
        (sha, dt, msg) for sha, dt, msg in commits
        if extract_visit_number(msg) is not None
        or "caretaker visit" in msg.lower()
    ]
    report.total_visits = len(visit_commits)

    # also scan commit bodies for rejection mentions
    rejection_events: list[RejectionEvent] = []
    seen_shas = set()

    for sha, dt, subject in commits:
        # check subject line
        if is_rejection_event(subject):
            body = get_commit_body(repo, sha)
            full_msg = subject + "\n" + body
            event = RejectionEvent(
                commit_sha=sha[:8],
                date=dt,
                visit_number=extract_visit_number(subject) or extract_visit_number(body),
                recovery_method=detect_recovery_method(full_msg),
                message_snippet=subject[:120],
            )
            if sha not in seen_shas:
                rejection_events.append(event)
                seen_shas.add(sha)
            continue

        # check body for rejection mentions
        body = get_commit_body(repo, sha)
        if body and is_rejection_event(body):
            full_msg = subject + "\n" + body
            event = RejectionEvent(
                commit_sha=sha[:8],
                date=dt,
                visit_number=extract_visit_number(subject) or extract_visit_number(body),
                recovery_method=detect_recovery_method(full_msg),
                message_snippet=subject[:120],
            )
            if sha not in seen_shas:
                rejection_events.append(event)
                seen_shas.add(sha)

    report.total_rejections = len(rejection_events)
    report.rejection_rate = (
        report.total_rejections / report.total_visits
        if report.total_visits > 0
        else 0.0
    )

    # hour distribution
    hour_counter: Counter = Counter()
    for event in rejection_events:
        hour_counter[event.date.hour] += 1
    report.by_hour = dict(sorted(hour_counter.items()))

    # recovery method breakdown
    method_counter: Counter = Counter()
    for event in rejection_events:
        method_counter[event.recovery_method] += 1
    report.by_recovery_method = dict(method_counter.most_common())

    # date distribution (YYYY-MM-DD)
    date_counter: Counter = Counter()
    for event in rejection_events:
        date_counter[event.date.strftime("%Y-%m-%d")] += 1
    report.by_date = dict(sorted(date_counter.items()))

    # trend analysis: compare first half vs second half rejection rate
    if len(rejection_events) >= 4 and len(visit_commits) >= 4:
        midpoint = len(visit_commits) // 2
        first_half_visits = midpoint
        second_half_visits = len(visit_commits) - midpoint
        mid_date = visit_commits[midpoint][1]

        first_rejections = sum(1 for e in rejection_events if e.date < mid_date)
        second_rejections = sum(1 for e in rejection_events if e.date >= mid_date)

        first_rate = first_rejections / first_half_visits if first_half_visits > 0 else 0
        second_rate = second_rejections / second_half_visits if second_half_visits > 0 else 0

        if second_rate < first_rate * 0.7:
            report.recent_trend = "improving"
        elif second_rate > first_rate * 1.3:
            report.recent_trend = "worsening"
        else:
            report.recent_trend = "stable"

    report.events = [
        {
            "sha": e.commit_sha,
            "date": e.date.isoformat(),
            "visit": e.visit_number,
            "recovery": e.recovery_method,
            "snippet": e.message_snippet,
        }
        for e in rejection_events
    ]

    return report


def print_text_report(report: DivergenceReport) -> None:
    """Print a human-readable text report."""
    print("=" * 60)
    print("  Push Divergence History Report")
    print("=" * 60)
    print()
    print(f"  Total visits:       {report.total_visits}")
    print(f"  Total rejections:   {report.total_rejections}")
    print(f"  Rejection rate:     {report.rejection_rate:.1%}")
    print(f"  Trend:              {report.recent_trend}")
    print()

    if report.by_recovery_method:
        print("  Recovery Methods:")
        for method, count in report.by_recovery_method.items():
            pct = count / report.total_rejections * 100 if report.total_rejections else 0
            print(f"    {method:<25s} {count:>4d}  ({pct:.0f}%)")
        print()

    if report.by_hour:
        print("  Rejections by Hour (UTC):")
        for hour, count in sorted(report.by_hour.items()):
            bar = "#" * count
            print(f"    {hour:02d}:00  {count:>3d}  {bar}")
        print()

    if report.by_date:
        print("  Rejections by Date:")
        dates = sorted(report.by_date.items())
        # show last 14 at most
        for date, count in dates[-14:]:
            bar = "#" * count
            print(f"    {date}  {count:>3d}  {bar}")
        print()

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze push divergence history from git log."
    )
    parser.add_argument(
        "--repo", type=str, default=None, help="Path to git repo"
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Limit analysis to the last N days"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output JSON report"
    )
    args = parser.parse_args()

    repo = find_repo_root(Path(args.repo) if args.repo else None)
    report = analyze_divergence(repo, args.days)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_text_report(report)

    sys.exit(0)


if __name__ == "__main__":
    main()
