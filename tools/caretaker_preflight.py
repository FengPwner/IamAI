#!/usr/bin/env python3
"""caretaker_preflight.py — unified preflight gate before commit/push.

Runs five health checks (git locks, stroke freshness, branch drift,
process health, pending files) and produces a single verdict.

Usage:
    python3 tools/caretaker_preflight.py
    python3 tools/caretaker_preflight.py --json
    python3 tools/caretaker_preflight.py --oneline
    python3 tools/caretaker_preflight.py --writer doubao --cadence 20

Exit codes:
    0 — all checks ok
    1 — at least one check failed
    2 — warnings only, no failures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_preflight import (
    run_preflight,
    render_table,
    render_oneline,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", type=str, default="qwen",
                     help="writer id to check process health for (default: qwen)")
    ap.add_argument("--cadence", type=int, default=15,
                     help="expected stroke interval in seconds (default: 15)")
    ap.add_argument("--json", action="store_true", help="emit structured JSON report")
    ap.add_argument("--oneline", action="store_true", help="compact one-line summary")
    ap.add_argument("--repo", type=str, default=None, help="path to repo root")
    args = ap.parse_args()

    cwd = Path(args.repo) if args.repo else REPO
    report = run_preflight(repo=cwd, writer_id=args.writer, cadence=args.cadence)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    elif args.oneline:
        print(render_oneline(report))
    else:
        print(render_table(report))

    verdict = report.get("verdict", "ok")
    if verdict == "fail":
        return 1
    elif verdict == "warn":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
