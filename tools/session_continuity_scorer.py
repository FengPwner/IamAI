#!/usr/bin/env python3
"""session_continuity_scorer — measure handoff quality between caretaker visits.

each caretaker visit is a discrete intervention. the question this tool
answers: how well does the system maintain continuity *between* visits?

continuity has three dimensions:
  1. process survival — did both processes stay alive?
  2. cadence fidelity — did the writer maintain its stroke rhythm?
  3. backlog discipline — was pending work committed before it piled up?

scoring:
  each dimension is 0-100. the composite score is the minimum of the three,
  because continuity is only as strong as its weakest link. a system where
  processes survive but the writer stalls is not continuous — it is a
  zombie. a system where the writer runs but commits pile up is not
  continuous — it is a time bomb.

  grade = min(process_survival, cadence_fidelity, backlog_discipline)

exit 0 when grade >= 60 (acceptable continuity)
exit 1 when grade <  60 (continuity broken somewhere)
"""

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class VisitRecord:
    """parsed data from a single caretaker visit note."""
    visit_num: int
    timestamp: str  # ISO-ish from the heading
    writer_running: bool
    batch_running: bool
    pending_files: int
    unpushed_commits: int
    restart_needed: bool


@dataclass
class ContinuityScore:
    """continuity assessment for a pair of consecutive visits."""
    prev_visit: int
    curr_visit: int
    process_survival: float   # 0-100
    cadence_fidelity: float   # 0-100
    backlog_discipline: float  # 0-100
    grade: float              # min of the three
    label: str                # excellent / good / degraded / broken

    def to_dict(self) -> dict:
        return {
            "prev_visit": self.prev_visit,
            "curr_visit": self.curr_visit,
            "process_survival": round(self.process_survival, 1),
            "cadence_fidelity": round(self.cadence_fidelity, 1),
            "backlog_discipline": round(self.backlog_discipline, 1),
            "grade": round(self.grade, 1),
            "label": self.label,
        }


def parse_visit_note(text: str) -> Optional[VisitRecord]:
    """extract structured data from a caretaker visit note."""

    # visit number from heading
    m = re.search(r"caretaker visit (\d+)", text, re.IGNORECASE)
    if not m:
        return None
    visit_num = int(m.group(1))

    # timestamp from heading line
    ts_match = re.search(r"#\s*caretaker visit \d+\s*[—–-]\s*(.+)", text)
    timestamp = ts_match.group(1).strip() if ts_match else ""

    # writer status — strip markdown bold wrappers first
    clean = text.replace("**", "")
    writer_running = False
    wm = re.search(r"writer\[.*?\]:\s*(running|NOT running)", clean)
    if wm:
        writer_running = wm.group(1) == "running"

    # batch status
    batch_running = False
    bm = re.search(r"batch\s*\[.*?\]:\s*(running|NOT running)", clean)
    if bm:
        batch_running = bm.group(1) == "running"

    # pending files
    pending = 0
    pm = re.search(r"pending:\s*(\d+)\s*file", clean)
    if pm:
        pending = int(pm.group(1))

    # unpushed commits
    unpushed = 0
    um = re.search(r"unpushed:\s*(\d+)", clean)
    if um:
        unpushed = int(um.group(1))

    # restart needed?
    restart_needed = "NOT running" in text and (
        "restarted" in text.lower() or "restart" in text.lower()
    )

    return VisitRecord(
        visit_num=visit_num,
        timestamp=timestamp,
        writer_running=writer_running,
        batch_running=batch_running,
        pending_files=pending,
        unpushed_commits=unpushed,
        restart_needed=restart_needed,
    )


def score_process_survival(prev: VisitRecord, curr: VisitRecord) -> float:
    """did both processes survive between visits?

    100 = both alive at both visits
    50  = one process died and was restarted
    0   = both processes died
    """
    deaths = 0
    if not curr.writer_running:
        deaths += 1
    if not curr.batch_running:
        deaths += 1
    if deaths == 0:
        return 100.0
    elif deaths == 1:
        return 50.0
    else:
        return 0.0


def score_cadence_fidelity(prev: VisitRecord, curr: VisitRecord) -> float:
    """did the writer maintain its stroke rhythm?

    proxy: if writer was running at both visits and pending files are
    low (< 20), cadence is healthy. high pending suggests the writer
    ran but commits fell behind.

    100 = writer running at both visits, pending < 10
    75  = writer running at both visits, pending 10-19
    50  = writer running at current visit only (was restarted)
    25  = writer running but pending >= 20 (stalling commits)
    0   = writer not running at current visit
    """
    if not curr.writer_running:
        return 0.0
    if not prev.writer_running and curr.writer_running:
        # restarted between visits — partial credit
        return 50.0
    # writer was running at both visits
    if curr.pending_files < 10:
        return 100.0
    elif curr.pending_files < 20:
        return 75.0
    else:
        return 25.0


def score_backlog_discipline(prev: VisitRecord, curr: VisitRecord) -> float:
    """is pending work being committed in a timely manner?

    this is about the *trend*, not the absolute number. a few pending
    files is normal (the writer is always producing). a growing pile
    means the commit pipeline is falling behind.

    100 = pending decreased or stayed at 0
    75  = pending increased but still < 10
    50  = pending 10-19
    25  = pending 20-49
    0   = pending >= 50
    """
    p = curr.pending_files
    if p == 0:
        return 100.0
    elif p < 10:
        if curr.pending_files <= prev.pending_files:
            return 100.0
        return 75.0
    elif p < 20:
        return 50.0
    elif p < 50:
        return 25.0
    else:
        return 0.0


def grade_label(grade: float) -> str:
    if grade >= 90:
        return "excellent"
    elif grade >= 60:
        return "good"
    elif grade >= 30:
        return "degraded"
    else:
        return "broken"


def score_pair(prev: VisitRecord, curr: VisitRecord) -> ContinuityScore:
    ps = score_process_survival(prev, curr)
    cf = score_cadence_fidelity(prev, curr)
    bd = score_backlog_discipline(prev, curr)
    g = min(ps, cf, bd)
    return ContinuityScore(
        prev_visit=prev.visit_num,
        curr_visit=curr.visit_num,
        process_survival=ps,
        cadence_fidelity=cf,
        backlog_discipline=bd,
        grade=g,
        label=grade_label(g),
    )


def load_visits(notes_dir: str) -> List[VisitRecord]:
    """parse all caretaker visit notes from a directory."""
    visits = []
    ndir = Path(notes_dir)
    if not ndir.exists():
        return visits
    for f in sorted(ndir.glob("caretaker-visit-*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        rec = parse_visit_note(text)
        if rec:
            visits.append(rec)
    visits.sort(key=lambda v: v.visit_num)
    return visits


def score_all(visits: List[VisitRecord]) -> List[ContinuityScore]:
    """score every consecutive pair of visits."""
    scores = []
    for i in range(1, len(visits)):
        scores.append(score_pair(visits[i - 1], visits[i]))
    return scores


def main():
    notes_dir = sys.argv[1] if len(sys.argv) > 1 else "notes"
    visits = load_visits(notes_dir)
    if len(visits) < 2:
        print("need at least 2 visit notes to score continuity")
        sys.exit(0)

    scores = score_all(visits)
    latest = scores[-1]

    print(json.dumps(latest.to_dict(), indent=2))
    print()
    print(f"continuity grade: {latest.label} ({latest.grade:.0f}/100)")
    print(f"  process_survival:  {latest.process_survival:.0f}")
    print(f"  cadence_fidelity:  {latest.cadence_fidelity:.0f}")
    print(f"  backlog_discipline: {latest.backlog_discipline:.0f}")

    # historical summary
    if len(scores) >= 5:
        recent = scores[-5:]
        avg = sum(s.grade for s in recent) / len(recent)
        print(f"\n5-visit rolling average: {avg:.1f}")

    sys.exit(0 if latest.grade >= 60 else 1)


if __name__ == "__main__":
    main()
