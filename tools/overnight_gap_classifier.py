#!/usr/bin/env python3
"""overnight_gap_classifier.py — classify overnight writer behaviour from stroke gaps.

Reads data/strokes.jsonl, looks at the last N hours (default 12), finds the
longest gap between consecutive strokes, and classifies the overnight run into
one of four buckets:

    clean_run      — no gap exceeded 2× the configured cadence
    mild_stall     — longest gap was 2–5× cadence (writer paused briefly)
    severe_stall   — longest gap was 5–20× cadence (process likely died and
                     was restarted within the window)
    extended_outage — longest gap exceeded 20× cadence (multi-hour silence,
                     probably a caretaker intervention at dawn)

Why this matters: the overnight run is the repo's unattended health signal.
A clean overnight means the writer-batch-push pipeline held together for eight
hours without human help. Anything worse is a story worth recording — not
because the story is interesting, but because the *pattern* of failures over
weeks tells you whether the system is getting more reliable or just failing
in new ways.

Exit codes:
    0 — classification succeeded (result printed to stdout)
    1 — data files missing or unreadable
    2 — no strokes found in the requested window

Usage:
    python3 tools/overnight_gap_classifier.py
    python3 tools/overnight_gap_classifier.py --hours 8
    python3 tools/overnight_gap_classifier.py --cadence 15 --json
    python3 tools/overnight_gap_classifier.py --repo /path/to/IamAI
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Thresholds (multiples of the configured stroke cadence)
# ---------------------------------------------------------------------------
MILD_STALL_X = 2
SEVERE_STALL_X = 5
EXTENDED_OUTAGE_X = 20

LABELS = {
    0: "clean_run",
    1: "mild_stall",
    2: "severe_stall",
    3: "extended_outage",
}


@dataclass
class OvernightReport:
    label: str
    longest_gap_s: float
    cadence_s: float
    window_hours: int
    strokes_in_window: int
    gap_started_at: str          # ISO-8601 of the stroke *before* the gap
    gap_ended_at: str            # ISO-8601 of the stroke *after* the gap
    multiplier: float            # longest_gap / cadence

    def to_dict(self) -> dict:
        return asdict(self)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root containing data/."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / "data" / "strokes.jsonl").exists():
            return parent
    return p


def load_strokes(repo: Path, window_hours: int = 12) -> list[dict]:
    """Read strokes from the last *window_hours* hours.

    Each line in strokes.jsonl is a JSON object with at least 'seq' and 'at'.
    Returns them sorted oldest-first.
    """
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    strokes: list[dict] = []

    for line in strokes_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        at_str = obj.get("at", "")
        if not at_str:
            continue
        try:
            at_dt = datetime.fromisoformat(at_str)
        except (ValueError, TypeError):
            continue
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        if at_dt >= cutoff:
            strokes.append({"seq": obj.get("seq", 0), "at": at_dt, "raw_at": at_str})

    strokes.sort(key=lambda s: s["at"])
    return strokes


def classify_gaps(
    strokes: list[dict],
    cadence_s: float = 15.0,
) -> OvernightReport:
    """Walk through sorted strokes, find the longest gap, classify it."""
    if len(strokes) < 2:
        # Not enough data points to measure a gap.
        return OvernightReport(
            label="clean_run" if strokes else "extended_outage",
            longest_gap_s=0.0,
            cadence_s=cadence_s,
            window_hours=0,
            strokes_in_window=len(strokes),
            gap_started_at=strokes[0]["raw_at"] if strokes else "",
            gap_ended_at=strokes[0]["raw_at"] if strokes else "",
            multiplier=0.0,
        )

    longest_gap_s = 0.0
    gap_start_raw = strokes[0]["raw_at"]
    gap_end_raw = strokes[1]["raw_at"]

    for i in range(1, len(strokes)):
        gap = (strokes[i]["at"] - strokes[i - 1]["at"]).total_seconds()
        if gap > longest_gap_s:
            longest_gap_s = gap
            gap_start_raw = strokes[i - 1]["raw_at"]
            gap_end_raw = strokes[i]["raw_at"]

    multiplier = longest_gap_s / cadence_s if cadence_s > 0 else float("inf")

    if multiplier >= EXTENDED_OUTAGE_X:
        label = "extended_outage"
    elif multiplier >= SEVERE_STALL_X:
        label = "severe_stall"
    elif multiplier >= MILD_STALL_X:
        label = "mild_stall"
    else:
        label = "clean_run"

    # Compute window span in hours from first to last stroke in window.
    span_s = (strokes[-1]["at"] - strokes[0]["at"]).total_seconds()
    window_hours = int(span_s / 3600) if span_s > 0 else 0

    return OvernightReport(
        label=label,
        longest_gap_s=longest_gap_s,
        cadence_s=cadence_s,
        window_hours=window_hours,
        strokes_in_window=len(strokes),
        gap_started_at=gap_start_raw,
        gap_ended_at=gap_end_raw,
        multiplier=round(multiplier, 1),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=None, help="repo root (default: auto-detect)")
    ap.add_argument("--hours", type=int, default=12, help="lookback window in hours (default 12)")
    ap.add_argument("--cadence", type=float, default=15.0, help="stroke cadence in seconds (default 15)")
    ap.add_argument("--json", action="store_true", help="output JSON instead of plain text")
    args = ap.parse_args()

    repo = find_repo_root(args.repo)
    strokes = load_strokes(repo, window_hours=args.hours)

    if not strokes:
        if args.json:
            print(json.dumps({"error": "no_strokes", "window_hours": args.hours}))
        else:
            print(f"No strokes found in the last {args.hours} hours.")
        return 2

    report = classify_gaps(strokes, cadence_s=args.cadence)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Overnight classification: {report.label}")
        print(f"  longest gap: {report.longest_gap_s:.0f}s ({report.multiplier}× cadence)")
        print(f"  gap window:  {report.gap_started_at} → {report.gap_ended_at}")
        print(f"  strokes in window: {report.strokes_in_window} over {report.window_hours}h")

    # Exit code reflects severity for easy scripting.
    severity = {"clean_run": 0, "mild_stall": 1, "severe_stall": 2, "extended_outage": 3}
    return severity.get(report.label, 0)


if __name__ == "__main__":
    sys.exit(main())
