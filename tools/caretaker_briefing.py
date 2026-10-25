#!/usr/bin/env python3
"""caretaker_briefing.py — CLI wrapper for the caretaker briefing module.

Generates a quick status summary when a caretaker arrives.

Usage:
    python3 tools/caretaker_briefing.py
    python3 tools/caretaker_briefing.py --since abc1234
    python3 tools/caretaker_briefing.py --since abc1234 --writer qwen --json
"""

import argparse
import json
import sys
from pathlib import Path

# allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.caretaker_briefing import brief


def main():
    parser = argparse.ArgumentParser(
        description="Generate a caretaker arrival briefing."
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Commit hash of the last caretaker visit (counts activity since then).",
    )
    parser.add_argument(
        "--writer",
        default="qwen",
        help="Writer identifier (default: qwen).",
    )
    parser.add_argument(
        "--cadence",
        type=float,
        default=15.0,
        help="Expected seconds between strokes (default: 15).",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to the repo root (default: cwd).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output machine-readable JSON instead of human text.",
    )
    args = parser.parse_args()

    b = brief(
        repo_path=args.repo,
        since_commit=args.since,
        writer_id=args.writer,
        cadence=args.cadence,
    )

    if args.as_json:
        out = {
            "strokes_since_visit": b.strokes_since_visit,
            "commits_since_visit": b.commits_since_visit,
            "writer_alive": b.writer_alive,
            "batch_alive": b.batch_alive,
            "uncommitted_files": b.uncommitted_files,
            "push_lag": b.push_lag,
            "longest_gap_seconds": b.longest_gap_seconds,
            "cadence_seconds": b.cadence_seconds,
            "stall_detected": b.stall_detected,
            "healthy": b.healthy,
            "warnings": b.warnings,
            "duration_seconds": b.duration_seconds,
        }
        print(json.dumps(out, indent=2))
    else:
        print(b.summary())

    sys.exit(0 if b.healthy else 1)


if __name__ == "__main__":
    main()
