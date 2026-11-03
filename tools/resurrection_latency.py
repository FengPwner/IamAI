#!/usr/bin/env python3
"""resurrection_latency.py — measure the gap between process death and resurrection.

When the writer dies silently (OOM kill, container recycle, SIGKILL), there is
no traceback — only a gap in the stroke log. This tool detects those gaps and
pairs them with the recovery event (the next stroke or caretaker commit) to
compute *resurrection latency*: how long the writer was silent.

The distinction from existing tools:

    cadence_stall_detector.py  — "is the writer stalled *right now*?"
    resurrection_tracker.py    — "how often does the writer die, and is it clustered?"
    resurrection_cost.py       — "how much time is lost to restarts?"
    resurrection_score.py      — "how good is the system at coming back?"
    resurrection_latency.py    — "for each death event, exactly when did the writer
                                  stop and when did it start again?"

This produces per-event records suitable for timeline visualisation and for
correlating deaths with external causes (container OOM events, host recycling,
deploy windows).

Input:
    data/strokes.jsonl  — one JSON object per line, must have "at" (ISO-8601)
    git log             — for detecting caretaker-driven recoveries

Output (JSON):
    [
        {
            "last_stroke_at": "2026-11-04T01:08:00+00:00",
            "next_stroke_at": "2026-11-04T01:52:00+00:00",
            "gap_seconds": 2640,
            "gap_cadences": 176.0,
            "severity": "severe",
            "recovery_type": "caretaker"
        },
        ...
    ]

Severity levels:
    nominal   — gap < 2x cadence
    mild      — 2x–5x cadence
    severe    — 5x–20x cadence
    critical  — > 20x cadence

Recovery types:
    self       — writer resumed on its own (e.g. pause released)
    caretaker  — recovery coincides with a catch-up commit
    unknown    — cannot determine

Usage:
    python3 tools/resurrection_latency.py
    python3 tools/resurrection_latency.py --cadence 15 --days 7
    python3 tools/resurrection_latency.py --json --min-severity mild
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"
DEFAULT_CADENCE = 15  # seconds

SEVERITY_ORDER = ["nominal", "mild", "severe", "critical"]

CATCH_UP_PATTERNS = [
    re.compile(r"catch-up", re.IGNORECASE),
    re.compile(r"process restart", re.IGNORECASE),
    re.compile(r"resurrection", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        # Python 3.7+ fromisoformat handles most cases; fallback for Z suffix
        cleaned = ts.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def classify_severity(gap_seconds: float, cadence: float) -> str:
    """Classify a gap's severity relative to the expected cadence."""
    if cadence <= 0:
        return "critical"
    ratio = gap_seconds / cadence
    if ratio < 2:
        return "nominal"
    elif ratio < 5:
        return "mild"
    elif ratio < 20:
        return "severe"
    else:
        return "critical"


def severity_at_least(severity: str, min_severity: str) -> bool:
    """Check if severity meets or exceeds the minimum threshold."""
    try:
        return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(min_severity)
    except ValueError:
        return False


@dataclass
class ResurrectionEvent:
    """A single death-and-recovery event."""
    last_stroke_at: str
    next_stroke_at: str
    gap_seconds: float
    gap_cadences: float
    severity: str
    recovery_type: str  # "self" | "caretaker" | "unknown"
    last_stroke_seq: Optional[int] = None
    next_stroke_seq: Optional[int] = None
    caretaker_commit: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# stroke loading
# ---------------------------------------------------------------------------

def load_strokes(strokes_path: Path, since: Optional[datetime] = None) -> List[dict]:
    """Load strokes from JSONL, optionally filtering by timestamp."""
    if not strokes_path.exists():
        return []
    strokes = []
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_timestamp(entry.get("at", ""))
            if ts is None:
                continue
            if since and ts < since:
                continue
            entry["_parsed_at"] = ts
            strokes.append(entry)
    strokes.sort(key=lambda e: e["_parsed_at"])
    return strokes


def find_gaps(strokes: List[dict], cadence: float) -> List[ResurrectionEvent]:
    """Find all gaps exceeding 2x cadence in a sorted stroke list."""
    events = []
    for i in range(len(strokes) - 1):
        curr = strokes[i]
        nxt = strokes[i + 1]
        t_curr = curr["_parsed_at"]
        t_nxt = nxt["_parsed_at"]
        gap = (t_nxt - t_curr).total_seconds()
        if gap < 2 * cadence:
            continue
        severity = classify_severity(gap, cadence)
        events.append(ResurrectionEvent(
            last_stroke_at=t_curr.isoformat(),
            next_stroke_at=t_nxt.isoformat(),
            gap_seconds=gap,
            gap_cadences=round(gap / cadence, 2) if cadence > 0 else 0,
            severity=severity,
            recovery_type="unknown",
            last_stroke_seq=curr.get("seq"),
            next_stroke_seq=nxt.get("seq"),
        ))
    return events


# ---------------------------------------------------------------------------
# git log correlation
# ---------------------------------------------------------------------------

def load_catch_up_commits(repo: Path) -> List[dict]:
    """Find catch-up commits from git log."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--format=%H|%aI|%s", "-200"],
            capture_output=True, text=True, cwd=str(repo), timeout=15
        )
        if result.returncode != 0:
            return []
    except Exception:
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        hash_, ts_str, message = parts
        ts = parse_timestamp(ts_str)
        is_catch_up = any(p.search(message) for p in CATCH_UP_PATTERNS)
        if is_catch_up and ts:
            commits.append({"hash": hash_[:8], "at": ts, "message": message})
    return commits


def correlate_recovery(
    events: List[ResurrectionEvent],
    catch_up_commits: List[dict],
    tolerance_seconds: float = 300,
) -> List[ResurrectionEvent]:
    """Mark events as 'caretaker' if a catch-up commit lands within tolerance
    of the recovery timestamp (next_stroke_at)."""
    for evt in events:
        recovery_time = parse_timestamp(evt.next_stroke_at)
        if recovery_time is None:
            continue
        for commit in catch_up_commits:
            delta = abs((recovery_time - commit["at"]).total_seconds())
            if delta <= tolerance_seconds:
                evt.recovery_type = "caretaker"
                evt.caretaker_commit = commit["hash"]
                break
        # If no caretaker commit matched, it may be a self-recovery
        if evt.recovery_type == "unknown":
            # Self-recovery: the writer resumed without a caretaker visit
            evt.recovery_type = "self"
    return events


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def summarize(events: List[ResurrectionEvent]) -> dict:
    """Produce aggregate statistics from a list of resurrection events."""
    if not events:
        return {"count": 0, "summary": "no resurrection events"}

    gaps = [e.gap_seconds for e in events]
    severities = [e.severity for e in events]
    recovery_types = [e.recovery_type for e in events]

    total_gap = sum(gaps)
    max_gap = max(gaps)
    avg_gap = total_gap / len(gaps)

    return {
        "count": len(events),
        "total_gap_seconds": round(total_gap, 1),
        "max_gap_seconds": round(max_gap, 1),
        "avg_gap_seconds": round(avg_gap, 1),
        "max_gap_cadences": max(e.gap_cadences for e in events),
        "severity_distribution": {
            s: severities.count(s) for s in SEVERITY_ORDER
        },
        "recovery_distribution": {
            "caretaker": recovery_types.count("caretaker"),
            "self": recovery_types.count("self"),
            "unknown": recovery_types.count("unknown"),
        },
        "worst_event": events[gaps.index(max_gap)].to_dict(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cadence", type=int, default=DEFAULT_CADENCE,
                    help="expected seconds between strokes (default: 15)")
    ap.add_argument("--days", type=int, default=7,
                    help="how many days of history to scan (default: 7)")
    ap.add_argument("--min-severity", choices=SEVERITY_ORDER, default="mild",
                    help="minimum severity to report (default: mild)")
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--repo", type=str, default=str(REPO),
                    help="repo root path")
    args = ap.parse_args()

    repo = Path(args.repo)
    strokes_path = repo / "data" / "strokes.jsonl"
    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    strokes = load_strokes(strokes_path, since=since)
    events = find_gaps(strokes, args.cadence)
    catch_up_commits = load_catch_up_commits(repo)
    events = correlate_recovery(events, catch_up_commits)

    # Filter by minimum severity
    events = [e for e in events if severity_at_least(e.severity, args.min_severity)]

    if args.json:
        output = {
            "events": [e.to_dict() for e in events],
            "summary": summarize(events),
            "config": {
                "cadence": args.cadence,
                "days": args.days,
                "min_severity": args.min_severity,
            }
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        if not events:
            print(f"No resurrection events in the last {args.days} days "
                  f"(severity >= {args.min_severity}).")
            return 0
        print(f"Resurrection events (last {args.days}d, "
              f"severity >= {args.min_severity}): {len(events)}\n")
        for i, evt in enumerate(events, 1):
            print(f"  {i}. [{evt.severity.upper():8s}] "
                  f"gap={evt.gap_seconds:.0f}s ({evt.gap_cadences:.1f}x cadence) "
                  f"recovery={evt.recovery_type}")
            print(f"     last stroke: {evt.last_stroke_at}  (seq {evt.last_stroke_seq})")
            print(f"     next stroke: {evt.next_stroke_at}  (seq {evt.next_stroke_seq})")
            if evt.caretaker_commit:
                print(f"     caretaker commit: {evt.caretaker_commit}")
            print()

        summary = summarize(events)
        print(f"Summary: {summary['count']} events, "
              f"max gap {summary['max_gap_seconds']:.0f}s "
              f"({summary['max_gap_cadences']:.1f}x cadence), "
              f"total downtime {summary['total_gap_seconds']:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
