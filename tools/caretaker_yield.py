#!/usr/bin/env python3
"""CLI: classify caretaker visits and print a yield summary.

Usage:
    python3 tools/caretaker_yield.py                    # scan notes/
    python3 tools/caretaker_yield.py --notes notes/     # custom dir
    python3 tools/caretaker_yield.py --last 20           # last 20 visits

Reads caretaker-visit-*.md files, extracts signals from the
"## What happened" / "## Action taken" sections, and classifies each
visit's yield type.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_yield import (  # noqa: E402
    VisitLedger,
    VisitRecord,
    classify_visit,
    yield_report,
    yield_score,
)


# ── filename parsing ──────────────────────────────────────────────────

_VISIT_RE = re.compile(
    r"caretaker-visit-(\d+)(?:-(\d{4}-\d{2}-\d{2}))?\.md$", re.IGNORECASE
)


def parse_visit_id(filename: str) -> int | None:
    m = _VISIT_RE.search(filename)
    return int(m.group(1)) if m else None


# ── content heuristics ────────────────────────────────────────────────

def _has_section(text: str, *keywords: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in keywords)


def classify_from_file(path: Path) -> VisitRecord | None:
    """Extract signals from a caretaker visit note."""
    vid = parse_visit_id(path.name)
    if vid is None:
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    low = text.lower()

    # detect restart
    processes_alive = not any(
        kw in low for kw in [
            "not running", "restarted", "restart", "reclaim",
            "processes were found dead", "dead on arrival",
        ]
    )

    # detect backlog commit
    backlog = any(
        kw in low for kw in [
            "backlog", "pending files", "uncommitted",
            "catch-up: commit", "committed pending",
        ]
    )

    # detect new content
    new_content = any(
        kw in low for kw in [
            "wrote new", "new feature", "new module", "new test",
            "new note", "added", "implemented",
        ]
    )

    # detect strokes lost
    strokes_lost = 0
    m = re.search(r"(\d+)\s+strokes?\s+lost", low)
    if m:
        strokes_lost = int(m.group(1))

    # detect files committed
    files_committed = 0
    m = re.search(r"(\d+)\s+files?\s+changed", low)
    if m:
        files_committed = int(m.group(1))

    return VisitRecord(
        visit_id=vid,
        processes_alive=processes_alive,
        backlog_committed=backlog,
        new_content_written=new_content,
        strokes_lost=strokes_lost,
        files_committed=files_committed,
    )


# ── main ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--notes", default=str(REPO / "notes"),
                    help="directory with caretaker-visit-*.md files")
    ap.add_argument("--last", type=int, default=0,
                    help="only analyze the last N visits (0 = all)")
    args = ap.parse_args()

    notes_dir = Path(args.notes)
    if not notes_dir.is_dir():
        print(f"error: {notes_dir} is not a directory", file=sys.stderr)
        return 1

    # collect and sort
    files = sorted(notes_dir.glob("caretaker-visit-*.md"))
    if not files:
        print(f"no caretaker-visit-*.md files found in {notes_dir}")
        return 0

    if args.last > 0:
        files = files[-args.last:]

    ledger = VisitLedger()
    for f in files:
        rec = classify_from_file(f)
        if rec is not None:
            try:
                ledger.add(rec)
            except ValueError:
                pass  # duplicate or out of order

    if ledger.count == 0:
        print("no parseable visit records found")
        return 0

    report = yield_report(ledger)

    print(f"=== caretaker yield report ===")
    print(f"visits analyzed: {report['total_visits']}")
    print(f"mean yield score: {report['mean_score']}/4.00")
    print(f"clean rate: {report['clean_rate']:.1%}")
    print(f"strokes lost: {report['total_strokes_lost']}")
    print(f"files committed: {report['total_files_committed']}")
    print()
    print("type breakdown:")
    for t, c in sorted(report["type_counts"].items()):
        print(f"  {t:14s}  {c:4d}  ({c/report['total_visits']:.1%})")
    print(f"\ndominant type: {report['dominant_type']}")
    print(f"last 5 visits: {', '.join(report['recent_5'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
