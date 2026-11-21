#!/usr/bin/env python3
"""stroke_yield_analyzer.py — quantify productivity loss during writer stalls.

every stall gap represents strokes that *should* have been written but weren't.
this module measures the difference between expected output (based on cadence)
and actual output (zero during the gap), producing a "yield ratio" that captures
how much of the writer's potential was realized over a given period.

concepts:
    - expected strokes: gap_duration / cadence_seconds
    - actual strokes during gap: 0 (by definition, it's a stall)
    - yield ratio: actual_total / expected_total over a time window
    - lost strokes: sum of expected strokes across all stall gaps

why this matters:
    cadence_stall_detector says "the writer stopped."
    resurrection_detector says "the writer restarted."
    neither says "here's how much was lost."

    a writer that stalls once for 10 minutes loses ~40 strokes at 15s cadence.
    a writer that stalls ten times for 1 minute each loses the same count
    but in a different pattern — fragmentation vs. blackout.

    yield analysis turns "the writer had a bad day" into numbers you can
    track, compare, and set thresholds on.

usage:
    python3 tools/stroke_yield_analyzer.py
    python3 tools/stroke_yield_analyzer.py --repo /path/to/IamAI
    python3 tools/stroke_yield_analyzer.py --cadence 15 --stall-threshold 300
    python3 tools/stroke_yield_analyzer.py --window 24h --json

exit codes:
    0 — yield above threshold (healthy)
    1 — yield below threshold (degraded)
    2 — cannot determine (missing data)
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root containing data/."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / "data" / "strokes.jsonl").exists():
            return parent
    return p


def parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def load_strokes(repo: Path) -> list[dict[str, Any]]:
    """Load all strokes from the JSONL file."""
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return []
    results = []
    with open(strokes_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    record = json.loads(line)
                    # normalize: some records use 'ts' instead of 'at'
                    if "at" not in record and "ts" in record:
                        record["at"] = record["ts"]
                    if "at" in record:
                        results.append(record)
                except json.JSONDecodeError:
                    continue
    return results


def compute_stall_gaps(
    strokes: list[dict[str, Any]],
    stall_threshold_sec: float = 300.0,
) -> list[dict[str, Any]]:
    """Find all gaps between consecutive strokes that exceed the stall threshold.

    Returns a list of gap records, each containing:
        - start: timestamp of the stroke before the gap
        - end: timestamp of the stroke after the gap
        - duration_sec: length of the gap in seconds
        - expected_strokes: how many strokes should have been written (at cadence)
    """
    if len(strokes) < 2:
        return []

    gaps = []
    for i in range(len(strokes) - 1):
        ts_before = parse_timestamp(strokes[i]["at"])
        ts_after = parse_timestamp(strokes[i + 1]["at"])
        duration = (ts_after - ts_before).total_seconds()

        if duration > stall_threshold_sec:
            gaps.append({
                "index": i,
                "start": strokes[i]["at"],
                "end": strokes[i + 1]["at"],
                "duration_sec": duration,
                "seq_before": strokes[i].get("seq"),
                "seq_after": strokes[i + 1].get("seq"),
            })

    return gaps


def compute_yield(
    strokes: list[dict[str, Any]],
    cadence_sec: float = 15.0,
    stall_threshold_sec: float = 300.0,
    window_hours: float | None = None,
) -> dict[str, Any]:
    """Compute yield metrics for the writer over the given time window.

    Returns a dict with:
        - window_start / window_end: time bounds analyzed
        - total_duration_sec: seconds in the window
        - expected_strokes: total strokes expected at the given cadence
        - actual_strokes: total strokes actually written
        - stall_gaps: list of gaps exceeding the threshold
        - total_stall_time_sec: sum of all stall gap durations
        - lost_strokes: strokes lost during stall gaps
        - yield_ratio: actual / expected (1.0 = perfect, 0.0 = nothing written)
        - yield_pct: yield_ratio as percentage
        - fragmentation: number of separate stall events
        - pattern: "clean" | "fragmented" | "blackout" | "empty"
    """
    if not strokes:
        return {
            "window_start": None,
            "window_end": None,
            "total_duration_sec": 0,
            "expected_strokes": 0,
            "actual_strokes": 0,
            "stall_gaps": [],
            "total_stall_time_sec": 0,
            "lost_strokes": 0,
            "yield_ratio": 0.0,
            "yield_pct": 0.0,
            "fragmentation": 0,
            "pattern": "empty",
        }

    # determine window
    all_times = [parse_timestamp(s["at"]) for s in strokes]
    latest = max(all_times)
    earliest = min(all_times)

    if window_hours is not None:
        window_start = latest - timedelta(hours=window_hours)
    else:
        window_start = earliest

    # filter strokes within window
    window_strokes = [
        s for s in strokes
        if parse_timestamp(s["at"]) >= window_start
    ]

    if not window_strokes:
        return {
            "window_start": window_start.isoformat(),
            "window_end": latest.isoformat(),
            "total_duration_sec": 0,
            "expected_strokes": 0,
            "actual_strokes": 0,
            "stall_gaps": [],
            "total_stall_time_sec": 0,
            "lost_strokes": 0,
            "yield_ratio": 0.0,
            "yield_pct": 0.0,
            "fragmentation": 0,
            "pattern": "empty",
        }

    window_start_actual = parse_timestamp(window_strokes[0]["at"])
    window_end_actual = parse_timestamp(window_strokes[-1]["at"])
    total_duration = (window_end_actual - window_start_actual).total_seconds()

    if total_duration <= 0:
        return {
            "window_start": window_strokes[0]["at"],
            "window_end": window_strokes[-1]["at"],
            "total_duration_sec": 0,
            "expected_strokes": 1,
            "actual_strokes": len(window_strokes),
            "stall_gaps": [],
            "total_stall_time_sec": 0,
            "lost_strokes": 0,
            "yield_ratio": 1.0,
            "yield_pct": 100.0,
            "fragmentation": 0,
            "pattern": "clean",
        }

    # expected strokes at the given cadence
    expected = max(1, total_duration / cadence_sec)
    actual = len(window_strokes)

    # find stall gaps within window
    stall_gaps = compute_stall_gaps(window_strokes, stall_threshold_sec)

    # compute expected strokes for each gap
    for gap in stall_gaps:
        gap["expected_strokes"] = gap["duration_sec"] / cadence_sec

    total_stall_time = sum(g["duration_sec"] for g in stall_gaps)
    lost_strokes = sum(g["expected_strokes"] for g in stall_gaps)

    yield_ratio = actual / expected if expected > 0 else 1.0
    yield_ratio = min(yield_ratio, 1.0)  # cap at 1.0

    fragmentation = len(stall_gaps)

    # classify the pattern
    if fragmentation == 0:
        pattern = "clean"
    elif total_stall_time > total_duration * 0.5:
        pattern = "blackout"
    elif fragmentation >= 3:
        pattern = "fragmented"
    else:
        pattern = "clean"  # a couple of small stalls is still mostly clean

    return {
        "window_start": window_strokes[0]["at"],
        "window_end": window_strokes[-1]["at"],
        "total_duration_sec": total_duration,
        "expected_strokes": round(expected, 1),
        "actual_strokes": actual,
        "stall_gaps": stall_gaps,
        "total_stall_time_sec": round(total_stall_time, 1),
        "lost_strokes": round(lost_strokes, 1),
        "yield_ratio": round(yield_ratio, 4),
        "yield_pct": round(yield_ratio * 100, 2),
        "fragmentation": fragmentation,
        "pattern": pattern,
    }


def format_report(result: dict[str, Any]) -> str:
    """Format the yield analysis as a human-readable report."""
    if result["pattern"] == "empty":
        return "stroke yield analysis: no strokes found in window"

    lines = [
        "=== stroke yield analysis ===",
        f"window: {result['window_start']} → {result['window_end']}",
        f"duration: {result['total_duration_sec']:.0f}s ({result['total_duration_sec']/3600:.1f}h)",
        f"expected strokes: {result['expected_strokes']}",
        f"actual strokes:   {result['actual_strokes']}",
        f"lost strokes:     {result['lost_strokes']}",
        f"stall time:       {result['total_stall_time_sec']:.0f}s",
        f"stall events:     {result['fragmentation']}",
        f"yield:            {result['yield_pct']}%",
        f"pattern:          {result['pattern']}",
    ]

    if result["stall_gaps"]:
        lines.append("")
        lines.append("stall gaps:")
        for i, gap in enumerate(result["stall_gaps"], 1):
            dur_min = gap["duration_sec"] / 60
            lines.append(
                f"  {i}. {dur_min:.1f}min ({gap['start']} → {gap['end']}) "
                f"~{gap['expected_strokes']:.0f} strokes lost"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze stroke yield loss during writer stalls"
    )
    parser.add_argument(
        "--repo", type=str, default=None,
        help="path to repo root (default: auto-detect)"
    )
    parser.add_argument(
        "--cadence", type=float, default=15.0,
        help="expected seconds between strokes (default: 15)"
    )
    parser.add_argument(
        "--stall-threshold", type=float, default=300.0,
        help="seconds of silence before a gap counts as a stall (default: 300)"
    )
    parser.add_argument(
        "--window", type=str, default=None,
        help="time window to analyze (e.g., '24h', '7d', '48h')"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output as JSON"
    )
    parser.add_argument(
        "--threshold", type=float, default=80.0,
        help="yield percentage below which exit code is 1 (default: 80)"
    )
    args = parser.parse_args()

    repo = find_repo_root(Path(args.repo) if args.repo else None)
    strokes = load_strokes(repo)

    window_hours = None
    if args.window:
        w = args.window.lower()
        if w.endswith("h"):
            window_hours = float(w[:-1])
        elif w.endswith("d"):
            window_hours = float(w[:-1]) * 24
        else:
            window_hours = float(w)

    result = compute_yield(
        strokes,
        cadence_sec=args.cadence,
        stall_threshold_sec=args.stall_threshold,
        window_hours=window_hours,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    if result["pattern"] == "empty":
        sys.exit(2)
    elif result["yield_pct"] < args.threshold:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
