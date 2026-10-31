#!/usr/bin/env python3
"""visit_overhead_ratio.py — measure caretaker visit overhead.

Problem: each caretaker visit spends time on process restart, git operations,
and push-divergence resolution before any productive work begins. This overhead
is invisible in stroke metrics. If the overhead ratio keeps climbing, the
caretaker is mostly maintaining itself rather than adding value.

This tool parses caretaker visit notes and calculates:
- Total visit duration (arrival to departure)
- Number of ritual actions (restart, stash, rebase, push, kill, pause)
- Number of productive actions (new notes, new tools, new tests)
- Overhead ratio = ritual actions / total actions

Usage:
    python3 tools/visit_overhead_ratio.py                # last 10 visits
    python3 tools/visit_overhead_ratio.py --visits 20    # last 20 visits
    python3 tools/visit_overhead_ratio.py --json         # machine-readable
    python3 tools/visit_overhead_ratio.py --notes-dir /path/to/notes

Exit codes:
    0 — success
    1 — no visit notes found
    2 — parse error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_NOTES_DIR = REPO / "notes"

RITUAL_KEYWORDS = [
    "restart", "stash", "rebase", "push", "kill", "pause",
    "fetch", "pull", "commit backlog", "backlog commit",
    "resume writer", "resume batch",
]

PRODUCTIVE_KEYWORDS = [
    "new note", "new tool", "new test", "added tool",
    "added note", "visit note", "write", "implement",
    "create", "add",
]


@dataclass
class VisitStats:
    visit_number: int
    date: str
    duration_minutes: float | None
    ritual_actions: int
    productive_actions: int
    total_actions: int
    overhead_ratio: float
    push_rejected: bool
    notes: str


def find_visit_notes(notes_dir: Path) -> list[Path]:
    """Find all caretaker visit notes, sorted by visit number."""
    pattern = re.compile(r"caretaker-visit-(\d+)-\d{4}-\d{2}-\d{2}\.md$")
    visits = []
    for p in notes_dir.glob("caretaker-visit-*.md"):
        m = pattern.match(p.name)
        if m:
            visits.append((int(m.group(1)), p))
    visits.sort(key=lambda x: x[0])
    return [v[1] for v in visits]


def parse_visit(path: Path) -> VisitStats | None:
    """Parse a single caretaker visit note."""
    text = path.read_text(encoding="utf-8")

    # Extract visit number
    num_match = re.search(r"Caretaker Visit (\d+)", text)
    if not num_match:
        return None
    visit_number = int(num_match.group(1))

    # Extract date from YAML frontmatter or header
    date_match = re.search(r"date:\s*(\S+)", text)
    date_str = date_match.group(1) if date_match else "unknown"

    # Extract timestamps for duration
    timestamps = re.findall(r"(\d{2}:\d{2})", text)
    duration_minutes = None
    if len(timestamps) >= 2:
        # Use first and last timestamp as rough duration
        try:
            h1, m1 = map(int, timestamps[0].split(":"))
            h2, m2 = map(int, timestamps[-1].split(":"))
            diff = (h2 * 60 + m2) - (h1 * 60 + m1)
            if diff > 0:
                duration_minutes = float(diff)
        except (ValueError, IndexError):
            pass

    # Count actions from the Actions table
    ritual_count = 0
    productive_count = 0

    # Look for table rows with | # | Action | Result |
    action_rows = re.findall(r"\|\s*\d+\s*\|(.*?)\|(.*?)\|", text)
    for action_text, result_text in action_rows:
        combined = (action_text + " " + result_text).lower()
        is_ritual = any(kw in combined for kw in RITUAL_KEYWORDS)
        is_productive = any(kw in combined for kw in PRODUCTIVE_KEYWORDS)
        if is_ritual:
            ritual_count += 1
        if is_productive:
            productive_count += 1

    total = ritual_count + productive_count
    overhead = ritual_count / total if total > 0 else 1.0
    push_rejected = "rejected" in text.lower() or "REJECTED" in text

    # Extract notes/observations
    notes = ""
    if "seventh consecutive" in text.lower():
        notes = "7th consecutive push divergence"
    elif "sixth consecutive" in text.lower():
        notes = "6th consecutive push divergence"
    elif "recurring" in text.lower():
        notes = "recurring divergence pattern"

    return VisitStats(
        visit_number=visit_number,
        date=date_str,
        duration_minutes=duration_minutes,
        ritual_actions=ritual_count,
        productive_actions=productive_count,
        total_actions=total,
        overhead_ratio=round(overhead, 3),
        push_rejected=push_rejected,
        notes=notes,
    )


def compute_trend(visits: list[VisitStats]) -> str:
    """Compute a simple trend line for overhead ratios."""
    if len(visits) < 3:
        return "insufficient data"
    ratios = [v.overhead_ratio for v in visits if v.total_actions > 0]
    if len(ratios) < 3:
        return "insufficient data"
    first_half = sum(ratios[:len(ratios)//2]) / (len(ratios)//2)
    second_half = sum(ratios[len(ratios)//2:]) / (len(ratios) - len(ratios)//2)
    if second_half > first_half + 0.05:
        return "worsening"
    elif second_half < first_half - 0.05:
        return "improving"
    return "stable"


def format_report(visits: list[VisitStats]) -> str:
    """Format a human-readable report."""
    lines = ["# Caretaker Visit Overhead Report\n"]
    lines.append(f"Visits analyzed: {len(visits)}")

    push_divergences = sum(1 for v in visits if v.push_rejected)
    lines.append(f"Push rejections: {push_divergences}")

    if visits:
        avg_overhead = sum(v.overhead_ratio for v in visits) / len(visits)
        lines.append(f"Average overhead ratio: {avg_overhead:.1%}")
        lines.append(f"Trend: {compute_trend(visits)}")

    lines.append("")
    lines.append("| Visit | Date | Ritual | Productive | Overhead | Push OK |")
    lines.append("|-------|------|--------|------------|----------|---------|")
    for v in visits:
        push_mark = "✗" if v.push_rejected else "✓"
        lines.append(
            f"| {v.visit_number} | {v.date} | {v.ritual_actions} | "
            f"{v.productive_actions} | {v.overhead_ratio:.0%} | {push_mark} |"
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Measure caretaker visit overhead")
    parser.add_argument("--visits", type=int, default=10, help="Number of recent visits")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--notes-dir", type=Path, default=DEFAULT_NOTES_DIR)
    args = parser.parse_args()

    all_visits = find_visit_notes(args.notes_dir)
    if not all_visits:
        print("No caretaker visit notes found.", file=sys.stderr)
        sys.exit(1)

    recent = all_visits[-args.visits:]
    stats = []
    for path in recent:
        parsed = parse_visit(path)
        if parsed:
            stats.append(parsed)

    if not stats:
        print("Could not parse any visit notes.", file=sys.stderr)
        sys.exit(2)

    if args.json:
        output = {
            "visits": [asdict(s) for s in stats],
            "trend": compute_trend(stats),
            "push_divergence_count": sum(1 for s in stats if s.push_rejected),
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_report(stats))


if __name__ == "__main__":
    main()
