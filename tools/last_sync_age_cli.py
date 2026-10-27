#!/usr/bin/env python3
"""CLI: last_sync_age — how long since the last successful git push?

Usage:
    python3 tools/last_sync_age_cli.py
    python3 tools/last_sync_age_cli.py --json

Exit codes:
    0  fresh   (synced within last hour)
    1  stale   (1–24 hours since sync)
    2  cold    (1–7 days since sync)
    3  frozen  (> 7 days or unknown)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.last_sync_age import last_sync_age, last_sync_summary  # noqa: E402


_EXIT_CODES = {"fresh": 0, "stale": 1, "cold": 2, "frozen": 3}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure time since last successful git push.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output JSON instead of human text.",
    )
    args = parser.parse_args()

    info = last_sync_age()

    if args.as_json:
        print(json.dumps(info, indent=2))
    else:
        health_tag = info["sync_health"].upper()
        print(f"last sync age: {info['sync_age_human']}  [{health_tag}]")
        if info["last_synced_sha"]:
            print(f"  last synced sha:   {info['last_synced_sha']}")
            print(f"  last synced at:    {info['last_synced_ts']}")
        else:
            print("  last synced sha:   (unknown — origin/main not found)")
        ahead = info["local_ahead"]
        if ahead >= 0:
            print(f"  local ahead:       {ahead} commits")
        else:
            print("  local ahead:       unknown")
        print(f"  summary: {last_sync_summary()}")

    return _EXIT_CODES.get(info["sync_health"], 3)


if __name__ == "__main__":
    raise SystemExit(main())
