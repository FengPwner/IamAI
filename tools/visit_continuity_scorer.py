#!/usr/bin/env python3
"""CLI wrapper for iamai.visit_continuity_scorer — assess caretaker health.

Parses caretaker visit notes from the notes/ directory and scores the
continuity of the automated writing pipeline.

Usage:
    python3 tools/visit_continuity_scorer.py                  # last 20 visits
    python3 tools/visit_continuity_scorer.py --last 50        # last 50 visits
    python3 tools/visit_continuity_scorer.py --all            # every visit
    python3 tools/visit_continuity_scorer.py --json           # JSON output

Exit codes:
    0  analysis complete
    1  no visit notes found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.visit_continuity_scorer import score_visits, health_grade  # noqa: E402

TZ_CN = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Visit note parser
# ---------------------------------------------------------------------------

_VISIT_RE = re.compile(
    r"caretaker visit (\d+)", re.IGNORECASE
)
_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})"
)
_ALIVE_RE = re.compile(
    r"writer.*?(running|alive|up|NOT running|dead|down|recycled|reclaim)",
    re.IGNORECASE,
)
_STROKE_RE = re.compile(
    r"(\d+)\s*strokes", re.IGNORECASE
)
_PENDING_RE = re.compile(
    r"(\d+)\s*(?:file|pending|uncommitted)", re.IGNORECASE
)


def _parse_visit_file(path: Path) -> dict | None:
    """Extract structured data from a caretaker visit note."""
    text = path.read_text(errors="replace")

    # Visit number
    m_num = _VISIT_RE.search(path.stem)
    visit_num = int(m_num.group(1)) if m_num else 0

    # Timestamp from filename or content
    m_ts = _TS_RE.search(text)
    ts = 0.0
    if m_ts:
        try:
            dt = datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=TZ_CN)
            ts = dt.timestamp()
        except ValueError:
            pass
    if ts == 0.0:
        # Fallback: file modification time
        ts = path.stat().st_mtime

    # Alive status
    alive = True  # default assume alive
    for m in _ALIVE_RE.finditer(text):
        val = m.group(1).lower()
        if any(w in val for w in ("not", "dead", "down", "recycled", "reclaim")):
            alive = False
            break

    # Strokes
    m_strokes = _STROKE_RE.search(text)
    strokes = int(m_strokes.group(1)) if m_strokes else 0

    # Pending
    m_pending = _PENDING_RE.search(text)
    pending = int(m_pending.group(1)) if m_pending else 0

    return {
        "visit": visit_num,
        "ts": ts,
        "alive": alive,
        "strokes": strokes,
        "pending": pending,
        "file": path.name,
    }


def collect_visits(notes_dir: Path, last_n: int | None = 20) -> list[dict]:
    """Parse visit notes from the notes directory."""
    visit_files = sorted(
        notes_dir.glob("caretaker-visit-*.md"),
        key=lambda p: p.name,
    )

    if last_n is not None:
        visit_files = visit_files[-last_n:]

    visits = []
    for f in visit_files:
        v = _parse_visit_file(f)
        if v:
            visits.append(v)

    return sorted(visits, key=lambda v: v["ts"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Score caretaker visit continuity.")
    ap.add_argument("--last", type=int, default=20, help="Number of recent visits (0=all)")
    ap.add_argument("--all", action="store_true", help="Analyse all visits")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--notes-dir", type=Path, default=REPO / "notes")
    args = ap.parse_args()

    last_n = None if args.all else args.last
    visits = collect_visits(args.notes_dir, last_n=last_n)

    if not visits:
        print("No visit notes found in", args.notes_dir, file=sys.stderr)
        sys.exit(1)

    result = score_visits(visits)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Caretaker Health Report — last {result['visit_count']} visits")
        print(f"  Span: {result['span_s'] / 3600:.1f} hours")
        print(f"  Cadence regularity:  {result['cadence_regularity']:.2f}")
        print(f"  Alive fraction:      {result['alive_fraction']:.2f}")
        print(f"  Recovery promptness: {result['recovery_promptness']:.2f}")
        print(f"  Content momentum:    {result['content_momentum']:.2f}")
        print(f"  Commit freshness:    {result['commit_freshness']:.2f}")
        print(f"  ─────────────────────────────")
        print(f"  Health score:        {result['health_score']:.2f}  Grade: {result['grade']}")


if __name__ == "__main__":
    main()
