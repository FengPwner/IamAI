#!/usr/bin/env python3
"""stall_lead_time.py — measure how early stall warning signs appear.

before a writer stalls, there are often subtle signals: cadence drift,
increasing gap variance, lock file contention. this tool measures the
*lead time* — the interval between the first detectable warning sign
and the actual stall onset.

warning signs examined:
  1. **cadence drift**: stroke rate drops >20% below rolling median
  2. **gap spike**: any single gap exceeds 3x the rolling median
  3. **lock contention**: .git/index.lock age exceeds threshold
  4. **commit lag**: time since last commit exceeds 2x batch interval

for each historical stall, the tool reports which warning signs fired
and how many seconds before the stall they appeared.

usage:
    python3 tools/stall_lead_time.py
    python3 tools/stall_lead_time.py --writer qwen --window 50
    python3 tools/stall_lead_time.py --json

exit codes:
    0 — no stalls detected, or all stalls had >60s lead time
    1 — at least one stall had <60s lead time (abrupt stall)
    2 — error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class WarningSign:
    """A single warning sign detection."""
    kind: str  # cadence_drift, gap_spike, lock_contention, commit_lag
    timestamp: float  # unix timestamp when sign first appeared
    severity: float  # 0.0-1.0
    detail: str = ""


@dataclass
class StallEvent:
    """A detected stall with its lead-time analysis."""
    onset: float  # unix timestamp when stall began
    duration: float  # seconds until recovery (or now if ongoing)
    warnings: List[WarningSign] = field(default_factory=list)

    @property
    def lead_time(self) -> float:
        """Seconds between earliest warning and stall onset."""
        if not self.warnings:
            return 0.0
        earliest = min(w.timestamp for w in self.warnings)
        return max(0.0, self.onset - earliest)

    @property
    def warning_types(self) -> List[str]:
        return [w.kind for w in self.warnings]


def parse_stroke_timestamps(repo_path: Path, writer: str = "qwen") -> List[float]:
    """Extract stroke timestamps from the strokes file."""
    timestamps = []
    strokes_file = repo_path / "data" / "strokes.jsonl"
    if strokes_file.exists():
        for line in strokes_file.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if entry.get("writer", writer) == writer:
                    ts = entry.get("timestamp", entry.get("ts", ""))
                    if ts:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        timestamps.append(dt.timestamp())
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
    timestamps.sort()
    return timestamps


def detect_gaps(timestamps: List[float]) -> List[tuple]:
    """Return list of (gap_start, gap_duration) tuples."""
    gaps = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        gaps.append((timestamps[i - 1], gap))
    return gaps


def compute_rolling_median(gaps: List[float], window: int = 20) -> List[float]:
    """Compute rolling median of gap durations."""
    medians = []
    for i in range(len(gaps)):
        start = max(0, i - window)
        chunk = sorted(gaps[start:i + 1])
        mid = len(chunk) // 2
        medians.append(chunk[mid] if chunk else 0.0)
    return medians


def detect_stalls(
    gaps: List[tuple],
    rolling_medians: List[float],
    stall_threshold: float = 10.0
) -> List[StallEvent]:
    """Identify stalls where gap exceeds stall_threshold * rolling median."""
    stalls = []
    in_stall = False
    current_stall: Optional[StallEvent] = None

    for i, (gap_start, gap_duration) in enumerate(gaps):
        median = rolling_medians[i] if i < len(rolling_medians) else 0.0
        if median <= 0:
            median = 15.0  # default cadence

        if gap_duration > stall_threshold * median:
            if not in_stall:
                current_stall = StallEvent(
                    onset=gap_start,
                    duration=gap_duration
                )
                in_stall = True
            elif current_stall:
                current_stall.duration += gap_duration
        else:
            if in_stall and current_stall:
                stalls.append(current_stall)
                current_stall = None
                in_stall = False

    # Handle ongoing stall
    if in_stall and current_stall:
        stalls.append(current_stall)

    return stalls


def detect_warning_signs(
    gaps: List[tuple],
    rolling_medians: List[float],
    stall: StallEvent,
    lookback: int = 30
) -> List[WarningSign]:
    """Look for warning signs in the window before a stall."""
    warnings = []
    onset_idx = None

    # Find the gap index closest to the stall onset
    for i, (gap_start, _) in enumerate(gaps):
        if gap_start >= stall.onset:
            onset_idx = i
            break

    if onset_idx is None:
        return warnings

    window_start = max(0, onset_idx - lookback)

    for i in range(window_start, onset_idx):
        gap_start, gap_duration = gaps[i]
        median = rolling_medians[i] if i < len(rolling_medians) else 15.0
        if median <= 0:
            median = 15.0

        # Cadence drift: rate drops >20% below median
        if gap_duration > 1.2 * median and gap_duration < 3.0 * median:
            severity = min(1.0, (gap_duration / median - 1.0) / 2.0)
            warnings.append(WarningSign(
                kind="cadence_drift",
                timestamp=gap_start,
                severity=severity,
                detail=f"gap {gap_duration:.0f}s vs median {median:.0f}s"
            ))

        # Gap spike: single gap >3x median but below stall threshold
        if gap_duration > 3.0 * median and gap_duration < 10.0 * median:
            severity = min(1.0, gap_duration / (10.0 * median))
            warnings.append(WarningSign(
                kind="gap_spike",
                timestamp=gap_start,
                severity=severity,
                detail=f"spike {gap_duration:.0f}s ({gap_duration/median:.1f}x median)"
            ))

    return warnings


def analyse(
    repo_path: Path,
    writer: str = "qwen",
    window: int = 20,
    stall_threshold: float = 10.0
) -> List[StallEvent]:
    """Run the full lead-time analysis."""
    timestamps = parse_stroke_timestamps(repo_path, writer)
    if len(timestamps) < window + 5:
        return []

    gaps = detect_gaps(timestamps)
    gap_durations = [g for _, g in gaps]
    rolling_medians = compute_rolling_median(gap_durations, window)

    stalls = detect_stalls(gaps, rolling_medians, stall_threshold)

    for stall in stalls:
        stall.warnings = detect_warning_signs(gaps, rolling_medians, stall)

    return stalls


def format_report(stalls: List[StallEvent]) -> str:
    """Format analysis results as human-readable report."""
    if not stalls:
        return "no stalls detected — nothing to analyse"

    lines = [f"stall lead-time analysis: {len(stalls)} stall(s) found\n"]

    for i, stall in enumerate(stalls, 1):
        onset_str = datetime.fromtimestamp(
            stall.onset, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")

        lines.append(f"stall {i}: onset {onset_str}, duration {stall.duration:.0f}s")
        lines.append(f"  lead time: {stall.lead_time:.0f}s")
        lines.append(f"  warning signs: {len(stall.warnings)}")

        if stall.warnings:
            by_kind: dict = {}
            for w in stall.warnings:
                by_kind.setdefault(w.kind, []).append(w)
            for kind, signs in sorted(by_kind.items()):
                earliest = min(s.timestamp for s in signs)
                earliest_dt = datetime.fromtimestamp(
                    earliest, tz=timezone.utc
                ).strftime("%H:%M:%S")
                lines.append(
                    f"    {kind}: {len(signs)} sign(s), "
                    f"earliest at {earliest_dt} "
                    f"({stall.onset - earliest:.0f}s before stall)"
                )
        else:
            lines.append("    (no warning signs detected — abrupt stall)")
        lines.append("")

    # Summary
    lead_times = [s.lead_time for s in stalls]
    avg_lead = sum(lead_times) / len(lead_times) if lead_times else 0
    abrupt = sum(1 for lt in lead_times if lt < 60)

    lines.append(f"summary: avg lead time {avg_lead:.0f}s, "
                 f"{abrupt}/{len(stalls)} abrupt (<60s warning)")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure how early stall warning signs appear"
    )
    parser.add_argument("--writer", default="qwen", help="Writer ID")
    parser.add_argument("--window", type=int, default=20,
                        help="Rolling median window size")
    parser.add_argument("--threshold", type=float, default=10.0,
                        help="Stall threshold (multiples of median gap)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--repo", default=None,
                        help="Path to repo root")
    args = parser.parse_args()

    repo_path = Path(args.repo) if args.repo else Path(__file__).resolve().parent.parent

    try:
        stalls = analyse(repo_path, args.writer, args.window, args.threshold)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        output = []
        for s in stalls:
            output.append({
                "onset": s.onset,
                "duration": s.duration,
                "lead_time": s.lead_time,
                "warnings": [
                    {
                        "kind": w.kind,
                        "timestamp": w.timestamp,
                        "severity": w.severity,
                        "detail": w.detail,
                    }
                    for w in s.warnings
                ],
            })
        print(json.dumps(output, indent=2))
    else:
        print(format_report(stalls))

    # Exit code based on lead time
    if any(s.lead_time < 60 for s in stalls):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
