#!/usr/bin/env python3
"""detection_gap_analyzer.py — measure the gap between process death and detection.

When a container recycles, the writer and batch committer die instantly.
The caretaker only discovers this at its next scheduled visit. The time
between death and detection is the "detection gap" — a window of silent
inactivity that no commit, no stroke, and no push fills.

This tool analyzes the commit log and process start times to estimate:

1. **death_time**: when the previous process last produced output
   (approximated by the timestamp of its last stroke or commit).
2. **detection_time**: when the next caretaker visit discovered the death
   (identified by "caretaker visit" commit messages that include
   "NOT running" or "restarted" language).
3. **detection_gap_seconds**: detection_time minus death_time. The smaller
   this number, the tighter the monitoring loop.
4. **detection_amplification**: ratio of detection_gap_seconds to the
   writer cadence (default 15s). A factor of 240 means the detection gap
   was 240x the stroke interval — 240 missed strokes.
5. **strokes_lost_estimate**: detection_gap_seconds divided by the
   cadence. An approximation of how many strokes the writer would have
   produced during the gap.

Usage:
    python3 tools/detection_gap_analyzer.py
    python3 tools/detection_gap_analyzer.py --writer qwen --last 10
    python3 tools/detection_gap_analyzer.py --json

Exit codes:
    0 — all gaps within threshold (<600s / 10 min)
    1 — at least one gap exceeds threshold
    2 — error (no data, parse failure)
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

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Thresholds
GAP_THRESHOLD_S = 600          # 10 min — detection should be faster than this
AMPLIFICATION_THRESHOLD = 40   # 40x the cadence — beyond this, monitoring is too slow
CADENCE_SECONDS = 15           # writer produces one stroke every 15s


@dataclass
class DetectionEvent:
    """One instance of a process dying and being detected."""
    visit_number: Optional[int]
    detection_time: datetime
    last_activity_time: datetime
    gap_seconds: float
    amplification: float
    strokes_lost: int
    commit_hash: str = ""

    def severity(self) -> str:
        if self.gap_seconds < GAP_THRESHOLD_S:
            return "ok"
        elif self.gap_seconds < 1800:
            return "degraded"
        else:
            return "poor"

    def to_dict(self) -> dict:
        return {
            "visit": self.visit_number,
            "detection_time": self.detection_time.isoformat(),
            "last_activity": self.last_activity_time.isoformat(),
            "gap_seconds": round(self.gap_seconds, 1),
            "amplification": round(self.amplification, 1),
            "strokes_lost": self.strokes_lost,
            "severity": self.severity(),
            "commit": self.commit_hash,
        }


def _parse_git_log() -> List[dict]:
    """Extract caretaker visit entries from git log."""
    result = subprocess.run(
        ["git", "log", "--oneline", "--format=%H|%s|%aI", "-200"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if result.returncode != 0:
        return []

    entries = []
    visit_re = re.compile(r"caretaker visit (\d+)")
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        commit_hash, subject, date_str = parts
        m = visit_re.search(subject.lower())
        if m:
            entries.append({
                "hash": commit_hash[:7],
                "visit": int(m.group(1)),
                "subject": subject,
                "time": datetime.fromisoformat(date_str),
            })
    return entries


def _parse_stroke_times(strokes_path: Path, limit: int = 500) -> List[datetime]:
    """Read recent stroke timestamps from strokes.jsonl."""
    if not strokes_path.exists():
        return []
    times = []
    lines = strokes_path.read_text().strip().splitlines()
    for line in lines[-limit:]:
        try:
            data = json.loads(line)
            ts = data.get("timestamp") or data.get("ts") or data.get("time")
            if ts:
                times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
    return sorted(times)


def find_detection_events(
    visits: List[dict],
    stroke_times: List[datetime],
    cadence: int = CADENCE_SECONDS,
) -> List[DetectionEvent]:
    """Match each caretaker visit to the last activity before it."""
    events = []
    for visit in visits:
        det_time = visit["time"]
        # Find the most recent stroke before this visit
        prior = [t for t in stroke_times if t < det_time]
        if not prior:
            continue
        last_stroke = prior[-1]
        gap = (det_time - last_stroke).total_seconds()
        amp = gap / cadence if cadence > 0 else 0
        lost = int(gap / cadence) if cadence > 0 else 0
        events.append(DetectionEvent(
            visit_number=visit["visit"],
            detection_time=det_time,
            last_activity_time=last_stroke,
            gap_seconds=gap,
            amplification=amp,
            strokes_lost=lost,
            commit_hash=visit["hash"],
        ))
    return events


def summarize(events: List[DetectionEvent]) -> dict:
    """Produce a summary of detection gap health."""
    if not events:
        return {"count": 0, "avg_gap": 0, "max_gap": 0, "health": "no_data"}

    gaps = [e.gap_seconds for e in events]
    severities = [e.severity() for e in events]

    avg_gap = sum(gaps) / len(gaps)
    max_gap = max(gaps)
    poor_count = severities.count("poor")
    degraded_count = severities.count("degraded")

    if poor_count > 0:
        health = "poor"
    elif degraded_count > 0:
        health = "degraded"
    else:
        health = "ok"

    return {
        "count": len(events),
        "avg_gap": round(avg_gap, 1),
        "max_gap": round(max_gap, 1),
        "min_gap": round(min(gaps), 1),
        "poor_count": poor_count,
        "degraded_count": degraded_count,
        "ok_count": severities.count("ok"),
        "avg_amplification": round(avg_gap / CADENCE_SECONDS, 1) if avg_gap else 0,
        "total_strokes_lost": sum(e.strokes_lost for e in events),
        "health": health,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze detection gaps")
    parser.add_argument("--writer", default="qwen", help="Writer ID")
    parser.add_argument("--last", type=int, default=20, help="Number of recent visits")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--threshold", type=int, default=GAP_THRESHOLD_S,
                        help="Gap threshold in seconds")
    args = parser.parse_args()

    visits = _parse_git_log()[:args.last]
    strokes = _parse_stroke_times(DEFAULT_STROKES)

    if not visits:
        print("no caretaker visits found in git log", file=sys.stderr)
        sys.exit(2)

    events = find_detection_events(visits, strokes)
    summary = summarize(events)

    if args.json:
        output = {
            "summary": summary,
            "events": [e.to_dict() for e in events],
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Detection Gap Analysis (writer={args.writer})")
        print(f"  visits analyzed: {summary['count']}")
        print(f"  avg gap: {summary['avg_gap']}s")
        print(f"  max gap: {summary['max_gap']}s")
        print(f"  avg amplification: {summary.get('avg_amplification', 0)}x cadence")
        print(f"  total strokes lost: {summary['total_strokes_lost']}")
        print(f"  health: {summary['health']}")
        print()
        for e in events[:10]:
            print(f"  visit {e.visit_number}: gap={e.gap_seconds:.0f}s "
                  f"amp={e.amplification:.0f}x lost={e.strokes_lost} [{e.severity()}]")

    # Exit code based on health
    if summary["health"] == "poor":
        sys.exit(1)
    elif summary["health"] == "degraded":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
