#!/usr/bin/env python3
"""CLI wrapper for iamai.repo_heartbeat — is the repository still alive?

Combines commit freshness, stroke freshness, and process liveness into
a single verdict: healthy / degraded / dead.

Usage:
    python3 tools/repo_heartbeat.py                    # check everything
    python3 tools/repo_heartbeat.py --writer qwen      # specify writer name
    python3 tools/repo_heartbeat.py --json             # machine-readable output
    python3 tools/repo_heartbeat.py --max-commit-gap 600  # tighter commit threshold

Exit codes:
    0  healthy — all signals green
    1  degraded — one signal lagging
    2  dead — two or more signals failing
"""

import argparse
import json
import sys
from pathlib import Path

# Allow imports from the repo root when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.repo_heartbeat import HeartbeatVerdict, assess

VERBOSITY = {
    HeartbeatVerdict.HEALTHY: "HEALTHY",
    HeartbeatVerdict.DEGRADED: "DEGRADED",
    HeartbeatVerdict.DEAD: "DEAD",
}

EXIT_CODES = {
    HeartbeatVerdict.HEALTHY: 0,
    HeartbeatVerdict.DEGRADED: 1,
    HeartbeatVerdict.DEAD: 2,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess repository liveness.")
    parser.add_argument("--writer", default="qwen", help="Writer name (default: qwen)")
    parser.add_argument("--max-commit-gap", type=int, default=1200, help="Max commit age in seconds (default: 1200)")
    parser.add_argument("--max-stroke-gap", type=int, default=600, help="Max stroke age in seconds (default: 600)")
    parser.add_argument("--pid-dir", default="/tmp", help="Directory containing PID files (default: /tmp)")
    parser.add_argument("--json", dest="use_json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    report = assess(
        repo_root=repo_root,
        max_commit_gap=args.max_commit_gap,
        max_stroke_gap=args.max_stroke_gap,
        writer_name=args.writer,
        pid_dir=args.pid_dir,
    )

    if args.use_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        tag = VERBOSITY[report.verdict]
        print(f"[{tag}] repo heartbeat @ {report.checked_at}")
        for sig in report.signals:
            status = "OK" if sig.ok else "FAIL"
            print(f"  {status:4s} {sig.name:22s} {sig.detail}")

    return EXIT_CODES[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
