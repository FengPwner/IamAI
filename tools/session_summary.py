#!/usr/bin/env python3
"""CLI: summarise a caretaker visit.

Reads git log, strokes.jsonl, and writer state to report what happened
during the current (or specified) visit window.

Usage:
    python3 tools/session_summary.py                             # current visit
    python3 tools/session_summary.py --since 2026-10-21T12:00:00+00:00
    python3 tools/session_summary.py --json                      # machine output
    python3 tools/session_summary.py --writer qwen               # explicit writer

Exit codes:
    0  summary produced
    1  insufficient data / error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.session_summary import summarise, report_line  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default=None, help="visit start ISO-8601 timestamp")
    ap.add_argument("--writer", default=None, help="writer id (default: from env or 'qwen')")
    ap.add_argument("--json", action="store_true", help="dump JSON report")
    args = ap.parse_args()

    writer = args.writer or "qwen"

    try:
        info = summarise(
            repo=REPO,
            visit_start_iso=args.since,
            writer=writer,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(report_line(info))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
