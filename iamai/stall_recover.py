"""Stall recovery — detect and auto-remediate writer pipeline stalls.

A "stall" is when the writer process is alive but not producing strokes,
or when commits silently fail and backlog accumulates. The existing
``commit_blockage`` module diagnoses *why* commits fail; this module
orchestrates the full recovery sequence:

    1. diagnose  — run blockage checks, inspect writer state
    2. remediate — remove stale locks, flush backlog, restart if needed
    3. verify    — confirm the writer is producing again

This is the module a caretaker (human or automated) calls when the
healthcheck says STALL. It wraps the individual detectors into a
single recover() function that returns a structured report.

Design note
-----------
Remediation is intentionally conservative: we remove stale lock files
and restart dead processes, but we never force-push, discard uncommitted
changes, or modify writer state. If auto-remediation fails, the report
tells the caretaker exactly what manual steps remain.

Usage
-----
    from iamai.stall_recover import recover, StallReport
    report = recover(repo_path)
    if report.recovered:
        print("pipeline healthy")
    else:
        print(f"manual steps needed: {report.remaining}")
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .commit_blockage import check_blockage


@dataclass
class StallReport:
    """Structured result of a stall recovery attempt."""

    recovered: bool = False
    actions_taken: List[str] = field(default_factory=list)
    remaining: List[str] = field(default_factory=list)
    blockage_findings: List[dict] = field(default_factory=list)
    writer_alive: bool = False
    batch_alive: bool = False
    uncommitted_files: int = 0
    duration_seconds: float = 0.0

    def summary(self) -> str:
        if self.recovered:
            acts = "; ".join(self.actions_taken) if self.actions_taken else "no action needed"
            return f"recovered ({acts})"
        rem = "; ".join(self.remaining) if self.remaining else "unknown issue"
        return f"NOT recovered — remaining: {rem}"


def _remove_stale_lock(repo: Path) -> Optional[str]:
    """Remove .git/index.lock if no process holds it. Returns action description or None."""
    lock = repo / ".git" / "index.lock"
    if not lock.exists():
        return None

    # Check if any process holds it via /proc
    lock_resolved = str(lock.resolve())
    holder_found = False
    proc = Path("/proc")
    if proc.exists():
        for pid_dir in proc.iterdir():
            if not pid_dir.name.isdigit():
                continue
            fd_dir = pid_dir / "fd"
            if not fd_dir.exists():
                continue
            try:
                for fd in fd_dir.iterdir():
                    try:
                        if str(fd.resolve()) == lock_resolved:
                            holder_found = True
                            break
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
            except (PermissionError, FileNotFoundError, OSError):
                continue
            if holder_found:
                break

    if holder_found:
        return None  # lock is live, don't touch it

    try:
        lock.unlink()
        return "removed stale .git/index.lock"
    except OSError as exc:
        return f"failed to remove index.lock: {exc}"


def _flush_backlog(repo: Path) -> Optional[str]:
    """Stage all changes and commit if there are uncommitted files."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    if not lines:
        return None

    count = len(lines)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
    commit_env = {**os.environ}
    commit_env.setdefault("GIT_AUTHOR_NAME", "stall-recover")
    commit_env.setdefault("GIT_AUTHOR_EMAIL", "caretaker@iamai")
    commit_env.setdefault("GIT_COMMITTER_NAME", "stall-recover")
    commit_env.setdefault("GIT_COMMITTER_EMAIL", "caretaker@iamai")
    commit_result = subprocess.run(
        ["git", "commit", "-m", f"stall-recover: flush {count} uncommitted files"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=commit_env,
    )
    if commit_result.returncode == 0:
        return f"committed {count} uncommitted files"
    return f"commit failed: {commit_result.stderr.strip()}"


def _check_writer_alive(writer_id: str = "qwen") -> bool:
    """Check if the writer process is running via pidfile."""
    pidfile = Path(f"/tmp/iamai-writer-{writer_id}.pid")
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        import os
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def _check_batch_alive(writer_id: str = "qwen") -> bool:
    """Check if the batch committer is running via pidfile."""
    pidfile = Path(f"/tmp/iamai-batch-{writer_id}.pid")
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        import os
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def recover(
    repo: Path,
    writer_id: str = "qwen",
    auto_restart: bool = False,
) -> StallReport:
    """Run the full stall recovery sequence.

    Parameters
    ----------
    repo : Path
        Root of the git repository.
    writer_id : str
        Writer identifier (matches IAMAII_WRITER env var).
    auto_restart : bool
        If True, attempt to restart dead processes via run_both.sh.
        Default False — only diagnose and remediate git-level issues.

    Returns
    -------
    StallReport with actions taken and remaining manual steps.
    """
    start = time.monotonic()
    report = StallReport()
    repo = Path(repo)

    # Step 1: diagnose blockage
    findings = check_blockage(repo)
    report.blockage_findings = findings

    # Step 2: remediate stale locks
    for finding in findings:
        if finding["severity"] == "blocking" and finding["cause"] == "stale_index_lock":
            action = _remove_stale_lock(repo)
            if action:
                report.actions_taken.append(action)

    # Step 3: flush uncommitted backlog
    flush_action = _flush_backlog(repo)
    if flush_action:
        report.actions_taken.append(flush_action)

    # Step 4: check process liveness
    report.writer_alive = _check_writer_alive(writer_id)
    report.batch_alive = _check_batch_alive(writer_id)

    if not report.writer_alive:
        if auto_restart:
            restart_result = subprocess.run(
                ["bash", "tools/run_both.sh"],
                cwd=str(repo),
                capture_output=True,
                text=True,
            )
            if restart_result.returncode == 0:
                report.actions_taken.append("restarted writer + batch via run_both.sh")
                report.writer_alive = _check_writer_alive(writer_id)
                report.batch_alive = _check_batch_alive(writer_id)
            else:
                report.remaining.append(
                    f"restart failed: {restart_result.stderr.strip() or restart_result.stdout.strip()}"
                )
        else:
            report.remaining.append("writer process dead — run tools/run_both.sh to restart")

    if not report.batch_alive and report.writer_alive:
        report.remaining.append("batch committer dead — writer running without committer")

    # Step 5: count remaining uncommitted
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    report.uncommitted_files = len([
        l for l in result.stdout.strip().split("\n") if l.strip()
    ])

    # Step 6: remaining blockage findings
    post_findings = check_blockage(repo)
    blocking = [f for f in post_findings if f["severity"] == "blocking"]
    if blocking:
        for f in blocking:
            report.remaining.append(f"still blocked: {f['cause']} — {f['fix']}")

    report.duration_seconds = round(time.monotonic() - start, 3)
    report.recovered = (
        report.writer_alive
        and report.batch_alive
        and report.uncommitted_files == 0
        and not any(f["severity"] == "blocking" for f in post_findings)
    )

    return report
