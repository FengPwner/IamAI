#!/usr/bin/env python3
"""commit_health_pulse.py — measure commit rhythm health over a time window.

A healthy self-writing repo commits at a steady cadence.  When the writer
stalls and a caretaker batch-catches-up, commits arrive in bursts: several
within seconds, then silence for hours.  This tool quantifies that pattern.

Algorithm:
    1. Collect commits within the last `hours` hours (default 24).
    2. Compute inter-commit gaps in seconds.
    3. Classify each gap as:
         steady  — within [0.5×, 2×] the expected cadence
         burst   — shorter than 0.5× cadence (rapid-fire recovery)
         gap     — longer than 2× cadence (writer was silent)
    4. Produce a PulseReport with:
         health_score — 0.0 (all bursts/gaps) to 1.0 (all steady)
         burst_ratio  — fraction of gaps that are bursts
         gap_ratio    — fraction of gaps that are silence
         pulse_label  — one of: steady, recovering, erratic, stalled

Exit codes:
    0 — analysis succeeded
    1 — git error or repo not found
    2 — no commits found in the requested window

Usage:
    python3 tools/commit_health_pulse.py
    python3 tools/commit_health_pulse.py --hours 12
    python3 tools/commit_health_pulse.py --cadence 600 --json
    python3 tools/commit_health_pulse.py --repo /path/to/IamAI
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_HOURS = 24
DEFAULT_CADENCE_SEC = 600  # 10 minutes — the batch commit interval


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CommitPulse:
    short_hash: str
    timestamp: str          # ISO-8601
    gap_seconds: float      # seconds since previous commit (0 for first)
    label: str              # steady | burst | gap


@dataclass
class PulseReport:
    repo: str
    window_hours: float
    cadence_seconds: int
    total_commits: int
    total_gaps: int
    steady_count: int
    burst_count: int
    gap_count: int
    health_score: float     # 0.0–1.0
    burst_ratio: float
    gap_ratio: float
    pulse_label: str        # steady | recovering | erratic | stalled
    longest_gap_seconds: float
    shortest_gap_seconds: float
    pulses: List[CommitPulse]


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------

def find_repo_root(start: str = ".") -> Path:
    """Walk up to find a .git directory."""
    p = Path(start).resolve()
    for parent in [p] + list(p.parents):
        if (parent / ".git").is_dir():
            return parent
    raise FileNotFoundError(f"No git repo found from {start}")


def get_commits_in_window(repo: Path, hours: float) -> List[tuple]:
    """Return list of (short_hash, datetime) for commits in the last N hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    try:
        result = subprocess.run(
            [
                "git", "log", "--format=%h %aI",
                f"--since={since_str}",
                "--reverse",  # oldest first so we can compute forward gaps
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise RuntimeError(f"git error: {exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")

    commits = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        short_hash, ts_str = parts
        # Parse ISO timestamp
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            commits.append((short_hash, dt))
        except ValueError:
            continue
    return commits


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_gap(gap_seconds: float, cadence: int) -> str:
    """Classify a single inter-commit gap."""
    if gap_seconds == 0:
        return "steady"
    ratio = gap_seconds / cadence
    if ratio < 0.5:
        return "burst"
    elif ratio > 2.0:
        return "gap"
    return "steady"


def classify_pulse(health_score: float, burst_ratio: float, gap_ratio: float) -> str:
    """Assign a human-readable pulse label."""
    if health_score >= 0.8:
        return "steady"
    elif health_score >= 0.5 and burst_ratio > gap_ratio:
        return "recovering"
    elif health_score >= 0.3:
        return "erratic"
    else:
        return "stalled"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze_pulse(repo: Path, hours: float, cadence: int) -> PulseReport:
    """Run the full pulse analysis."""
    commits = get_commits_in_window(repo, hours)

    if not commits:
        return PulseReport(
            repo=str(repo),
            window_hours=hours,
            cadence_seconds=cadence,
            total_commits=0,
            total_gaps=0,
            steady_count=0,
            burst_count=0,
            gap_count=0,
            health_score=0.0,
            burst_ratio=0.0,
            gap_ratio=0.0,
            pulse_label="stalled",
            longest_gap_seconds=0.0,
            shortest_gap_seconds=0.0,
            pulses=[],
        )

    pulses: List[CommitPulse] = []
    # First commit has no gap
    pulses.append(CommitPulse(
        short_hash=commits[0][0],
        timestamp=commits[0][1].isoformat(),
        gap_seconds=0.0,
        label="steady",
    ))

    gaps: List[float] = []
    steady = 1  # first commit counts as steady
    burst = 0
    gap_n = 0

    for i in range(1, len(commits)):
        delta = (commits[i][1] - commits[i - 1][1]).total_seconds()
        gaps.append(delta)
        label = classify_gap(delta, cadence)
        if label == "steady":
            steady += 1
        elif label == "burst":
            burst += 1
        else:
            gap_n += 1
        pulses.append(CommitPulse(
            short_hash=commits[i][0],
            timestamp=commits[i][1].isoformat(),
            gap_seconds=delta,
            label=label,
        ))

    total_gaps = len(gaps)
    health_score = steady / max(len(pulses), 1)
    burst_ratio = burst / max(total_gaps, 1)
    gap_ratio = gap_n / max(total_gaps, 1)
    pulse_label = classify_pulse(health_score, burst_ratio, gap_ratio)

    return PulseReport(
        repo=str(repo),
        window_hours=hours,
        cadence_seconds=cadence,
        total_commits=len(commits),
        total_gaps=total_gaps,
        steady_count=steady,
        burst_count=burst,
        gap_count=gap_n,
        health_score=round(health_score, 4),
        burst_ratio=round(burst_ratio, 4),
        gap_ratio=round(gap_ratio, 4),
        pulse_label=pulse_label,
        longest_gap_seconds=max(gaps) if gaps else 0.0,
        shortest_gap_seconds=min(gaps) if gaps else 0.0,
        pulses=pulses,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Measure commit rhythm health."
    )
    parser.add_argument(
        "--repo", default=".", help="Path to git repo (default: cwd)"
    )
    parser.add_argument(
        "--hours", type=float, default=DEFAULT_HOURS,
        help=f"Look-back window in hours (default {DEFAULT_HOURS})"
    )
    parser.add_argument(
        "--cadence", type=int, default=DEFAULT_CADENCE_SEC,
        help=f"Expected commit cadence in seconds (default {DEFAULT_CADENCE_SEC})"
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output JSON instead of human-readable text"
    )
    args = parser.parse_args()

    try:
        repo = find_repo_root(args.repo)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        report = analyze_pulse(repo, args.hours, args.cadence)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if report.total_commits == 0:
        print("No commits found in the requested window.", file=sys.stderr)
        sys.exit(2)

    if args.as_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"Commit Health Pulse — {repo.name}")
        print(f"  window:    {report.window_hours}h")
        print(f"  cadence:   {report.cadence_seconds}s")
        print(f"  commits:   {report.total_commits}")
        print(f"  health:    {report.health_score:.2%}")
        print(f"  pulse:     {report.pulse_label}")
        print(f"  steady:    {report.steady_count}")
        print(f"  bursts:    {report.burst_count} ({report.burst_ratio:.0%})")
        print(f"  gaps:      {report.gap_count} ({report.gap_ratio:.0%})")
        if report.total_gaps:
            print(f"  shortest:  {report.shortest_gap_seconds:.0f}s")
            print(f"  longest:   {report.longest_gap_seconds:.0f}s")


if __name__ == "__main__":
    main()
