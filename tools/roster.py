#!/usr/bin/env python3
"""Who is writing this repo right now? Reads the state files on disk, prints a table.

    python3 tools/roster.py            # markdown table of every writer
    python3 tools/roster.py --summary  # one line, for a commit body
    python3 tools/roster.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import roster as R  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--every", type=int, default=15, help="stroke cadence used for 'alive'")
    ap.add_argument("--summary", action="store_true", help="single line")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--include-legacy", action="store_true", help="also list the pre-namespacing shared file")
    args = ap.parse_args()

    rows = R.roster(every=args.every, include_legacy=args.include_legacy)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.summary:
        print(R.summary(every=args.every))
    else:
        print(R.as_markdown(rows))
    return 0 if R.alive_writers(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
