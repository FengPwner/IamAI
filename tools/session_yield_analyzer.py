#!/usr/bin/env python3
"""session_yield_analyzer.py — measure how many strokes each writer session produces.

A "session" is the lifespan of one writer process invocation, from the
first stroke it emits until it dies (container recycle, crash, or
planned stop). Between sessions there is a gap — the detection delay
before the caretaker restarts the writer.

This tool answers a question none of the other metrics cover:

    "how productive is each writer session before it dies?"

The ghost push index measures push health. The detection gap analyzer
measures monitoring health. The stall classifier measures stroke-level
continuity. But none of them tell you whether sessions are getting
longer or shorter, richer or poorer.

Algorithm:
    1. Read data/strokes.jsonl (append-only stroke log).
    2. Detect session boundaries: a gap larger than `--gap-threshold`
       seconds (default 300, i.e. 5 minutes) between consecutive
       strokes signals the end of one session and the start of the next.
       (The writer cadence is 15s; a 5-minute gap means ~20 missed
       strokes — almost certainly a process death.)
    3. For each session, record:
       - start_time: timestamp of the first stroke
       - end_time: timestamp of the last stroke
       - duration_seconds: end minus start
       - stroke_count: number of strokes in this session
       - kinds: breakdown by stroke kind (thought, metric, snippet, etc.)
       - strokes_per_minute: stroke_count / (duration_seconds / 60)
    4. Compute summary statistics:
       - total_sessions: number of detected sessions
       - median_session_duration: middle value of durations
       - median_strokes_per_session: middle value of stroke counts
       - total_strokes: sum across all sessions
       - yield_trend: compare median stroke count of the last 10
         sessions vs the previous 10 — positive means sessions are
         getting more productive, negative means container recycles
         are cutting sessions shorter
       - reliability_score: fraction of sessions that produced at least
         10 strokes. A session with <10 strokes died almost immediately
         after starting (or was born just before the container died).

Severity classification (based on reliability_score):
    RELIABLE   — score >= 0.80. Most sessions are productive.
    DEGRADED   — score >= 0.50. Many sessions die young.
    FRAGILE    — score <  0.50. Container recycles are dominating.

Usage:
    python3 tools/session_yield_analyzer.py
    python3 tools/session_yield_analyzer.py --json
    python3 tools/session_yield_analyzer.py --gap-threshold 600 --last 20

Exit codes:
    0 — RELIABLE or DEGRADED
    1 — FRAGILE (more than half the sessions are short-lived)
    2 — error (no data, parse failure)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"
DEFAULT_GAP_THRESHOLD = 300  # seconds — 5 minutes
MIN_STROKES_RELIABLE = 10  # a session with fewer is "short-lived"


@dataclass
class Session:
    """One writer session — from first stroke to last before a gap."""
    start_time: datetime
    end_time: datetime
    strokes: List[Dict[str, Any]]

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def stroke_count(self) -> int:
        return len(self.strokes)

    @property
    def strokes_per_minute(self) -> float:
        if self.duration_seconds < 1:
            return 0.0
        return self.stroke_count / (self.duration_seconds / 60.0)

    @property
    def kind_breakdown(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self.strokes:
            k = s.get("kind", "unknown")
            counts[k] = counts.get(k, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat(),
            "duration_seconds": round(self.duration_seconds, 1),
            "stroke_count": self.stroke_count,
            "strokes_per_minute": round(self.strokes_per_minute, 2),
            "kinds": self.kind_breakdown,
        }


def parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime."""
    ts_str = ts_str.strip()
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def detect_sessions(
    strokes: List[Dict[str, Any]],
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> List[Session]:
    """Split a chronological stroke list into sessions by gap detection."""
    if not strokes:
        return []

    sessions: List[Session] = []
    current_strokes: List[Dict[str, Any]] = [strokes[0]]

    for i in range(1, len(strokes)):
        prev_ts = parse_timestamp(strokes[i - 1]["at"])
        curr_ts = parse_timestamp(strokes[i]["at"])
        gap = (curr_ts - prev_ts).total_seconds()

        if gap > gap_threshold:
            # close current session, start a new one
            sessions.append(
                Session(
                    start_time=parse_timestamp(current_strokes[0]["at"]),
                    end_time=parse_timestamp(current_strokes[-1]["at"]),
                    strokes=list(current_strokes),
                )
            )
            current_strokes = [strokes[i]]
        else:
            current_strokes.append(strokes[i])

    # close the last session
    sessions.append(
        Session(
            start_time=parse_timestamp(current_strokes[0]["at"]),
            end_time=parse_timestamp(current_strokes[-1]["at"]),
            strokes=list(current_strokes),
        )
    )

    return sessions


def classify_severity(reliability_score: float) -> str:
    """Classify system reliability based on fraction of productive sessions."""
    if reliability_score >= 0.80:
        return "RELIABLE"
    elif reliability_score >= 0.50:
        return "DEGRADED"
    else:
        return "FRAGILE"


def compute_yield_trend(sessions: List[Session], window: int = 10) -> float:
    """Compare median stroke count of the last N sessions vs the previous N.

    Returns:
        positive float — sessions are getting more productive
        negative float — sessions are getting shorter
        0.0 — not enough data to compare
    """
    if len(sessions) < 2 * window:
        return 0.0
    recent = [s.stroke_count for s in sessions[-window:]]
    previous = [s.stroke_count for s in sessions[-2 * window : -window]]
    recent_median = median(recent)
    previous_median = median(previous)
    if previous_median == 0:
        return 0.0
    return round((recent_median - previous_median) / previous_median, 3)


def analyze(
    strokes_path: Path = DEFAULT_STROKES,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
    last_n: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the full session yield analysis."""
    if not strokes_path.exists():
        return {"error": f"strokes file not found: {strokes_path}", "exit_code": 2}

    raw_strokes: List[Dict[str, Any]] = []
    for line in strokes_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # normalise timestamp key: some early entries use "t" instead of "at"
        if "at" not in entry and "t" in entry:
            entry["at"] = entry["t"]
        # skip entries that still have no usable timestamp
        if "at" not in entry:
            continue
        raw_strokes.append(entry)

    if not raw_strokes:
        return {"error": "no strokes found", "exit_code": 2}

    # sort chronologically (the file should be, but be safe)
    raw_strokes.sort(key=lambda s: s["at"])
    strokes = raw_strokes

    sessions = detect_sessions(strokes, gap_threshold)

    if not sessions:
        return {"error": "no sessions detected", "exit_code": 2}

    if last_n:
        sessions = sessions[-last_n:]

    durations = [s.duration_seconds for s in sessions]
    stroke_counts = [s.stroke_count for s in sessions]
    productive = sum(1 for c in stroke_counts if c >= MIN_STROKES_RELIABLE)
    reliability_score = productive / len(sessions)
    severity = classify_severity(reliability_score)
    yield_trend = compute_yield_trend(sessions)

    result = {
        "total_sessions": len(sessions),
        "total_strokes": sum(stroke_counts),
        "median_session_duration_seconds": round(median(durations), 1),
        "median_strokes_per_session": median(stroke_counts),
        "productive_sessions": productive,
        "short_lived_sessions": len(sessions) - productive,
        "reliability_score": round(reliability_score, 3),
        "severity": severity,
        "yield_trend": yield_trend,
        "gap_threshold_seconds": gap_threshold,
        "sessions": [s.to_dict() for s in sessions[-20:]],  # last 20 for detail
        "exit_code": 1 if severity == "FRAGILE" else 0,
    }

    return result


def format_human(data: Dict[str, Any]) -> str:
    """Format the analysis result for human-readable output."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = [
        "=== Session Yield Analysis ===",
        "",
        f"total sessions detected:  {data['total_sessions']}",
        f"total strokes:            {data['total_strokes']}",
        f"median session duration:  {data['median_session_duration_seconds']:.0f}s "
        f"({data['median_session_duration_seconds'] / 60:.1f} min)",
        f"median strokes/session:   {data['median_strokes_per_session']}",
        f"productive sessions:      {data['productive_sessions']} / {data['total_sessions']}",
        f"short-lived sessions:     {data['short_lived_sessions']}",
        f"reliability score:        {data['reliability_score']:.1%}",
        f"severity:                 {data['severity']}",
    ]

    trend = data["yield_trend"]
    if trend > 0:
        trend_desc = f"+{trend:.1%} (sessions getting more productive)"
    elif trend < 0:
        trend_desc = f"{trend:.1%} (sessions getting shorter — recycles cutting yield)"
    else:
        trend_desc = "insufficient data for trend"
    lines.append(f"yield trend:              {trend_desc}")
    lines.append(f"gap threshold:            {data['gap_threshold_seconds']}s")

    # show last few sessions
    if data.get("sessions"):
        lines.append("")
        lines.append("--- last sessions ---")
        for s in data["sessions"][-10:]:
            dur_min = s["duration_seconds"] / 60
            lines.append(
                f"  {s['start'][:19]}  dur={dur_min:.1f}min  "
                f"strokes={s['stroke_count']}  "
                f"rate={s['strokes_per_minute']:.1f}/min  "
                f"kinds={s['kinds']}"
            )

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strokes",
        type=Path,
        default=DEFAULT_STROKES,
        help="path to strokes.jsonl",
    )
    ap.add_argument(
        "--gap-threshold",
        type=float,
        default=DEFAULT_GAP_THRESHOLD,
        help="seconds between strokes that signals a new session (default 300)",
    )
    ap.add_argument(
        "--last",
        type=int,
        default=None,
        help="only analyse the last N sessions",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="output JSON instead of human-readable text",
    )
    args = ap.parse_args()

    data = analyze(args.strokes, args.gap_threshold, args.last)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(format_human(data))

    return data.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())
