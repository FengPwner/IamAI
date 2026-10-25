#!/usr/bin/env python3
"""CLI: caretaker dashboard — one-call snapshot for a caretaker visit.

Usage:
    python3 tools/caretaker_dashboard.py              # human-readable
    python3 tools/caretaker_dashboard.py --json       # machine-readable

Exit codes:
    0  healthy
    1  attention
    2  critical
    3  error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_dashboard import (  # noqa: E402
    dashboard_snapshot,
    format_snapshot,
)

_VERDICT_EXIT = {
    "healthy": 0,
    "attention": 1,
    "critical": 2,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Caretaker dashboard snapshot.")
    ap.add_argument("--writer", default="qwen",
                    help="writer identity (default: qwen)")
    ap.add_argument("--freshness-healthy", type=float, default=120.0,
                    help="max age (s) for healthy freshness (default 120)")
    ap.add_argument("--freshness-degraded", type=float, default=600.0,
                    help="max age (s) for degraded freshness (default 600)")
    ap.add_argument("--momentum-window", type=float, default=12.0,
                    help="commit momentum window in hours (default 12)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    try:
        snap = dashboard_snapshot(
            repo=REPO,
            writer=args.writer,
            freshness_healthy_sec=args.freshness_healthy,
            freshness_degraded_sec=args.freshness_degraded,
            momentum_window_hours=args.momentum_window,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(snap, indent=2))
    else:
        print(format_snapshot(snap))

    return _VERDICT_EXIT.get(snap["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
