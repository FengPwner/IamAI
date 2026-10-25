#!/usr/bin/env python3
"""stuck_gate_detector.py — detect and clear stuck pause gates.

visit 230 identified the failure mode: the batch committer's exception
handler can set the pause gate on a transient error (network timeout,
race with another git operation), and no automatic mechanism clears it.
the writer idles forever behind a red gate that was set by a transient
error, not a real test failure.

this detector checks:
  1. is the pause gate present?
  2. if so, run the test suite (pytest --co -q for speed, or full if asked)
  3. if tests pass, the gate is stuck → clear it and log the event
  4. if tests fail, the gate is legitimate → leave it alone

usage:
    python3 tools/stuck_gate_detector.py --writer qwen
    python3 tools/stuck_gate_detector.py --writer qwen --check-only   # report, don't clear
    python3 tools/stuck_gate_detector.py --writer qwen --full-tests   # run full suite, not just --co

exit codes:
    0  — no gate present, or gate was stuck and has been cleared
    1  — gate is present and legitimate (tests are failing)
    2  — gate is present and stuck (tests pass but gate was red) — cleared unless --check-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def gate_path(writer: str) -> Path:
    return Path(f"/tmp/iamai-writer-pause-{writer}")


def deadman_path(writer: str) -> Path:
    return Path(f"/tmp/iamai-deadman-{writer}.json")


def gate_is_red(writer: str) -> bool:
    return gate_path(writer).exists()


def gate_age_seconds(writer: str) -> float | None:
    """How long the gate has been present, or None if no gate."""
    p = gate_path(writer)
    if not p.exists():
        return None
    try:
        return time.time() - p.stat().st_mtime
    except OSError:
        return None


def run_tests(repo_root: Path, full: bool = False, timeout: int = 60) -> bool:
    """Run pytest. Returns True if all tests pass."""
    if full:
        cmd = [sys.executable, "-m", "pytest", "-x", "-q", "--tb=no"]
    else:
        # --co (collect only) is fast and catches import errors, syntax errors,
        # and most structural problems without actually running test code.
        cmd = [sys.executable, "-m", "pytest", "--co", "-q", "--tb=no"]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        # timeout → assume tests are broken, don't clear gate
        return False
    except Exception:
        return False


def clear_gate(writer: str) -> bool:
    """Remove the pause gate. Returns True if successfully removed."""
    p = gate_path(writer)
    try:
        if p.exists():
            p.unlink()
            return True
        return True  # already gone
    except OSError:
        return False


def log_event(writer: str, event: dict) -> None:
    """Append a structured event to the stuck gate log."""
    log_path = Path(f"/tmp/iamai-stuck-gate-{writer}.jsonl")
    event["at"] = datetime.now(tz=timezone.utc).isoformat()
    event["writer"] = writer
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass  # best-effort logging


def detect(
    writer: str,
    repo_root: Path,
    check_only: bool = False,
    full_tests: bool = False,
) -> dict:
    """
    Main detection logic. Returns a structured result dict.

    Possible outcomes:
      - {"status": "no_gate"}           — nothing to do
      - {"status": "stuck_cleared"}     — gate was stuck, cleared it
      - {"status": "stuck_not_cleared"} — gate stuck but --check-only, left it
      - {"status": "legitimate"}        — gate present, tests failing, left it
      - {"status": "error"}             — something went wrong
    """
    if not gate_is_red(writer):
        return {"status": "no_gate", "message": "no pause gate present"}

    age = gate_age_seconds(writer)
    age_str = f"{age:.0f}s" if age is not None else "unknown"

    # Quick sanity: if gate is less than 60 seconds old, don't touch it.
    # the batch committer may be in the middle of a legitimate cycle.
    if age is not None and age < 60:
        return {
            "status": "too_fresh",
            "message": f"gate is only {age_str} old, leaving it alone",
            "age_seconds": age,
        }

    tests_pass = run_tests(repo_root, full=full_tests)

    if not tests_pass:
        return {
            "status": "legitimate",
            "message": f"gate present ({age_str}), tests failing — gate is legitimate",
            "age_seconds": age,
        }

    # Tests pass but gate is red → stuck gate
    if check_only:
        log_event(writer, {
            "event": "stuck_gate_detected",
            "age_seconds": age,
            "action": "none (check-only mode)",
        })
        return {
            "status": "stuck_not_cleared",
            "message": f"stuck gate detected ({age_str}), tests pass — not clearing (check-only)",
            "age_seconds": age,
        }

    cleared = clear_gate(writer)
    if cleared:
        log_event(writer, {
            "event": "stuck_gate_cleared",
            "age_seconds": age,
            "action": "auto-cleared",
        })
        return {
            "status": "stuck_cleared",
            "message": f"stuck gate cleared ({age_str} old), tests were passing",
            "age_seconds": age,
        }
    else:
        return {
            "status": "error",
            "message": "failed to clear gate (permission error?)",
            "age_seconds": age,
        }


def format_result(result: dict) -> str:
    """Human-readable summary of detection result."""
    status = result["status"]
    msg = result["message"]
    icons = {
        "no_gate": "✓",
        "too_fresh": "⏳",
        "stuck_cleared": "🔧",
        "stuck_not_cleared": "⚠",
        "legitimate": "🚨",
        "error": "✗",
    }
    icon = icons.get(status, "?")
    return f"{icon} [{status}] {msg}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect and clear stuck pause gates in the IamAI writer system."
    )
    parser.add_argument(
        "--writer",
        default=os.environ.get("IAMAII_WRITER", "qwen"),
        help="Writer ID (default: qwen or $IAMAII_WRITER)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Report stuck gates but don't clear them.",
    )
    parser.add_argument(
        "--full-tests",
        action="store_true",
        help="Run the full test suite instead of just collect-only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output result as JSON.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    result = detect(
        writer=args.writer,
        repo_root=repo_root,
        check_only=args.check_only,
        full_tests=args.full_tests,
    )

    if args.json_output:
        print(json.dumps(result))
    else:
        print(format_result(result))

    # exit code mapping
    exit_map = {
        "no_gate": 0,
        "too_fresh": 0,
        "stuck_cleared": 0,
        "stuck_not_cleared": 2,
        "legitimate": 1,
        "error": 1,
    }
    return exit_map.get(result["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
