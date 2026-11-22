#!/usr/bin/env python3
"""caretaker_autorecover.py — single-command crash recovery.

combines the diagnostic (process_death_clock) and the recovery
(push_guard + run_both.sh restart) into one callable entry point.
visit 799 noted "the next logical step is a single caretaker script
that runs both in sequence — detect death, record it, recover push,
resume cadence."  this is that script.

flow:
  1. probe pid files to see which processes are alive.
  2. for each dead process, record a death event.
  3. if anything was dead, call run_both.sh to restart.
  4. run guarded_push() to flush any unpushed commits.
  5. return a structured recovery report.

CLI
---
    python3 tools/caretaker_autorecover.py              # full recovery
    python3 tools/caretaker_autorecover.py --dry-run    # show what would happen
    python3 tools/caretaker_autorecover.py --probe-only # check liveness, no action
    python3 tools/caretaker_autorecover.py --json       # output report as JSON

exit codes:
    0 — everything was already alive, or recovery succeeded
    1 — recovery attempted but something failed
    2 — probe-only: at least one process is dead
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
WRITER_ID = os.environ.get("IAMAII_WRITER", "qwen")
WRITER_PID = Path(f"/tmp/iamai-writer-{WRITER_ID}.pid")
BATCH_PID = Path(f"/tmp/iamai-batch-{WRITER_ID}.pid")
RUN_BOTH = REPO / "tools" / "run_both.sh"
RESTART_TIMEOUT = 30  # seconds to wait for run_both.sh
PUSH_TIMEOUT = 120    # seconds for guarded_push (repo is large)


# ---------------------------------------------------------------------------
# data class
# ---------------------------------------------------------------------------


@dataclass
class RecoveryReport:
    """Structured result of an autorecover run."""

    writer_alive: bool = False
    batch_alive: bool = False
    writer_pid: Optional[int] = None
    batch_pid: Optional[int] = None
    deaths_recorded: List[str] = field(default_factory=list)
    restart_attempted: bool = False
    restart_ok: bool = False
    restart_output: str = ""
    push_attempted: bool = False
    push_result: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)

    @property
    def recovered(self) -> bool:
        """True if both processes are alive and push is clean (or skipped)."""
        if not (self.writer_alive and self.batch_alive):
            return False
        if self.push_attempted and self.push_result and not self.push_result.get("ok"):
            return False
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


def _read_pid(path: Path) -> Optional[int]:
    """Read a pid from a file; return None on any failure."""
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_alive(pid: Optional[int]) -> bool:
    """Check if a process with the given pid is alive."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def probe(writer_pid_path: Path = WRITER_PID,
          batch_pid_path: Path = BATCH_PID) -> Dict[str, Any]:
    """Check liveness of writer and batch. Returns a dict with pids and flags."""
    w_pid = _read_pid(writer_pid_path)
    b_pid = _read_pid(batch_pid_path)
    w_alive = _is_alive(w_pid)
    b_alive = _is_alive(b_pid)
    return {
        "writer_alive": w_alive,
        "batch_alive": b_alive,
        "writer_pid": w_pid,
        "batch_alive_val": b_alive,
        "batch_pid": b_pid,
    }


# ---------------------------------------------------------------------------
# death recording
# ---------------------------------------------------------------------------


def _record_deaths(writer_alive: bool, batch_alive: bool,
                   writer_pid: Optional[int], batch_pid: Optional[int],
                   note: str = "") -> List[str]:
    """Record death events for any dead process. Returns list of dead names."""
    # import lazily to avoid hard dependency on process_death_clock
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from process_death_clock import record_death
    except ImportError:
        return []

    dead = []
    if not writer_alive:
        record_death("writer", pid=writer_pid, note=note or "autorecover: writer dead on probe")
        dead.append("writer")
    if not batch_alive:
        record_death("batch", pid=batch_pid, note=note or "autorecover: batch dead on probe")
        dead.append("batch")
    return dead


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def _restart(repo: Path = REPO, timeout: int = RESTART_TIMEOUT) -> tuple[bool, str]:
    """Run run_both.sh to restart dead processes. Returns (ok, output)."""
    run_both = repo / "tools" / "run_both.sh"
    if not run_both.exists():
        return False, f"run_both.sh not found at {run_both}"
    try:
        result = subprocess.run(
            ["bash", str(run_both)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        ok = result.returncode == 0
        return ok, output
    except subprocess.TimeoutExpired:
        return False, f"run_both.sh timed out after {timeout}s"
    except Exception as exc:
        return False, f"run_both.sh failed: {exc}"


# ---------------------------------------------------------------------------
# push recovery
# ---------------------------------------------------------------------------


def _recover_push(cwd: str = ".", dry_run: bool = False) -> Dict[str, Any]:
    """Run push_guard.guarded_push and return its result dict."""
    try:
        sys.path.insert(0, str(REPO / "tools"))
        from push_guard import guarded_push
        return guarded_push(cwd=cwd or str(REPO), dry_run=dry_run)
    except ImportError:
        return {"ok": False, "error": "push_guard module not available", "steps": []}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "steps": []}


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def autorecover(
    dry_run: bool = False,
    probe_only: bool = False,
    repo: Path = REPO,
    writer_pid_path: Path = WRITER_PID,
    batch_pid_path: Path = BATCH_PID,
) -> RecoveryReport:
    """Full recovery sequence: probe → record deaths → restart → push.

    Args:
        dry_run: if True, skip actual restart and push.
        probe_only: if True, only probe and return; no restart or push.
        repo: path to the repository root.
        writer_pid_path: path to the writer pid file.
        batch_pid_path: path to the batch pid file.

    Returns:
        RecoveryReport with full details.
    """
    report = RecoveryReport()

    # step 1: probe
    state = probe(writer_pid_path, batch_pid_path)
    report.writer_alive = state["writer_alive"]
    report.batch_alive = state["batch_alive"]
    report.writer_pid = state["writer_pid"]
    report.batch_pid = state["batch_pid"]

    if probe_only:
        return report

    both_alive = report.writer_alive and report.batch_alive

    # step 2: record deaths for anything dead
    if not both_alive and not dry_run:
        report.deaths_recorded = _record_deaths(
            report.writer_alive, report.batch_alive,
            report.writer_pid, report.batch_pid,
        )

    # step 3: restart if needed
    if not both_alive:
        report.restart_attempted = True
        if dry_run:
            report.restart_ok = True
            report.restart_output = "[dry-run] would run run_both.sh"
        else:
            ok, output = _restart(repo)
            report.restart_ok = ok
            report.restart_output = output
            if not ok:
                report.errors.append(f"restart failed: {output[:200]}")
            else:
                # re-probe after restart
                new_state = probe(writer_pid_path, batch_pid_path)
                report.writer_alive = new_state["writer_alive"]
                report.batch_alive = new_state["batch_alive"]
                report.writer_pid = new_state["writer_pid"]
                report.batch_pid = new_state["batch_pid"]

    # step 4: push recovery
    report.push_attempted = True
    if dry_run:
        report.push_result = {"ok": True, "steps": ["[dry-run] would run guarded_push"]}
    else:
        report.push_result = _recover_push(cwd=str(repo))
        if not report.push_result.get("ok"):
            report.errors.append(
                f"push failed: {report.push_result.get('error', 'unknown')}"
            )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="single-command crash recovery for IamAI writer + batch"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen without doing it")
    parser.add_argument("--probe-only", action="store_true",
                        help="check liveness, do not restart or push")
    parser.add_argument("--json", action="store_true",
                        help="output report as JSON")
    args = parser.parse_args()

    report = autorecover(
        dry_run=args.dry_run,
        probe_only=args.probe_only,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        # human-readable output
        print(f"writer: {'alive' if report.writer_alive else 'DEAD'} (pid {report.writer_pid})")
        print(f"batch:  {'alive' if report.batch_alive else 'DEAD'} (pid {report.batch_pid})")

        if report.deaths_recorded:
            print(f"deaths recorded: {', '.join(report.deaths_recorded)}")

        if report.restart_attempted:
            status = "ok" if report.restart_ok else "FAILED"
            print(f"restart: {status}")
            if report.restart_output:
                for line in report.restart_output.strip().splitlines()[:5]:
                    print(f"  {line}")

        if report.push_attempted and report.push_result:
            status = "ok" if report.push_result.get("ok") else "FAILED"
            print(f"push: {status}")
            for step in report.push_result.get("steps", []):
                print(f"  {step}")

        if report.errors:
            print(f"errors: {len(report.errors)}")
            for err in report.errors:
                print(f"  - {err}")

        verdict = "recovered" if report.recovered else "needs attention"
        print(f"\nverdict: {verdict}")

    # exit code
    if args.probe_only:
        return 0 if (report.writer_alive and report.batch_alive) else 2
    return 0 if report.recovered else 1


if __name__ == "__main__":
    sys.exit(main())
