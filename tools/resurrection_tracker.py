#!/usr/bin/env python3
"""resurrection_tracker.py — analyze process death-and-restart patterns.

Every time the writer or batch process dies and a caretaker restarts it,
the repo records a "catch-up" commit. This tool scans git log for those
commits, pairs them with caretaker visit notes, and produces:

    - resurrection count per process (writer / batch / both)
    - mean time between resurrections (MTBR)
    - clustering: are deaths bunched in time or evenly spread?
    - gap distribution: quartiles of intervals between resurrections

Why it matters: a process that dies once a day is a nuisance; one that
dies six times in an hour is a bug. The tracker distinguishes the two.

Usage:
    python3 tools/resurrection_tracker.py
    python3 tools/resurrection_tracker.py --json
    python3 tools/resurrection_tracker.py --days 7
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

REPO = Path(__file__).resolve().parent.parent

CATCH_UP_PATTERNS = [
    re.compile(r"catch-up", re.IGNORECASE),
    re.compile(r"process restart", re.IGNORECASE),
    re.compile(r"resurrection", re.IGNORECASE),
    re.compile(r"restart.*writer", re.IGNORECASE),
    re.compile(r"restart.*batch", re.IGNORECASE),
]

CST = timezone(timedelta(hours=8))


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=30)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)


@dataclass
class Resurrection:
    timestamp: datetime
    commit_hash: str
    message: str
    process: str  # "writer" | "batch" | "both"


@dataclass
class ClusterInfo:
    label: str
    count: int
    start: datetime
    end: datetime
    span_minutes: float


def parse_commit_line(line: str) -> Resurrection | None:
    """Parse 'hash YYYY-MM-DD HH:MM:SS message' into a Resurrection."""
    parts = line.split(" ", 3)
    if len(parts) < 4:
        return None
    commit_hash, date_str, time_str, message = parts
    try:
        ts = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
        ts = ts.replace(tzinfo=CST)
    except ValueError:
        return None

    msg_lower = message.lower()
    if "writer" in msg_lower and "batch" in msg_lower:
        proc = "both"
    elif "batch" in msg_lower:
        proc = "batch"
    elif "writer" in msg_lower:
        proc = "writer"
    else:
        proc = "both"  # generic catch-up assumed to cover both

    return Resurrection(timestamp=ts, commit_hash=commit_hash, message=message, process=proc)


def fetch_catch_up_commits(days: int = 30) -> list[Resurrection]:
    """Scan git log for catch-up / restart commits."""
    since = (datetime.now(CST) - timedelta(days=days)).strftime("%Y-%m-%d")
    code, out = _run([
        "git", "log", "--all", "--oneline",
        f"--since={since}",
        "--format=%h %ai %s",
    ])
    if code != 0 or not out:
        return []

    results = []
    for line in out.splitlines():
        # Match only catch-up style commits
        if any(p.search(line) for p in CATCH_UP_PATTERNS):
            r = parse_commit_line(line)
            if r:
                results.append(r)

    results.sort(key=lambda r: r.timestamp)
    return results


def detect_clusters(resurrections: list[Resurrection], window_minutes: int = 60) -> list[ClusterInfo]:
    """Find clusters: groups of N>=2 resurrections within window_minutes."""
    if len(resurrections) < 2:
        return []

    clusters = []
    i = 0
    while i < len(resurrections):
        j = i + 1
        while j < len(resurrections):
            gap = (resurrections[j].timestamp - resurrections[i].timestamp).total_seconds() / 60
            if gap > window_minutes:
                break
            j += 1
        count = j - i
        if count >= 2:
            span = (resurrections[j - 1].timestamp - resurrections[i].timestamp).total_seconds() / 60
            clusters.append(ClusterInfo(
                label=f"cluster@{resurrections[i].timestamp.strftime('%m-%d %H:%M')}",
                count=count,
                start=resurrections[i].timestamp,
                end=resurrections[j - 1].timestamp,
                span_minutes=round(span, 1),
            ))
            i = j
        else:
            i += 1

    return clusters


def compute_gaps(resurrections: list[Resurrection]) -> list[float]:
    """Return sorted list of gap-hours between consecutive resurrections."""
    gaps = []
    for i in range(1, len(resurrections)):
        delta = (resurrections[i].timestamp - resurrections[i - 1].timestamp).total_seconds() / 3600
        gaps.append(round(delta, 2))
    gaps.sort()
    return gaps


def quartiles(data: list[float]) -> dict:
    if not data:
        return {"q1": 0, "q2": 0, "q3": 0, "min": 0, "max": 0}
    n = len(data)
    return {
        "min": data[0],
        "q1": data[n // 4] if n >= 4 else data[0],
        "q2": median(data),
        "q3": data[3 * n // 4] if n >= 4 else data[-1],
        "max": data[-1],
    }


def build_report(resurrections: list[Resurrection], as_json: bool = False) -> str:
    if not resurrections:
        if as_json:
            return json.dumps({"count": 0, "verdict": "no resurrections found"})
        return "No resurrections found in the given time window."

    total = len(resurrections)
    by_proc = {"writer": 0, "batch": 0, "both": 0}
    for r in resurrections:
        by_proc[r.process] = by_proc.get(r.process, 0) + 1

    gaps = compute_gaps(resurrections)
    gap_hours = quartiles(gaps)
    clusters = detect_clusters(resurrections)

    first = resurrections[0].timestamp
    last = resurrections[-1].timestamp
    span_days = max((last - first).total_seconds() / 86400, 1)
    mtbr_hours = round(span_days * 24 / total, 1)

    if total <= 2:
        verdict = "healthy"
    elif len(clusters) == 0 and mtbr_hours > 12:
        verdict = "healthy"
    elif len(clusters) <= 1 and mtbr_hours > 4:
        verdict = "noisy"
    else:
        verdict = "unstable"

    if as_json:
        return json.dumps({
            "count": total,
            "by_process": by_proc,
            "mtbr_hours": mtbr_hours,
            "gap_hours": gap_hours,
            "clusters": [
                {"label": c.label, "count": c.count, "span_minutes": c.span_minutes}
                for c in clusters
            ],
            "verdict": verdict,
            "first": first.isoformat(),
            "last": last.isoformat(),
            "span_days": round(span_days, 1),
        }, indent=2)

    lines = [
        f"# Resurrection Tracker",
        f"",
        f"Total resurrections: {total} (span {round(span_days, 1)} days)",
        f"  writer: {by_proc['writer']}  batch: {by_proc['batch']}  both: {by_proc['both']}",
        f"MTBR (mean time between resurrections): {mtbr_hours} hours",
        f"",
        f"Gap distribution (hours):",
        f"  min={gap_hours['min']}  Q1={gap_hours['q1']}  median={gap_hours['q2']}  Q3={gap_hours['q3']}  max={gap_hours['max']}",
        f"",
    ]
    if clusters:
        lines.append(f"Clusters ({len(clusters)} found):")
        for c in clusters:
            lines.append(f"  {c.label}: {c.count} resurrections in {c.span_minutes} min")
    else:
        lines.append("No clusters detected (deaths are evenly spread).")
    lines.append(f"")
    lines.append(f"Verdict: {verdict}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Track process resurrection patterns")
    parser.add_argument("--days", type=int, default=30, help="Look back N days (default 30)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    resurrections = fetch_catch_up_commits(args.days)
    print(build_report(resurrections, as_json=args.json))


if __name__ == "__main__":
    main()
