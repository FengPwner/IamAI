#!/usr/bin/env python3
"""writer_productivity_index.py — measure effective writing throughput.

The writing system produces strokes at a nominal cadence (one every 15s).
But real productivity is lower than theoretical maximum because of:

  - container recycling (writer down, no output)
  - restart overhead (SSH rescue, process spawn, cadence re-acquisition)
  - cadence drift (strokes arriving late or in bursts)

This tool answers: "what fraction of the system's potential output is
actually reaching the repository?"

Input:
    data/strokes.jsonl     (stroke log with timestamps)
    git log                (commit timestamps for efficiency calc)

Output:

    Writer Productivity Index
    ───────────────────────────────────────
    Period:                 24h
    Total strokes:          400
    Net strokes/hour:       16.7    (theoretical max: 240)
    Diversity score:        0.82    (Shannon entropy, 0=monotype, 1=uniform)
    Efficiency ratio:       91%     (time producing vs. total time)
    Productivity index:     0.06    (composite, 0=idle, 1=perfect)

Formula:
    output_rate = net_strokes / hours
    rate_score  = min(output_rate / theoretical_max, 1.0)
    pi          = rate_score * diversity * efficiency

    theoretical_max defaults to 240 strokes/hour (one per 15s).

Usage:
    python3 tools/writer_productivity_index.py
    python3 tools/writer_productivity_index.py --hours 48
    python3 tools/writer_productivity_index.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def parse_iso(s: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    if not s:
        return None
    s = s.strip()
    # Handle 'Z' suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Try parsing with offset
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Stroke extraction
# ---------------------------------------------------------------------------

def load_strokes(strokes_path: Path) -> list[dict[str, Any]]:
    """Load strokes from JSONL file, skipping malformed lines."""
    strokes = []
    if not strokes_path.exists():
        return strokes
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = parse_iso(entry.get("at", ""))
                if ts is not None:
                    entry["_ts"] = ts
                    strokes.append(entry)
            except (json.JSONDecodeError, TypeError):
                continue
    strokes.sort(key=lambda e: e["_ts"])
    return strokes


def filter_strokes_by_window(
    strokes: list[dict[str, Any]],
    hours: float,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return strokes within the last `hours` hours."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    return [s for s in strokes if s["_ts"] >= cutoff]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_net_strokes_per_hour(
    strokes: list[dict[str, Any]],
    hours: float,
) -> float:
    """Net strokes per hour over the given window."""
    if hours <= 0 or not strokes:
        return 0.0
    return len(strokes) / hours


def compute_diversity_score(strokes: list[dict[str, Any]]) -> float:
    """Shannon entropy of stroke kind distribution, normalized to [0, 1].

    Returns 0 if all strokes are the same kind, 1 if perfectly uniform
    across all observed kinds.
    """
    if len(strokes) <= 1:
        return 0.0

    kind_counts: dict[str, int] = {}
    for s in strokes:
        kind = s.get("kind", "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    n = len(strokes)
    entropy = 0.0
    for count in kind_counts.values():
        if count > 0:
            p = count / n
            entropy -= p * math.log2(p)

    # Normalize by max possible entropy (log2 of number of kinds)
    k = len(kind_counts)
    if k <= 1:
        return 0.0
    max_entropy = math.log2(k)
    return entropy / max_entropy if max_entropy > 0 else 0.0


def compute_efficiency_ratio(
    strokes: list[dict[str, Any]],
    hours: float,
    restart_timestamps: list[datetime] | None = None,
    restart_overhead_minutes: float = 5.0,
) -> float:
    """Fraction of wall-clock time the writer was actually producing.

    Accounts for restart overhead: each restart event deducts
    `restart_overhead_minutes` from productive time.
    """
    if hours <= 0:
        return 0.0

    total_minutes = hours * 60
    downtime_minutes = 0.0

    if restart_timestamps:
        downtime_minutes += len(restart_timestamps) * restart_overhead_minutes

    # Estimate gaps from stroke timestamps: if the gap between consecutive
    # strokes exceeds 2x the nominal cadence (15s), count the excess as
    # downtime.
    if len(strokes) >= 2:
        nominal_gap = timedelta(seconds=30)  # 2x the 15s cadence
        for i in range(1, len(strokes)):
            gap = strokes[i]["_ts"] - strokes[i - 1]["_ts"]
            if gap > nominal_gap:
                excess = (gap - nominal_gap).total_seconds() / 60
                downtime_minutes += excess

    productive_minutes = max(total_minutes - downtime_minutes, 0)
    return productive_minutes / total_minutes


def extract_restart_timestamps_from_git(
    repo_root: Path,
) -> list[datetime]:
    """Extract restart event timestamps from git log commit messages."""
    try:
        result = subprocess.run(
            [
                "git", "log", "--oneline", "--format=%aI %s",
                "--all",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    restart_pattern = re.compile(
        r"(restart|resurrect|recovery|catch-up|recovery)", re.IGNORECASE
    )
    timestamps = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        # Format: "2026-11-03T12:00:00+00:00 commit message"
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        ts_str, msg = parts
        if restart_pattern.search(msg):
            ts = parse_iso(ts_str)
            if ts is not None:
                timestamps.append(ts)
    return sorted(timestamps)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------

def compute_productivity_index(
    net_rate: float,
    diversity: float,
    efficiency: float,
    theoretical_max: float = 240.0,
) -> float:
    """Composite productivity index in [0, 1].

    Combines:
    - output rate (normalized against theoretical max)
    - diversity score
    - efficiency ratio
    """
    rate_score = min(net_rate / theoretical_max, 1.0) if theoretical_max > 0 else 0.0
    return rate_score * diversity * efficiency


def build_report(
    strokes: list[dict[str, Any]],
    hours: float,
    restart_timestamps: list[datetime] | None = None,
    theoretical_max: float = 240.0,
    restart_overhead_minutes: float = 5.0,
) -> dict[str, Any]:
    """Build a complete productivity report."""
    net_rate = compute_net_strokes_per_hour(strokes, hours)
    diversity = compute_diversity_score(strokes)
    efficiency = compute_efficiency_ratio(
        strokes, hours, restart_timestamps, restart_overhead_minutes
    )
    pi = compute_productivity_index(net_rate, diversity, efficiency, theoretical_max)

    # Kind breakdown
    kind_counts: dict[str, int] = {}
    for s in strokes:
        kind = s.get("kind", "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    return {
        "period_hours": hours,
        "total_strokes": len(strokes),
        "net_strokes_per_hour": round(net_rate, 2),
        "theoretical_max": theoretical_max,
        "diversity_score": round(diversity, 4),
        "efficiency_ratio": round(efficiency, 4),
        "productivity_index": round(pi, 6),
        "kind_breakdown": kind_counts,
        "restart_count": len(restart_timestamps) if restart_timestamps else 0,
    }


def render_report(report: dict[str, Any]) -> str:
    """Format the report as human-readable text."""
    lines = [
        "Writer Productivity Index",
        "─" * 40,
        f"Period:                 {report['period_hours']}h",
        f"Total strokes:          {report['total_strokes']}",
        f"Net strokes/hour:       {report['net_strokes_per_hour']}"
        f"    (theoretical max: {report['theoretical_max']})",
        f"Diversity score:        {report['diversity_score']}"
        f"    (0=monotype, 1=uniform)",
        f"Efficiency ratio:       {report['efficiency_ratio']:.0%}"
        f"     (time producing vs. total time)",
        f"Productivity index:     {report['productivity_index']}"
        f"    (composite, 0=idle, 1=perfect)",
        "",
        "Kind breakdown:",
    ]
    for kind, count in sorted(
        report["kind_breakdown"].items(), key=lambda x: -x[1]
    ):
        lines.append(f"  {kind:20s} {count}")

    if report["restart_count"] > 0:
        lines.append(f"\nRestart events:         {report['restart_count']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure writing system productivity index."
    )
    parser.add_argument(
        "--hours", type=float, default=24,
        help="Lookback window in hours (default: 24)",
    )
    parser.add_argument(
        "--strokes", type=str, default="data/strokes.jsonl",
        help="Path to strokes JSONL file",
    )
    parser.add_argument(
        "--theoretical-max", type=float, default=240.0,
        help="Theoretical max strokes/hour (default: 240 = one per 15s)",
    )
    parser.add_argument(
        "--restart-overhead", type=float, default=5.0,
        help="Minutes of overhead per restart event (default: 5)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of text",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    strokes_path = repo_root / args.strokes

    strokes = load_strokes(strokes_path)
    strokes = filter_strokes_by_window(strokes, args.hours)

    restart_timestamps = extract_restart_timestamps_from_git(repo_root)
    # Filter restart timestamps to the same window
    if restart_timestamps:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=args.hours)
        restart_timestamps = [t for t in restart_timestamps if t >= cutoff]

    report = build_report(
        strokes,
        args.hours,
        restart_timestamps,
        args.theoretical_max,
        args.restart_overhead,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_report(report))


if __name__ == "__main__":
    main()
