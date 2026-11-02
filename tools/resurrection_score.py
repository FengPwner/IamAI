#!/usr/bin/env python3
"""resurrection_score.py — compute a resilience score from caretaker visit history.

After 500 visits, it's worth asking: how good is this system at coming back?

The score is 0–100, composed of four weighted components:
  - **recovery_rate** (30%): fraction of visits that ended with all processes running
  - **push_reliability** (25%): fraction of visits that successfully pushed to remote
  - **data_retention** (25%): inverse of data-loss risk (fewer uncommitted strokes = better)
  - **cadence_stability** (20%): how quickly the writer returns to normal cadence post-restart

Usage:
    python3 tools/resurrection_score.py
    python3 tools/resurrection_score.py --json
    python3 tools/resurrection_score.py --visits-dir /path/to/notes
    python3 tools/resurrection_score.py --detail

Exit codes:
    0 — score computed successfully
    1 — no visit notes found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_VISITS_DIR = REPO / "notes"


@dataclass
class VisitRecord:
    """Parsed data from a single caretaker visit note."""
    visit_number: int
    date: str
    writer_running_after: bool
    batch_running_after: bool
    push_succeeded: bool
    pending_at_death: int  # uncommitted files found
    stall_gap_seconds: float  # longest gap before restart


@dataclass
class ComponentScore:
    """One component of the resilience score."""
    name: str
    weight: float
    raw: float  # 0.0–1.0
    weighted: float  # raw * weight


@dataclass
class ResurrectionScore:
    """Complete resilience assessment."""
    total: float  # 0–100
    grade: str  # S/A/B/C/F
    components: list
    visits_analysed: int
    summary: str


def parse_visit_note(path: Path) -> VisitRecord | None:
    """Extract structured data from a caretaker visit markdown file."""
    text = path.read_text(encoding="utf-8", errors="replace")

    # Extract visit number
    m = re.search(r"caretaker visit (\d+)", text, re.IGNORECASE)
    if not m:
        return None
    visit_num = int(m.group(1))

    # Extract date from filename or header
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    date_str = date_m.group(1) if date_m else "unknown"

    # Check if writer was running after visit
    writer_ok = bool(re.search(
        r"writer\s*.*?running\s*\(pid\s*\d+\)", text, re.IGNORECASE
    ))

    # Check if batch was running after visit
    batch_ok = bool(re.search(
        r"batch\s*.*?running\s*\(pid\s*\d+\)", text, re.IGNORECASE
    ))

    # Check push status
    push_ok = bool(re.search(
        r"push\s*(?:succeeded|clean|.*?pushed to origin)", text, re.IGNORECASE
    )) or bool(re.search(r"\d+\.\.[0-9a-f]+\s+main\s*->\s*main", text))

    # Count pending files at death
    pending_m = re.search(r"(\d+)\s+pending\s+files?", text, re.IGNORECASE)
    pending = int(pending_m.group(1)) if pending_m else 0

    # Longest stall gap
    gap_m = re.search(r"(?:longest gap|gap)\s+(\d+)s?", text, re.IGNORECASE)
    gap = float(gap_m.group(1)) if gap_m else 0.0

    return VisitRecord(
        visit_number=visit_num,
        date=date_str,
        writer_running_after=writer_ok,
        batch_running_after=batch_ok,
        push_succeeded=push_ok,
        pending_at_death=pending,
        stall_gap_seconds=gap,
    )


def load_visits(visits_dir: Path) -> list[VisitRecord]:
    """Load all visit records from a directory."""
    visits = []
    for f in sorted(visits_dir.glob("caretaker-visit-*.md")):
        rec = parse_visit_note(f)
        if rec:
            visits.append(rec)
    visits.sort(key=lambda v: v.visit_number)
    return visits


def compute_recovery_rate(visits: list[VisitRecord]) -> float:
    """Fraction of visits where both processes ended up running."""
    if not visits:
        return 0.0
    ok = sum(1 for v in visits if v.writer_running_after and v.batch_running_after)
    return ok / len(visits)


def compute_push_reliability(visits: list[VisitRecord]) -> float:
    """Fraction of visits that successfully pushed."""
    if not visits:
        return 0.0
    ok = sum(1 for v in visits if v.push_succeeded)
    return ok / len(visits)


def compute_data_retention(visits: list[VisitRecord]) -> float:
    """Score based on how few pending files were found (less = better).

    0 pending → 1.0, 10+ pending → 0.0
    """
    if not visits:
        return 0.0
    # Average pending, then invert with a soft curve
    avg_pending = sum(v.pending_at_death for v in visits) / len(visits)
    # Soft clamp: score = max(0, 1 - avg_pending/10)
    return max(0.0, 1.0 - avg_pending / 10.0)


def compute_cadence_stability(visits: list[VisitRecord]) -> float:
    """Score based on stall gap — shorter gaps mean faster detection.

    gap ≤ 600s (one batch interval) → 1.0
    gap ≥ 7200s (2 hours) → 0.0
    Linear interpolation between.
    """
    if not visits:
        return 0.0
    gaps = [v.stall_gap_seconds for v in visits if v.stall_gap_seconds > 0]
    if not gaps:
        return 1.0  # no stalls detected = perfect
    avg_gap = sum(gaps) / len(gaps)
    # Linear scale: 600s = 1.0, 7200s = 0.0
    score = max(0.0, min(1.0, (7200.0 - avg_gap) / (7200.0 - 600.0)))
    return score


def grade_score(total: float) -> str:
    """Assign a letter grade to the total score."""
    if total >= 90:
        return "S"
    elif total >= 75:
        return "A"
    elif total >= 60:
        return "B"
    elif total >= 40:
        return "C"
    else:
        return "F"


def compute_score(visits: list[VisitRecord]) -> ResurrectionScore:
    """Compute the full resurrection score from visit records."""
    components = [
        ComponentScore("recovery_rate", 0.30, compute_recovery_rate(visits), 0),
        ComponentScore("push_reliability", 0.25, compute_push_reliability(visits), 0),
        ComponentScore("data_retention", 0.25, compute_data_retention(visits), 0),
        ComponentScore("cadence_stability", 0.20, compute_cadence_stability(visits), 0),
    ]

    for c in components:
        c.weighted = c.raw * c.weight

    total = sum(c.weighted for c in components) * 100.0
    total = round(min(100.0, max(0.0, total)), 1)
    grade = grade_score(total)

    summary = (
        f"resurrection score: {total}/100 ({grade}) "
        f"across {len(visits)} visits. "
        f"recovery {components[0].raw:.0%}, "
        f"push {components[1].raw:.0%}, "
        f"retention {components[2].raw:.0%}, "
        f"cadence {components[3].raw:.0%}."
    )

    return ResurrectionScore(
        total=total,
        grade=grade,
        components=[asdict(c) for c in components],
        visits_analysed=len(visits),
        summary=summary,
    )


def format_text(score: ResurrectionScore, detail: bool = False) -> str:
    """Format score as human-readable text."""
    lines = [
        f"=== Resurrection Score ===",
        f"Total: {score.total}/100 ({score.grade})",
        f"Visits analysed: {score.visits_analysed}",
        f"",
    ]
    if detail:
        lines.append("Components:")
        for c in score.components:
            bar = "█" * int(c["raw"] * 20) + "░" * (20 - int(c["raw"] * 20))
            lines.append(
                f"  {c['name']:20s}  weight {c['weight']:.0%}  "
                f"raw {c['raw']:.0%}  [{bar}]"
            )
        lines.append("")
    lines.append(score.summary)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compute resurrection score")
    parser.add_argument("--visits-dir", type=Path, default=DEFAULT_VISITS_DIR)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--detail", action="store_true", help="Show component breakdown")
    args = parser.parse_args()

    visits = load_visits(args.visits_dir)
    if not visits:
        print("no visit notes found", file=sys.stderr)
        sys.exit(1)

    score = compute_score(visits)

    if args.json:
        print(json.dumps(asdict(score), indent=2))
    else:
        print(format_text(score, detail=args.detail))


if __name__ == "__main__":
    main()
