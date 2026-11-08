#!/usr/bin/env python3
"""CLI wrapper for iamai.restart_readiness — pre-restart readiness checks.

Usage:
    python tools/restart_readiness.py              # run all checks
    python tools/restart_readiness.py --json       # JSON output
    python tools/restart_readiness.py --check disk_space  # single check
    python tools/restart_readiness.py --list       # list available checks
"""

import argparse
import json
import sys
from pathlib import Path

# ensure iamai is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.restart_readiness import RestartReadinessChecker


def main():
    parser = argparse.ArgumentParser(
        description="Pre-restart environment readiness checker"
    )
    parser.add_argument(
        "--repo", default=".",
        help="path to the IamAI repo root (default: cwd)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="output results as JSON",
    )
    parser.add_argument(
        "--check", type=str, default=None,
        help="run a single named check",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="list available checks",
    )
    parser.add_argument(
        "--min-free-mb", type=int, default=100,
        help="minimum free disk space in MB (default: 100)",
    )
    parser.add_argument(
        "--max-dirty", type=int, default=50,
        help="max dirty files before warning (default: 50)",
    )
    parser.add_argument(
        "--ssh-key", type=str, default="/tmp/ssh_deploy_key",
        help="path to SSH deploy key (default: /tmp/ssh_deploy_key)",
    )

    args = parser.parse_args()
    checker = RestartReadinessChecker(
        repo_root=args.repo,
        min_free_mb=args.min_free_mb,
        max_dirty_files=args.max_dirty,
        ssh_key_path=args.ssh_key,
    )

    if args.list:
        for name in checker.check_names:
            print(f"  {name}")
        return 0

    if args.check:
        result = checker.check_one(args.check)
        if args.json_output:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            status_icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}[result.status]
            print(f"{status_icon} {result.name}: {result.detail}")
        return {"pass": 0, "warn": 0, "fail": 1}[result.status]

    report = checker.check_all()

    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for check in report.checks:
            status_icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}[check.status]
            print(f"  {status_icon} {check.name}: {check.detail}")
        print()
        print(f"  verdict: {report.verdict}")
        print(f"  elapsed: {report.elapsed_ms:.0f}ms")

    return 0 if report.verdict == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
