#!/usr/bin/env python3
"""caretaker_exit_checklist.py — pre-departure sanity check for caretakers.

Before a caretaker session ends, this tool verifies that the repo is in
a healthy handoff state: writer alive, batch alive, no uncommitted drift,
recent commits, and no pause gate left stuck.

Usage:
    python3 tools/caretaker_exit_checklist.py
    python3 tools/caretaker_exit_checklist.py --writer qwen
    python3 tools/caretaker_exit_checklist.py --json

Exit codes:
    0 — all checks passed, safe to leave
    1 — one or more checks failed, review before departing
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GMT8 = timezone(timedelta(hours=8))


def _pid_alive(pid: int) -> bool:
    """Check whether a PID is alive without killing it."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _find_pid(cmd_pattern: str) -> int | None:
    """Find the PID of a running process matching cmd_pattern."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", cmd_pattern],
            capture_output=True, text=True, timeout=5
        )
        pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
        return pids[0] if pids else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _latest_stroke_age(strokes_path: Path) -> float | None:
    """Return seconds since the last stroke, or None if no strokes exist."""
    if not strokes_path.exists():
        return None
    last_line = ""
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                last_line = stripped
    if not last_line:
        return None
    try:
        data = json.loads(last_line)
        at_str = data.get("at", "")
        dt = datetime.fromisoformat(at_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def _uncommitted_count() -> int:
    """Count uncommitted tracked files."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO)
        )
        return len([l for l in result.stdout.strip().split("\n") if l.strip()])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1


def _unpushed_count() -> int:
    """Count commits ahead of origin/main."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO)
        )
        return int(result.stdout.strip()) if result.returncode == 0 else -1
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return -1


def _pause_gate_active(writer: str = "qwen") -> bool:
    """Check whether the pause gate file exists."""
    pause_file = REPO / "data" / f"pause.{writer}"
    if not pause_file.exists():
        # fallback: /tmp/iamai-writer-pause
        pause_file = Path(f"/tmp/iamai-{writer}-pause")
    return pause_file.exists()


def _last_commit_age() -> float | None:
    """Return seconds since the most recent commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=10, cwd=str(REPO)
        )
        if result.returncode == 0 and result.stdout.strip():
            ts = int(result.stdout.strip())
            return time.time() - ts
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def run_checklist(writer: str = "qwen") -> dict:
    """Run all exit checks and return a structured report."""
    now = datetime.now(GMT8).strftime("%Y-%m-%d %H:%M:%S CST")
    checks = {}

    # 1. writer alive
    writer_pid = _find_pid(f"writer_loop.py.*--writer {writer}")
    checks["writer_alive"] = {
        "pass": writer_pid is not None and _pid_alive(writer_pid),
        "pid": writer_pid,
        "detail": f"writer pid {writer_pid}" if writer_pid else "writer not found"
    }

    # 2. batch committer alive
    batch_pid = _find_pid(f"commit_batch.py.*--writer {writer}")
    checks["batch_alive"] = {
        "pass": batch_pid is not None and _pid_alive(batch_pid),
        "pid": batch_pid,
        "detail": f"batch pid {batch_pid}" if batch_pid else "batch not found"
    }

    # 3. pause gate
    pause_active = _pause_gate_active(writer)
    checks["pause_gate_clear"] = {
        "pass": not pause_active,
        "detail": "pause gate OFF" if not pause_active else "⚠ pause gate STUCK"
    }

    # 4. uncommitted drift
    uncommitted = _uncommitted_count()
    checks["low_uncommitted"] = {
        "pass": 0 <= uncommitted <= 5,
        "count": uncommitted,
        "detail": f"{uncommitted} uncommitted files" if uncommitted >= 0 else "could not check"
    }

    # 5. unpushed commits
    unpushed = _unpushed_count()
    checks["low_unpushed"] = {
        "pass": 0 <= unpushed <= 2,
        "count": unpushed,
        "detail": f"{unpushed} unpushed commits" if unpushed >= 0 else "could not check"
    }

    # 6. recent stroke activity
    strokes_path = REPO / "data" / "strokes.jsonl"
    stroke_age = _latest_stroke_age(strokes_path)
    max_stroke_gap = 60.0  # 60s threshold for a 15s cadence writer
    checks["strokes_fresh"] = {
        "pass": stroke_age is not None and stroke_age <= max_stroke_gap,
        "age_seconds": round(stroke_age, 1) if stroke_age is not None else None,
        "detail": f"last stroke {stroke_age:.0f}s ago" if stroke_age else "no strokes found"
    }

    # 7. recent commit activity
    commit_age = _last_commit_age()
    max_commit_gap = 900.0  # 15 min threshold
    checks["commit_fresh"] = {
        "pass": commit_age is not None and commit_age <= max_commit_gap,
        "age_seconds": round(commit_age, 1) if commit_age is not None else None,
        "detail": f"last commit {commit_age:.0f}s ago" if commit_age else "no commit timestamp"
    }

    all_pass = all(c["pass"] for c in checks.values())
    return {
        "timestamp": now,
        "writer": writer,
        "all_pass": all_pass,
        "verdict": "SAFE TO DEPART" if all_pass else "REVIEW BEFORE LEAVING",
        "checks": checks
    }


def format_report(report: dict) -> str:
    """Format the checklist as a human-readable string."""
    lines = [
        f"═══ Caretaker Exit Checklist — {report['timestamp']} ═══",
        f"Writer: {report['writer']}",
        f"Verdict: {report['verdict']}",
        ""
    ]
    for name, check in report["checks"].items():
        status = "✓" if check["pass"] else "✗"
        lines.append(f"  {status} {name:24s} {check['detail']}")
    lines.append("")
    if report["all_pass"]:
        lines.append("All clear. Safe to hand off.")
    else:
        failed = [n for n, c in report["checks"].items() if not c["pass"]]
        lines.append(f"Failed: {', '.join(failed)}")
        lines.append("Fix these before departing.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default="qwen", help="writer name (default: qwen)")
    ap.add_argument("--json", action="store_true", help="output as JSON")
    args = ap.parse_args()

    report = run_checklist(writer=args.writer)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
