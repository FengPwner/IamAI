#!/usr/bin/env python3
"""unpushed_age.py — CLI wrapper for iamai.unpushed_age.

measures how long the oldest unpushed local commit has been sitting.
complements unpushed_count.py: count tells you *how many*; age tells
you *how long*.

exit codes:
  0 — synced (no unpushed commits)
  1 — fresh (< 10 min)
  2 — aging (10–30 min)
  3 — stale (30–60 min)
  4 — critical (> 1 hour)
  5 — cannot determine

usage:
  python3 tools/unpushed_age.py [--json] [--oneline]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.unpushed_age import measure_unpushed_age


def main() -> int:
    parser = argparse.ArgumentParser(
        description="check age of oldest unpushed commit"
    )
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--oneline", action="store_true", help="single-line summary")
    args = parser.parse_args()

    result = measure_unpushed_age(REPO)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif args.oneline:
        print(result.summary())
    else:
        print(result.summary())
        if result.age_seconds is not None:
            print(f"  age: {result.age_seconds:.0f}s ({result.age_seconds/60:.1f} min)")
        print(f"  unpushed: {result.unpushed_count}")
        print(f"  label: {result.label}")

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
