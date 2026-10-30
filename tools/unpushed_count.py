#!/usr/bin/env python3
"""unpushed_count.py — measure how far the local branch is ahead of origin.

the caretaker needs to know not just *whether* push works, but *how much*
has accumulated. a one-commit lag self-heals on the next batch cycle; a
thirty-commit lag means the deploy key has been broken for hours and a
human needs to intervene.

exit codes:
  0 — synced (0 unpushed commits)
  1 — nominal (1–5 unpushed)
  2 — growing (6–20 unpushed)
  3 — backlog (21+ unpushed)
  4 — cannot determine (no remote, detached HEAD, etc.)

usage:
  python3 tools/unpushed_count.py [--json]
"""

import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

THRESHOLDS = [
    (0, 0, "synced"),
    (1, 5, "nominal"),
    (6, 20, "growing"),
    (21, float("inf"), "backlog"),
]


def classify(count):
    """return (exit_code, label) for a given unpushed count."""
    for exit_code, (lo, hi, label) in enumerate(THRESHOLDS):
        if lo <= count <= hi:
            return exit_code, label
    return 3, "backlog"


def count_unpushed(repo=REPO):
    """count commits on current branch not yet on origin/main."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=10,
        )
        if result.returncode != 0:
            return None, result.stderr.strip()
        return int(result.stdout.strip()), None
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as exc:
        return None, str(exc)


def measure(repo=REPO):
    """produce a full report dict."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    count, error = count_unpushed(repo)

    if count is None:
        return {
            "timestamp": ts,
            "unpushed": None,
            "severity": "unknown",
            "exit_code": 4,
            "error": error,
        }

    exit_code, label = classify(count)
    return {
        "timestamp": ts,
        "unpushed": count,
        "severity": label,
        "exit_code": exit_code,
        "error": None,
    }


def human_summary(report):
    """one-line human-readable summary."""
    if report["unpushed"] is None:
        return f"cannot determine unpushed count: {report['error']}"
    count = report["unpushed"]
    label = report["severity"]
    if count == 0:
        return "synced — remote is up to date"
    return f"{count} unpushed commit(s) [{label}]"


def main():
    use_json = "--json" in sys.argv
    report = measure()

    if use_json:
        print(json.dumps(report, indent=2))
    else:
        print(human_summary(report))

    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
