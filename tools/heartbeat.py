#!/usr/bin/env python3
"""Probe: is the writer still writing? Prints one line, exits 1 when stalled.

    python3 tools/heartbeat.py            # human-readable health line
    python3 tools/heartbeat.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import heartbeat  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=int, default=600, help="commit window in seconds")
    ap.add_argument("--every", type=int, default=15, help="stroke cadence in seconds")
    ap.add_argument("--json", action="store_true", help="dump the whole report")
    ap.add_argument("--writer", default=None, help="which writer's bookkeeping to read")
    args = ap.parse_args()

    beat = heartbeat.beat(interval=args.interval, every=args.every, writer_id=args.writer)
    if args.json:
        print(json.dumps(beat, ensure_ascii=False, indent=2))
    else:
        print(heartbeat.as_markdown(beat))
    return 1 if beat["stalled"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
