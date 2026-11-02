#!/usr/bin/env python3
"""rescue_push_orchestrator.py — full push-recovery orchestration for multi-process repos.

Bridges the gap between rebase_rescue.py (which handles git mechanics) and the
operational reality of a continuously-running writer. When push is rejected due
to remote divergence, the full sequence is:

    1. Detect divergence (push rejected).
    2. Stop writer and batch committer processes.
    3. Commit any pending changes.
    4. Pull --rebase from remote.
    5. Push.
    6. Restart writer and batch committer.
    7. Report outcome.

This is the tool that caretaker visits need: one command that handles
everything from "push rejected" to "processes running, push succeeded".

Exit codes:
    0 — push succeeded
    1 — push still rejected after rescue
    2 — unexpected error

Usage:
    python3 tools/rescue_push_orchestrator.py [--repo .] [--remote origin] [--branch main]
    python3 tools/rescue_push_orchestrator.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OrchestratorReport:
    """Structured result of a rescue-push operation."""
    steps: list[str] = field(default_factory=list)
    writer_stopped: bool = False
    batch_stopped: bool = False
    pending_committed: bool = False
    pending_file_count: int = 0
    rebased: bool = False
    pushed: bool = False
    writer_restarted: bool = False
    batch_restarted: bool = False
    success: bool = False
    error: str = ""
    duration_s: float = 0.0

    def log(self, msg: str) -> None:
        self.steps.append(msg)

    def summarize(self) -> str:
        lines = ["=== Rescue Push Orchestration ==="]
        lines.append(f"duration: {self.duration_s:.1f}s")
        lines.append(f"writer stopped: {self.writer_stopped}")
        lines.append(f"batch stopped: {self.batch_stopped}")
        lines.append(f"pending committed: {self.pending_committed} ({self.pending_file_count} files)")
        lines.append(f"rebased: {self.rebased}")
        lines.append(f"pushed: {self.pushed}")
        lines.append(f"writer restarted: {self.writer_restarted}")
        lines.append(f"batch restarted: {self.batch_restarted}")
        lines.append(f"success: {self.success}")
        if self.error:
            lines.append(f"error: {self.error}")
        lines.append("---")
        for s in self.steps:
            lines.append(f"  {s}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "writer_stopped": self.writer_stopped,
            "batch_stopped": self.batch_stopped,
            "pending_committed": self.pending_committed,
            "pending_file_count": self.pending_file_count,
            "rebased": self.rebased,
            "pushed": self.pushed,
            "writer_restarted": self.writer_restarted,
            "batch_restarted": self.batch_restarted,
            "success": self.success,
            "error": self.error,
            "duration_s": self.duration_s,
        }


def git(args, cwd, env=None):
    """Run git with captured output and safe defaults."""
    full_env = os.environ.copy()
    full_env.setdefault("GIT_AUTHOR_NAME", "IamAI")
    full_env.setdefault("GIT_AUTHOR_EMAIL", "iamai@iamai.local")
    full_env.setdefault("GIT_COMMITTER_NAME", "IamAI")
    full_env.setdefault("GIT_COMMITTER_EMAIL", "iamai@iamai.local")
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), capture_output=True, text=True, env=full_env
    )

def _OLD_git(args, cwd, env=None):
    """Run git with captured output."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), capture_output=True, text=True, env=full_env
    )


def find_processes(name_fragment: str) -> list[int]:
    """Find PIDs of processes matching a name fragment."""
    try:
        r = subprocess.run(
            ["pgrep", "-f", name_fragment],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip():
            return [int(p) for p in r.stdout.strip().split("\n") if p.strip()]
    except (subprocess.SubprocessError, ValueError):
        pass
    return []


def stop_process(pid: int, timeout_s: float = 5.0) -> bool:
    """Send SIGTERM then SIGKILL if needed. Returns True if process is stopped.

    Uses os.waitpid for zombie reaping when the process is a direct child.
    """
    def _is_alive(p):
        try:
            r, _ = os.waitpid(p, os.WNOHANG)
            if r > 0:
                return False
        except ChildProcessError:
            pass
        try:
            os.kill(p, 0)
            return True
        except ProcessLookupError:
            return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _is_alive(pid):
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    time.sleep(0.5)
    return not _is_alive(pid)

def has_uncommitted_changes(repo: Path) -> bool:
    """Check if there are uncommitted changes in the repo."""
    r = git(["status", "--porcelain"], repo)
    return bool(r.stdout.strip())


def count_uncommitted_files(repo: Path) -> int:
    """Count files with uncommitted changes."""
    r = git(["status", "--porcelain"], repo)
    return len([l for l in r.stdout.strip().split("\n") if l.strip()])


def commit_pending(repo: Path, message: str = "rescue-push: commit pending before rebase") -> bool:
    """Stage and commit all pending changes."""
    git(["add", "-A"], repo)
    r = git(["commit", "-m", message], repo)
    return r.returncode == 0


def pull_rebase(repo: Path, remote: str, branch: str) -> bool:
    """Pull --rebase from remote."""
    ssh_key = "/tmp/ssh_deploy_key"
    env = {}
    if os.path.exists(ssh_key):
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"
    r = git(["pull", "--rebase", remote, branch], repo, env=env or None)
    return r.returncode == 0


def push(repo: Path, remote: str, branch: str) -> bool:
    """Push to remote."""
    ssh_key = "/tmp/ssh_deploy_key"
    env = {}
    if os.path.exists(ssh_key):
        env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"
    r = git(["push", remote, branch], repo, env=env or None)
    return r.returncode == 0


def start_writer(repo: Path) -> int | None:
    """Start the writer loop in background. Returns PID or None."""
    script = repo / "tools" / "writer_loop.py"
    if not script.exists():
        return None
    proc = subprocess.Popen(
        [sys.executable, str(script), "--writer", "qwen", "--every", "15"],
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def start_batch(repo: Path) -> int | None:
    """Start the batch committer in background. Returns PID or None."""
    script = repo / "tools" / "commit_batch.py"
    if not script.exists():
        return None
    proc = subprocess.Popen(
        [sys.executable, str(script), "--watch", "--writer", "qwen", "--interval", "600"],
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def orchestrate(
    repo: Path,
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
    skip_restart: bool = False,
) -> OrchestratorReport:
    """Run the full rescue-push orchestration."""
    t0 = time.monotonic()
    report = OrchestratorReport()

    try:
        # Step 1: Stop writer processes
        report.log("stopping writer processes")
        writer_pids = find_processes("writer_loop.py")
        for pid in writer_pids:
            if dry_run:
                report.log(f"  [dry-run] would stop writer pid {pid}")
            else:
                if stop_process(pid):
                    report.writer_stopped = True
                    report.log(f"  stopped writer pid {pid}")
                else:
                    report.log(f"  WARNING: could not stop writer pid {pid}")

        batch_pids = find_processes("commit_batch.py")
        for pid in batch_pids:
            if dry_run:
                report.log(f"  [dry-run] would stop batch pid {pid}")
            else:
                if stop_process(pid):
                    report.batch_stopped = True
                    report.log(f"  stopped batch pid {pid}")
                else:
                    report.log(f"  WARNING: could not stop batch pid {pid}")

        # Small delay to let processes release any locks
        if not dry_run and (writer_pids or batch_pids):
            time.sleep(1.0)

        # Step 2: Commit pending changes
        if not dry_run and has_uncommitted_changes(repo):
            report.log("committing pending changes")
            report.pending_file_count = count_uncommitted_files(repo)
            if commit_pending(repo):
                report.pending_committed = True
                report.log(f"  committed {report.pending_file_count} pending files")
            else:
                report.log("  no pending changes to commit (or commit failed)")
        elif dry_run:
            report.log("[dry-run] would commit pending changes")
        else:
            report.log("no pending changes")

        # Step 3: Pull --rebase
        report.log(f"pulling --rebase from {remote}/{branch}")
        if dry_run:
            report.log("  [dry-run] would pull --rebase")
            report.rebased = True
        else:
            if pull_rebase(repo, remote, branch):
                report.rebased = True
                report.log("  rebase succeeded")
            else:
                report.error = "rebase failed"
                report.log("  ERROR: rebase failed")
                # Try to restart processes even on failure
                if not skip_restart:
                    _restart_processes(repo, report, dry_run)
                report.duration_s = time.monotonic() - t0
                return report

        # Step 4: Push
        report.log(f"pushing to {remote}/{branch}")
        if dry_run:
            report.log("  [dry-run] would push")
            report.pushed = True
        else:
            if push(repo, remote, branch):
                report.pushed = True
                report.log("  push succeeded")
            else:
                report.error = "push still rejected after rescue"
                report.log("  ERROR: push still rejected")

        # Step 5: Restart processes
        if not skip_restart:
            _restart_processes(repo, report, dry_run)

        report.success = report.pushed or dry_run

    except Exception as e:
        report.error = str(e)
        report.log(f"EXCEPTION: {e}")
        # Try to restart processes on unexpected errors
        if not skip_restart and not dry_run:
            _restart_processes(repo, report, dry_run)

    report.duration_s = time.monotonic() - t0
    return report


def _restart_processes(repo: Path, report: OrchestratorReport, dry_run: bool) -> None:
    """Restart writer and batch processes."""
    report.log("restarting processes")
    if dry_run:
        report.log("  [dry-run] would restart writer and batch")
        report.writer_restarted = True
        report.batch_restarted = True
        return

    writer_pid = start_writer(repo)
    if writer_pid:
        report.writer_restarted = True
        report.log(f"  writer restarted: pid {writer_pid}")
    else:
        report.log("  WARNING: could not restart writer")

    batch_pid = start_batch(repo)
    if batch_pid:
        report.batch_restarted = True
        report.log(f"  batch restarted: pid {batch_pid}")
    else:
        report.log("  WARNING: could not restart batch")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Full push-recovery orchestration for multi-process repos"
    )
    parser.add_argument("--repo", default=".", help="Path to git repo")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-restart", action="store_true",
                        help="Don't restart processes after rescue")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of text")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").is_dir():
        for parent in repo.parents:
            if (parent / ".git").is_dir():
                repo = parent
                break

    report = orchestrate(
        repo, args.remote, args.branch,
        dry_run=args.dry_run,
        skip_restart=args.skip_restart,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summarize())

    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
