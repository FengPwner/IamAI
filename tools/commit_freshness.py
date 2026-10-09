#!/usr/bin/env python3
"""Measure how fresh the latest commit is and whether the pipeline is healthy.

A commit is "fresh" when its age (now − committer_date) is less than one
batch interval.  A commit that is twice the interval old means the committer
died silently; three times means the whole pipeline collapsed.

    python3 tools/commit_freshness.py                   # human-readable
    python3 tools/commit_freshness.py --json            # machine-readable
    python3 tools/commit_freshness.py --interval 600    # custom window

Exit codes:
    0  fresh   — latest commit is within one interval
    1  stale   — latest commit is older than one interval
    2  dead    — latest commit is older than three intervals
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


# ── Data ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FreshnessReport:
    commit_age_seconds: float
    commit_age_human: str
    latest_commit_hash: str
    latest_commit_message: str
    interval: int
    status: str          # "fresh" | "stale" | "dead"
    uncommitted_files: int
    stale_threshold: float
    dead_threshold: float


# ── Helpers ──────────────────────────────────────────────────────────


def _run(cmd: list[str], cwd: Path) -> str:
    """Run a subprocess and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, cwd=str(cwd)
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _human_duration(seconds: float) -> str:
    """Convert seconds to a short human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _classify(age: float, interval: int) -> str:
    """Classify freshness based on commit age vs interval."""
    if age <= interval:
        return "fresh"
    if age <= interval * 3:
        return "stale"
    return "dead"


def _count_uncommitted(repo: Path) -> int:
    """Count files with uncommitted changes."""
    output = _run(["git", "status", "--porcelain"], repo)
    if not output:
        return 0
    return len(output.splitlines())


# ── Core ─────────────────────────────────────────────────────────────


def measure(interval: int = 600, repo: Path | None = None) -> FreshnessReport:
    """Measure commit freshness for the given repository."""
    repo = repo or REPO
    now = time.time()

    # Latest commit info
    commit_epoch = _run(
        ["git", "log", "-1", "--format=%ct"], repo
    )
    commit_hash = _run(
        ["git", "log", "-1", "--format=%h"], repo
    )
    commit_msg = _run(
        ["git", "log", "-1", "--format=%s"], repo
    )

    if commit_epoch:
        try:
            age = now - float(commit_epoch)
        except ValueError:
            age = float("inf")
    else:
        age = float("inf")

    status = _classify(age, interval)
    uncommitted = _count_uncommitted(repo)

    return FreshnessReport(
        commit_age_seconds=round(age, 1),
        commit_age_human=_human_duration(age),
        latest_commit_hash=commit_hash or "?",
        latest_commit_message=commit_msg or "(no commits)",
        interval=interval,
        status=status,
        uncommitted_files=uncommitted,
        stale_threshold=float(interval),
        dead_threshold=float(interval * 3),
    )


def as_markdown(report: FreshnessReport) -> str:
    """Render a freshness report as a short markdown summary."""
    icon = {"fresh": "🟢", "stale": "🟡", "dead": "🔴"}.get(report.status, "⚪")
    lines = [
        f"## Commit Freshness {icon} {report.status}",
        "",
        f"- **age:** {report.commit_age_human} ({report.commit_age_seconds:.0f}s)",
        f"- **latest:** `{report.latest_commit_hash}` {report.latest_commit_message}",
        f"- **interval:** {report.interval}s  stale>{report.stale_threshold:.0f}s  dead>{report.dead_threshold:.0f}s",
        f"- **uncommitted:** {report.uncommitted_files} file(s)",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=int, default=600, help="expected commit interval in seconds")
    ap.add_argument("--json", action="store_true", help="dump the whole report as JSON")
    args = ap.parse_args()

    report = measure(interval=args.interval)
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(as_markdown(report))

    if report.status == "dead":
        return 2
    if report.status == "stale":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
