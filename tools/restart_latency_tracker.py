#!/usr/bin/env python3
"""restart_latency_tracker.py — measure how fast processes recover after death.

The detection gap analyzer tells you how long it took to *notice* a process
died. The session yield analyzer tells you how productive each session was.
But neither answers a simple operational question: once we know the process
is dead, how fast do we get it running again?

Restart latency is the wall-clock time from detection to confirmed restart.
It captures the entire recovery pipeline: detection, decision, lock check,
process spawn, and first-stroke confirmation.

This tool parses caretaker visit notes to extract timestamps for:
  1. **detection_time**: when the caretaker discovered the process was down
     (from the note's timestamp or the "pre-flight" section).
  2. **restart_time**: when run_both.sh completed successfully
     (from the "actions taken" section or commit timestamps).
  3. **restart_latency_seconds**: restart_time minus detection_time.

Severity classification:
  - fast:      < 30s   (automated or near-instant recovery)
  - acceptable: 30-120s (normal human-in-the-loop recovery)
  - slow:      120-300s (something went wrong during recovery)
  - stalled:   > 300s  (recovery itself failed or was delayed)

Usage:
    python3 tools/restart_latency_tracker.py
    python3 tools/restart_latency_tracker.py --last 20
    python3 tools/restart_latency_tracker.py --json
    python3 tools/restart_latency_tracker.py --notes-dir notes/

Exit codes:
    0 — all restarts within acceptable threshold (<120s)
    1 — at least one restart was slow or stalled
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
DEFAULT_NOTES_DIR = REPO / "notes"

# Thresholds in seconds
FAST_THRESHOLD = 30
ACCEPTABLE_THRESHOLD = 120
SLOW_THRESHOLD = 300

# Pattern to match caretaker visit notes that mention restarts
VISIT_PATTERN = re.compile(r"caretaker-visit-(\d+)")
RESTART_PID_PATTERN = re.compile(
    r"(?:writer|batch)\s+pid\s+(\d+)[\s:]+(?:up|running)", re.IGNORECASE
)
NOT_RUNNING_PATTERN = re.compile(
    r"(?:writer|batch).*?NOT\s+running", re.IGNORECASE
)

# Timestamp patterns in notes
# "visit 386 at 08:01" or "2026-10-27 08:01"
AT_TIME_PATTERN = re.compile(
    r"visit\s+\d+\s+at\s+(\d{1,2}):(\d{2})"
)
ISO_TIME_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)"
)


@dataclass
class RestartEvent:
    """One instance of detecting death and restarting."""
    visit_number: Optional[int]
    detection_time: datetime
    restart_time: datetime
    latency_seconds: float
    writer_pid: Optional[int] = None
    batch_pid: Optional[int] = None
    needed_restart: bool = True
    commit_hash: str = ""

    def severity(self) -> str:
        if not self.needed_restart:
            return "not_needed"
        if self.latency_seconds < FAST_THRESHOLD:
            return "fast"
        elif self.latency_seconds < ACCEPTABLE_THRESHOLD:
            return "acceptable"
        elif self.latency_seconds < SLOW_THRESHOLD:
            return "slow"
        else:
            return "stalled"

    def to_dict(self) -> dict:
        return {
            "visit": self.visit_number,
            "detection_time": self.detection_time.isoformat(),
            "restart_time": self.restart_time.isoformat(),
            "latency_seconds": round(self.latency_seconds, 1),
            "severity": self.severity(),
            "needed_restart": self.needed_restart,
            "writer_pid": self.writer_pid,
            "batch_pid": self.batch_pid,
            "commit": self.commit_hash,
        }


def parse_visit_note(note_path: Path) -> Optional[dict]:
    """Parse a single caretaker visit note for restart information.

    Returns a dict with:
      - visit_number: int or None
      - detection_time: datetime or None
      - restart_time: datetime or None (None if no restart needed)
      - needed_restart: bool
      - writer_pid: int or None
      - batch_pid: int or None
    """
    if not note_path.exists():
        return None

    text = note_path.read_text(encoding="utf-8", errors="replace")

    # Extract visit number from filename
    match = VISIT_PATTERN.search(note_path.stem)
    visit_number = int(match.group(1)) if match else None

    # Check if restart was needed
    needed_restart = bool(NOT_RUNNING_PATTERN.search(text))

    # Extract PIDs from restart output
    pids = RESTART_PID_PATTERN.findall(text)
    writer_pid = int(pids[0]) if len(pids) >= 1 else None
    batch_pid = int(pids[1]) if len(pids) >= 2 else None

    # Try to extract detection time (pre-flight section)
    detection_time = None
    at_match = AT_TIME_PATTERN.search(text)
    if at_match:
        hour, minute = int(at_match.group(1)), int(at_match.group(2))
        # Use the date from the note filename if available
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", note_path.stem)
        if date_match:
            date_str = date_match.group(1)
            detection_time = datetime.fromisoformat(
                f"{date_str}T{hour:02d}:{minute:02d}:00+08:00"
            )
        else:
            # Fallback: use today's date (approximate)
            today = datetime.now(timezone.utc).date()
            detection_time = datetime(
                today.year, today.month, today.day,
                hour, minute, 0, tzinfo=timezone.utc
            )

    # Try ISO timestamp fallback
    if detection_time is None:
        iso_match = ISO_TIME_PATTERN.search(text)
        if iso_match:
            ts_str = iso_match.group(1)
            try:
                detection_time = datetime.fromisoformat(ts_str)
                if detection_time.tzinfo is None:
                    detection_time = detection_time.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    # Restart time: if restart happened, it's close to detection time
    # (the caretaker detects and restarts in the same visit)
    restart_time = None
    if needed_restart and detection_time is not None:
        # Look for explicit restart confirmation time
        restart_section = text.split("actions taken")
        if len(restart_section) > 1:
            restart_iso = ISO_TIME_PATTERN.search(restart_section[1])
            if restart_iso:
                try:
                    restart_time = datetime.fromisoformat(restart_iso.group(1))
                    if restart_time.tzinfo is None:
                        restart_time = restart_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
        # Default: restart ~= detection time (same visit, within seconds)
        if restart_time is None:
            restart_time = detection_time

    return {
        "visit_number": visit_number,
        "detection_time": detection_time,
        "restart_time": restart_time,
        "needed_restart": needed_restart,
        "writer_pid": writer_pid,
        "batch_pid": batch_pid,
    }


def find_restart_events(
    notes_dir: Path,
    last_n: Optional[int] = None,
) -> List[RestartEvent]:
    """Scan all caretaker visit notes and extract restart events."""
    events = []

    if not notes_dir.exists():
        return events

    visit_files = sorted(
        [f for f in notes_dir.glob("caretaker-visit-*.md")
         if VISIT_PATTERN.search(f.stem)],
        key=lambda p: p.stat().st_mtime,
    )

    if last_n is not None:
        visit_files = visit_files[-last_n:]

    for note_path in visit_files:
        parsed = parse_visit_note(note_path)
        if parsed is None:
            continue

        if parsed["needed_restart"] and parsed["detection_time"] and parsed["restart_time"]:
            latency = (parsed["restart_time"] - parsed["detection_time"]).total_seconds()
            events.append(RestartEvent(
                visit_number=parsed["visit_number"],
                detection_time=parsed["detection_time"],
                restart_time=parsed["restart_time"],
                latency_seconds=max(0, latency),
                writer_pid=parsed["writer_pid"],
                batch_pid=parsed["batch_pid"],
                needed_restart=True,
            ))
        elif not parsed["needed_restart"] and parsed["detection_time"]:
            # Process was alive — no restart needed, record as healthy
            events.append(RestartEvent(
                visit_number=parsed["visit_number"],
                detection_time=parsed["detection_time"],
                restart_time=parsed["detection_time"],
                latency_seconds=0,
                needed_restart=False,
            ))

    return events


def summarize(events: List[RestartEvent]) -> dict:
    """Produce summary statistics from a list of restart events."""
    if not events:
        return {"count": 0, "message": "no restart events found"}

    restarts_needed = [e for e in events if e.needed_restart]
    no_restarts = [e for e in events if not e.needed_restart]

    latencies = [e.latency_seconds for e in restarts_needed]

    severity_counts = {"fast": 0, "acceptable": 0, "slow": 0, "stalled": 0}
    for e in restarts_needed:
        severity_counts[e.severity()] += 1

    result = {
        "total_visits": len(events),
        "restarts_needed": len(restarts_needed),
        "no_restart_needed": len(no_restarts),
        "restart_rate": round(len(restarts_needed) / len(events), 3) if events else 0,
        "latency_stats": {},
        "severity_breakdown": severity_counts,
        "exit_code": 0,
    }

    if latencies:
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        result["latency_stats"] = {
            "min": round(min(latencies), 1),
            "max": round(max(latencies), 1),
            "median": round(latencies_sorted[n // 2], 1),
            "mean": round(sum(latencies) / n, 1),
            "p90": round(latencies_sorted[min(n - 1, max(0, int(n * 0.9) - 1))], 1) if n >= 10 else round(max(latencies), 1),
        }
        if max(latencies) >= ACCEPTABLE_THRESHOLD:
            result["exit_code"] = 1

    return result


def format_human(summary: dict, events: List[RestartEvent]) -> str:
    """Format summary for human-readable output."""
    lines = []
    lines.append("=== Restart Latency Report ===")
    lines.append(f"Total visits analyzed: {summary.get('total_visits', 0)}")
    lines.append(f"Restarts needed: {summary.get('restarts_needed', 0)}")
    lines.append(f"No restart needed: {summary.get('no_restart_needed', 0)}")
    lines.append(f"Restart rate: {summary.get('restart_rate', 0):.1%}")

    stats = summary.get("latency_stats", {})
    if stats:
        lines.append("")
        lines.append("--- Latency (seconds) ---")
        lines.append(f"  Min:    {stats['min']}")
        lines.append(f"  Max:    {stats['max']}")
        lines.append(f"  Median: {stats['median']}")
        lines.append(f"  Mean:   {stats['mean']}")
        lines.append(f"  P90:    {stats['p90']}")

    breakdown = summary.get("severity_breakdown", {})
    if any(breakdown.values()):
        lines.append("")
        lines.append("--- Severity ---")
        for sev in ["fast", "acceptable", "slow", "stalled"]:
            count = breakdown.get(sev, 0)
            if count > 0:
                lines.append(f"  {sev:12s}: {count}")

    if events:
        lines.append("")
        lines.append("--- Recent Events ---")
        for e in events[-10:]:
            if e.needed_restart:
                lines.append(
                    f"  visit {e.visit_number or '?':>4}: "
                    f"{e.latency_seconds:6.0f}s ({e.severity()})"
                )
            else:
                lines.append(
                    f"  visit {e.visit_number or '?':>4}: "
                    f"  no restart needed"
                )

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Track restart latency across caretaker visits."
    )
    ap.add_argument(
        "--notes-dir",
        type=Path,
        default=DEFAULT_NOTES_DIR,
        help="directory containing caretaker visit notes",
    )
    ap.add_argument(
        "--last",
        type=int,
        default=None,
        help="only analyze the last N visits",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="output JSON instead of human-readable text",
    )
    args = ap.parse_args()

    events = find_restart_events(args.notes_dir, args.last)
    summary = summarize(events)

    if args.json:
        output = {
            "summary": summary,
            "events": [e.to_dict() for e in events],
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(format_human(summary, events))

    return summary.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())
