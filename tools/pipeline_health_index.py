#!/usr/bin/env python3
"""CLI wrapper for iamai.pipeline_health_index — single-number pipeline health.

Usage:
    python3 tools/pipeline_health_index.py              # auto-detect from repo
    python3 tools/pipeline_health_index.py --json       # machine-readable output

Exit codes:
    0  healthy (index >= 0.80)
    1  warn (0.50–0.79)
    2  critical (0.20–0.49)
    3  down (< 0.20) or error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.pipeline_health_index import PipelineHealthIndex  # noqa: E402

_VERDICT_EXIT = {"healthy": 0, "warn": 1, "critical": 2, "down": 3}


def _get_writer_freshness(repo: Path) -> float:
    """Seconds since last stroke in data/strokes.jsonl."""
    path = repo / "data" / "strokes.jsonl"
    if not path.exists():
        return 9999.0
    lines = path.read_text().splitlines()
    if not lines:
        return 9999.0
    last = None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            ts = rec.get("ts") or rec.get("timestamp")
            if ts:
                last = ts
                break
        except json.JSONDecodeError:
            continue
    if last is None:
        return 9999.0
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).total_seconds())
    except (ValueError, TypeError):
        return 9999.0


def _get_commit_freshness(repo: Path) -> float:
    """Seconds since last local commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode != 0:
            return 9999.0
        ts = result.stdout.strip()
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).total_seconds())
    except Exception:
        return 9999.0


def _get_uncommitted(repo: Path) -> int:
    """Count of uncommitted files."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        return len([l for l in result.stdout.splitlines() if l.strip()])
    except Exception:
        return 999


def _get_unpushed(repo: Path) -> int:
    """Count of unpushed commits."""
    try:
        result = subprocess.run(
            ["git", "log", "@{u}..", "--oneline"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode != 0:
            return 0
        return len([l for l in result.stdout.splitlines() if l.strip()])
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="emit JSON instead of text")
    args = ap.parse_args()

    idx = PipelineHealthIndex()

    wf = _get_writer_freshness(REPO)
    cf = _get_commit_freshness(REPO)
    uc = _get_uncommitted(REPO)
    up = _get_unpushed(REPO)

    result = idx.compute(wf, cf, uc, up)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(idx.summary(wf, cf, uc, up))

    return _VERDICT_EXIT.get(result["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
