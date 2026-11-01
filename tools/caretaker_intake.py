#!/usr/bin/env python3
"""CLI wrapper for iamai.caretaker_intake — run full arrival diagnosis.

Usage:
    python3 tools/caretaker_intake.py            # human-readable output
    python3 tools/caretaker_intake.py --json     # JSON output
    python3 tools/caretaker_intake.py --quiet    # exit code only

Exit codes:
    0  verdict = healthy
    1  verdict = attention
    2  verdict = action
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_intake import run_intake, format_intake  # noqa: E402


EXIT_CODES = {"healthy": 0, "attention": 1, "action": 2}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run caretaker arrival diagnosis."
    )
    parser.add_argument(
        "--json", action="store_true", help="Output JSON instead of text."
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress output, exit code only."
    )
    parser.add_argument(
        "--repo", default=str(REPO), help="Path to repo root."
    )
    args = parser.parse_args()

    report = run_intake(repo_path=args.repo)

    if not args.quiet:
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, default=str))
        else:
            print(format_intake(report))

    sys.exit(EXIT_CODES.get(report.verdict, 2))


if __name__ == "__main__":
    main()
