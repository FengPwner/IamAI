#!/usr/bin/env python3
"""process_health.py — quick health check for writer + batch processes.

Produces a structured verdict per process: healthy, degraded, or dead.
Checks PID files, process liveness (kill -0), and recent log activity.

Exit codes:
    0 — all healthy
    1 — at least one process dead or degraded
    2 — repo not found or other error

Usage:
    python3 tools/process_health.py
    python3 tools/process_health.py --writer qwen --json
    python3 tools/process_health.py --log-age-warn 1800
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ProcessStatus:
    name: str
    pid: Optional[int]
    alive: bool
    pidfile_exists: bool
    log_last_activity: Optional[str]   # ISO-8601 or None
    log_age_seconds: Optional[float]
    verdict: str                       # "healthy" | "degraded" | "dead"


@dataclass
class HealthReport:
    writer: ProcessStatus
    batch: ProcessStatus
    unpushed_commits: int
    pending_files: int
    overall: str                       # "healthy" | "degraded" | "dead"
    checked_at: str                    # ISO-8601


def read_pidfile(path: Path) -> Optional[int]:
    """Read an integer PID from a file, return None on any failure."""
    try:
        text = path.read_text().strip()
        pid = int(text)
        return pid if pid > 0 else None
    except (OSError, ValueError):
        return None


def pid_alive(pid: Optional[int]) -> bool:
    """Check whether a PID is alive using signal 0."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def last_log_activity(log_path: Path) -> Optional[tuple]:
    """Return (last_line, mtime_iso, age_seconds) from a log file, or None."""
    if not log_path.exists():
        return None
    try:
        stat = log_path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - mtime).total_seconds()
        # read last non-empty line
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return ("", mtime.isoformat(), age)
            # read last 1024 bytes for efficiency
            read_size = min(1024, size)
            f.seek(-read_size, 2)
            chunk = f.read().decode("utf-8", errors="replace")
            lines = [l for l in chunk.splitlines() if l.strip()]
            last_line = lines[-1] if lines else ""
        return (last_line, mtime.isoformat(), age)
    except OSError:
        return None


def check_process(
    name: str,
    pidfile: Path,
    log_path: Path,
    log_age_warn: float,
) -> ProcessStatus:
    """Check a single process (writer or batch)."""
    pid = read_pidfile(pidfile)
    alive = pid_alive(pid)
    activity = last_log_activity(log_path)

    log_last = None
    log_age = None
    if activity is not None:
        _, log_last, log_age = activity

    # Determine verdict
    if not alive:
        verdict = "dead"
    elif log_age is not None and log_age > log_age_warn:
        verdict = "degraded"
    else:
        verdict = "healthy"

    return ProcessStatus(
        name=name,
        pid=pid,
        alive=alive,
        pidfile_exists=pidfile.exists(),
        log_last_activity=log_last,
        log_age_seconds=log_age,
        verdict=verdict,
    )


def count_unpushed(repo: Path) -> int:
    """Count commits ahead of origin/main."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", "^origin/main"],
            capture_output=True, text=True, cwd=str(repo), timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return -1  # unknown


def count_pending(repo: Path) -> int:
    """Count uncommitted files."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(repo), timeout=10,
        )
        if result.returncode == 0:
            return len([l for l in result.stdout.splitlines() if l.strip()])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return -1


def full_report(
    repo: Path,
    writer_id: str = "qwen",
    log_age_warn: float = 1800,
) -> HealthReport:
    """Produce a full health report for both processes."""
    writer_pid = Path(f"/tmp/iamai-writer-{writer_id}.pid")
    batch_pid = Path(f"/tmp/iamai-batch-{writer_id}.pid")
    log_path = Path(f"/tmp/iamai-{writer_id}.log")

    writer_status = check_process("writer", writer_pid, log_path, log_age_warn)
    batch_status = check_process("batch", batch_pid, log_path, log_age_warn)

    unpushed = count_unpushed(repo)
    pending = count_pending(repo)

    # Overall verdict: worst of the two
    verdicts = [writer_status.verdict, batch_status.verdict]
    if "dead" in verdicts:
        overall = "dead"
    elif "degraded" in verdicts:
        overall = "degraded"
    else:
        overall = "healthy"

    return HealthReport(
        writer=writer_status,
        batch=batch_status,
        unpushed_commits=unpushed,
        pending_files=pending,
        overall=overall,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


def format_report(report: HealthReport) -> str:
    """Format a health report as human-readable text."""
    lines = []
    for ps in [report.writer, report.batch]:
        pid_str = f"pid {ps.pid}" if ps.pid else "no pid"
        alive_str = "alive" if ps.alive else "DEAD"
        age_str = f" (log age {ps.log_age_seconds:.0f}s)" if ps.log_age_seconds is not None else ""
        lines.append(f"  {ps.name}: {ps.verdict} [{pid_str}, {alive_str}]{age_str}")
    lines.append(f"  unpushed: {report.unpushed_commits}  pending: {report.pending_files}")
    lines.insert(0, f"health: {report.overall}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=os.environ.get("IAMAII_WRITER", "qwen"))
    ap.add_argument("--json", action="store_true", help="output JSON")
    ap.add_argument("--log-age-warn", type=float, default=1800,
                    help="seconds of log silence before 'degraded' (default 1800)")
    ap.add_argument("--repo", type=str, default=None, help="repo path")
    args = ap.parse_args()

    repo = Path(args.repo) if args.repo else Path(__file__).resolve().parent.parent

    report = full_report(repo, writer_id=args.writer, log_age_warn=args.log_age_warn)

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))

    return 1 if report.overall != "healthy" else 0


if __name__ == "__main__":
    raise SystemExit(main())
