#!/usr/bin/env python3
"""post_restart_health.py — quick health snapshot after a process restart.

Combines five critical signals into a single pass/warn/fail report:

  1. writer alive?        — pid file exists and process responds to SIG 0
  2. batch alive?         — same check for the commit batch process
  3. push current?        — local HEAD contains all of origin/main
  4. ssh key available?   — deploy key file exists with correct permissions
  5. stroke freshness?    — last stroke in strokes.jsonl is within 5× cadence

Usage:
    python3 tools/post_restart_health.py
    python3 tools/post_restart_health.py --writer qwen --cadence 15
    python3 tools/post_restart_health.py --json

Exit codes:
    0  all checks pass
    1  at least one warning
    2  at least one failure
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run(cmd: str, cwd: str | None = None) -> tuple[int, str, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _pid_alive(pidfile: Path) -> bool:
    """Check if the process recorded in *pidfile* is alive."""
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, signal.SIG_DFL)  # signal 0 — existence check
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def check_writer_alive(writer_id: str) -> dict:
    pidfile = Path(f"/tmp/iamai-writer-{writer_id}.pid")
    alive = _pid_alive(pidfile)
    return {
        "check": "writer_alive",
        "status": "pass" if alive else "fail",
        "detail": f"pid file {pidfile} — {'running' if alive else 'not running'}",
    }


def check_batch_alive(writer_id: str) -> dict:
    pidfile = Path(f"/tmp/iamai-batch-{writer_id}.pid")
    alive = _pid_alive(pidfile)
    return {
        "check": "batch_alive",
        "status": "pass" if alive else "fail",
        "detail": f"pid file {pidfile} — {'running' if alive else 'not running'}",
    }


def check_push_current(repo: Path) -> dict:
    """Is local HEAD at or ahead of origin/main?"""
    rc, out, _ = _run(
        "git rev-list --count HEAD..origin/main", cwd=str(repo)
    )
    remote_ahead = int(out) if rc == 0 and out.isdigit() else -1

    if remote_ahead < 0:
        return {
            "check": "push_current",
            "status": "warn",
            "detail": "could not compare with origin/main (fetch first?)",
        }
    if remote_ahead == 0:
        return {
            "check": "push_current",
            "status": "pass",
            "detail": "local is up to date with origin/main",
        }
    return {
        "check": "push_current",
        "status": "fail",
        "detail": f"remote is {remote_ahead} commit(s) ahead — push will be rejected",
    }


def check_ssh_key(key_path: str = "/tmp/ssh_deploy_key") -> dict:
    p = Path(key_path)
    if not p.exists():
        return {
            "check": "ssh_key",
            "status": "fail",
            "detail": f"{key_path} does not exist",
        }
    mode = oct(p.stat().st_mode & 0o777)
    if mode != "0o600":
        return {
            "check": "ssh_key",
            "status": "warn",
            "detail": f"{key_path} permissions are {mode}, expected 0o600",
        }
    return {
        "check": "ssh_key",
        "status": "pass",
        "detail": f"{key_path} exists with correct permissions (0o600)",
    }


def check_stroke_freshness(
    repo: Path, cadence_seconds: float = 15.0, max_age_multiples: float = 5.0
) -> dict:
    """How old is the last stroke in strokes.jsonl?"""
    strokes_file = repo / "data" / "strokes.jsonl"
    if not strokes_file.exists():
        return {
            "check": "stroke_freshness",
            "status": "warn",
            "detail": "data/strokes.jsonl not found",
        }

    last_line = ""
    try:
        # Read last line efficiently
        with open(strokes_file, "rb") as f:
            f.seek(0, 2)  # end
            size = f.tell()
            block = min(size, 4096)
            f.seek(size - block)
            lines = f.read().decode("utf-8", errors="replace").splitlines()
            last_line = lines[-1] if lines else ""
    except OSError:
        return {
            "check": "stroke_freshness",
            "status": "warn",
            "detail": "could not read strokes.jsonl",
        }

    if not last_line:
        return {
            "check": "stroke_freshness",
            "status": "warn",
            "detail": "strokes.jsonl is empty",
        }

    try:
        record = json.loads(last_line)
        at_str = record.get("at", "")
        last_at = datetime.fromisoformat(at_str)
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - last_at).total_seconds()
        max_age = cadence_seconds * max_age_multiples
        if age <= max_age:
            return {
                "check": "stroke_freshness",
                "status": "pass",
                "detail": f"last stroke {age:.0f}s ago (threshold {max_age:.0f}s)",
            }
        else:
            return {
                "check": "stroke_freshness",
                "status": "fail",
                "detail": f"last stroke {age:.0f}s ago, stale (threshold {max_age:.0f}s)",
            }
    except (json.JSONDecodeError, ValueError, KeyError):
        return {
            "check": "stroke_freshness",
            "status": "warn",
            "detail": "could not parse last stroke timestamp",
        }


def run_all_checks(
    repo: Path = REPO,
    writer_id: str = "qwen",
    cadence_seconds: float = 15.0,
    ssh_key_path: str = "/tmp/ssh_deploy_key",
) -> list[dict]:
    """Run all health checks and return results."""
    return [
        check_writer_alive(writer_id),
        check_batch_alive(writer_id),
        check_push_current(repo),
        check_ssh_key(ssh_key_path),
        check_stroke_freshness(repo, cadence_seconds),
    ]


def format_report(results: list[dict]) -> str:
    """Format results as a human-readable report."""
    lines = ["=== post-restart health ===", ""]
    for r in results:
        icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}[r["status"]]
        lines.append(f"  {icon} {r['check']:20s}  {r['detail']}")
    lines.append("")

    fails = sum(1 for r in results if r["status"] == "fail")
    warns = sum(1 for r in results if r["status"] == "warn")
    if fails:
        lines.append(f"result: FAIL ({fails} failure(s), {warns} warning(s))")
    elif warns:
        lines.append(f"result: WARN ({warns} warning(s))")
    else:
        lines.append("result: PASS — all systems nominal")
    return "\n".join(lines)


def exit_code(results: list[dict]) -> int:
    """0 = all pass, 1 = any warn, 2 = any fail."""
    if any(r["status"] == "fail" for r in results):
        return 2
    if any(r["status"] == "warn" for r in results):
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default="qwen", help="writer id (default: qwen)")
    ap.add_argument("--cadence", type=float, default=15.0,
                    help="expected seconds between strokes (default: 15)")
    ap.add_argument("--ssh-key", default="/tmp/ssh_deploy_key",
                    help="path to deploy key (default: /tmp/ssh_deploy_key)")
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="emit JSON instead of text")
    args = ap.parse_args()

    results = run_all_checks(
        repo=REPO,
        writer_id=args.writer,
        cadence_seconds=args.cadence,
        ssh_key_path=args.ssh_key,
    )

    if args.json_output:
        print(json.dumps({"checks": results, "exit_code": exit_code(results)}, indent=2))
    else:
        print(format_report(results))

    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
