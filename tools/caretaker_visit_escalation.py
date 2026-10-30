#!/usr/bin/env python3
"""CLI: caretaker_visit_escalation — detect when caretaker visits repeat the same fix.

Reads the caretaker visit log and scores whether the same action is
being repeated too many times in a row, indicating the caretaker is
masking a deeper issue instead of solving it.

Usage:
    python3 tools/caretaker_visit_escalation.py
    python3 tools/caretaker_visit_escalation.py --last 20
    python3 tools/caretaker_visit_escalation.py --json
    python3 tools/caretaker_visit_escalation.py --report

Exit codes:
    0  analysis complete
    1  no visit log found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_visit_escalation import (  # noqa: E402
    escalation_score,
    escalation_report,
    needs_escalation,
)


def _parse_visit_log(log_path: Path, last_n: int | None = None) -> list[str]:
    """Extract action names from caretaker visit log entries.

    Each line like "visit 394 at 17:01, restarted both processes" yields
    an action string.  We extract the first verb-like word after the
    timestamp.
    """
    actions = []
    if not log_path.exists():
        return actions

    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        # Match patterns like "visit NNN at HH:MM, <action>..."
        m = re.search(r"visit\s+\d+\s+at\s+\d+:\d+,\s*(\w+)", line)
        if m:
            actions.append(m.group(1).lower())

    if last_n is not None:
        actions = actions[-last_n:]
    return actions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--last",
        type=int,
        default=None,
        help="only analyse the last N visits (default: all)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON",
    )
    ap.add_argument(
        "--report",
        action="store_true",
        help="include per-visit history breakdown",
    )
    ap.add_argument(
        "--log",
        type=str,
        default=None,
        help="path to visit log (default: data/caretaker_visits.log)",
    )
    args = ap.parse_args()

    log_path = Path(args.log) if args.log else REPO / "data" / "caretaker_visits.log"

    actions = _parse_visit_log(log_path, last_n=args.last)

    if not actions:
        print(f"No visit log found at {log_path} or log is empty.", file=sys.stderr)
        return 1

    if args.report:
        result = escalation_report(actions)
    else:
        result = escalation_score(actions)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        level = result["level"]
        streak = result["streak"]
        action = result["action"]
        total = result["total"]

        print(f"caretaker visit escalation: {level.upper()}")
        print(f"  trailing streak: {streak}x {action!r} (of {total} total visits)")
        print(f"  summary: {result['summary']}")

        if args.report and "history" in result:
            print()
            print("  history:")
            for h in result["history"]:
                print(f"    {h['action']:<12} streak={h['streak']}")

        if needs_escalation(actions):
            print()
            print("  *** ESCALATION NEEDED — human intervention required ***")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
