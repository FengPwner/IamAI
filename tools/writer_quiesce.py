#!/usr/bin/env python3
"""writer_quiesce.py — temporarily freeze the writer for safe git operations.

The writer process modifies files every 15 seconds, which causes race
conditions during git stash/pull/rebase/push sequences. This tool sends
SIGSTOP to freeze the writer, performs the git operation, then SIGCONT
to resume — eliminating the dirty-tree window entirely.

Usage:
    python3 tools/writer_quiesce.py                   # freeze, show status, resume
    python3 tools/writer_quiesce.py --hold 30         # freeze for 30s then auto-resume
    python3 tools/writer_quiesce.py --freeze-only     # freeze and exit (caller resumes)
    python3 tools/writer_quiesce.py --resume-only     # resume a previously frozen writer
    python3 tools/writer_quiesce.py --exec "git pull --rebase origin main"
    python3 tools/writer_quiesce.py --json            # JSON output
    python3 tools/writer_quiesce.py --writer qwen     # specify writer name

Exit codes:
    0 — success (froze and resumed cleanly, or command succeeded)
    1 — writer process not found
    2 — git command failed during quiesce
    3 — could not resume writer (manual intervention needed)
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class QuiesceReport:
    """Report of a quiesce operation."""
    writer_pid: int = 0
    writer_name: str = "qwen"
    frozen: bool = False
    resumed: bool = False
    hold_seconds: float = 0.0
    git_command: str = ""
    git_exit_code: Optional[int] = None
    git_stdout: str = ""
    git_stderr: str = ""
    dirty_files_before: list = field(default_factory=list)
    dirty_files_after: list = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        d = {
            "writer_pid": self.writer_pid,
            "writer_name": self.writer_name,
            "frozen": self.frozen,
            "resumed": self.resumed,
            "hold_seconds": round(self.hold_seconds, 2),
            "dirty_files_before": self.dirty_files_before,
            "dirty_files_after": self.dirty_files_after,
        }
        if self.git_command:
            d["git_command"] = self.git_command
            d["git_exit_code"] = self.git_exit_code
            d["git_stdout"] = self.git_stdout[:500]
            d["git_stderr"] = self.git_stderr[:500]
        if self.error:
            d["error"] = self.error
        return d

    def verdict(self) -> str:
        if self.error:
            return "failed"
        if self.frozen and self.resumed:
            return "clean"
        if self.frozen and not self.resumed:
            return "frozen"
        return "unknown"


def find_writer_pid(writer_name: str = "qwen") -> Optional[int]:
    """Find the PID of the writer process by name."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"writer_loop.*--writer\\s+{writer_name}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    # Fallback: search /proc
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode(errors="replace")
            if "writer_loop" in cmdline and f"--writer" in cmdline and writer_name in cmdline:
                return int(entry.name)
        except (PermissionError, FileNotFoundError):
            continue
    return None


def get_dirty_files(repo: Path) -> list[str]:
    """Return list of modified/untracked files via git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def freeze_writer(pid: int) -> bool:
    """Send SIGSTOP to freeze the writer process."""
    try:
        os.kill(pid, signal.SIGSTOP)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def resume_writer(pid: int) -> bool:
    """Send SIGCONT to resume the writer process."""
    try:
        os.kill(pid, signal.SIGCONT)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def is_process_frozen(pid: int) -> Optional[bool]:
    """Check if a process is in stopped state (T = stopped)."""
    try:
        status = (Path("/proc") / str(pid) / "status").read_text()
        for line in status.splitlines():
            if line.startswith("State:"):
                state_char = line.split(":")[1].strip()[0]
                return state_char == "T"
    except (FileNotFoundError, PermissionError, IndexError):
        pass
    return None


def run_git_command(cmd: str, repo: Path, timeout: int = 60) -> tuple[int, str, str]:
    """Run a git command in the repo directory."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=str(repo), timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s"


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Find the repo root from the given path or cwd."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").is_dir():
            return parent
    return p


def quiesce(
    writer_name: str = "qwen",
    hold_seconds: float = 0,
    git_command: str = "",
    freeze_only: bool = False,
    resume_only: bool = False,
    repo: Optional[Path] = None,
    timeout: int = 60,
) -> QuiesceReport:
    """Main quiesce operation.

    1. Find writer process
    2. Freeze it (SIGSTOP)
    3. Optionally run a git command
    4. Resume it (SIGCONT)

    Args:
        writer_name: Name of the writer to freeze.
        hold_seconds: Hold frozen for this many seconds before resuming.
        git_command: Shell command to run while writer is frozen.
        freeze_only: If True, freeze and exit without resuming.
        resume_only: If True, only resume (skip freeze).
        repo: Repo root path.
        timeout: Timeout for git command in seconds.

    Returns:
        QuiesceReport with results.
    """
    repo = repo or find_repo_root()
    report = QuiesceReport(writer_name=writer_name)

    # Find writer
    pid = find_writer_pid(writer_name)
    if pid is None:
        report.error = f"Writer '{writer_name}' not found"
        return report
    report.writer_pid = pid

    # Resume-only mode
    if resume_only:
        if resume_writer(pid):
            report.resumed = True
        else:
            report.error = f"Could not resume writer pid {pid}"
        return report

    # Record dirty files before
    report.dirty_files_before = get_dirty_files(repo)

    # Freeze
    if not freeze_writer(pid):
        report.error = f"Could not freeze writer pid {pid}"
        return report
    report.frozen = True

    # Brief pause to let in-flight writes settle
    time.sleep(0.2)

    try:
        # Run git command if provided
        if git_command:
            report.git_command = git_command
            exit_code, stdout, stderr = run_git_command(git_command, repo, timeout)
            report.git_exit_code = exit_code
            report.git_stdout = stdout
            report.git_stderr = stderr

        # Hold for specified duration
        if hold_seconds > 0 and not freeze_only:
            time.sleep(hold_seconds)

    finally:
        # Resume unless freeze-only
        if not freeze_only:
            if resume_writer(pid):
                report.resumed = True
            else:
                report.error = f"Froze writer but could not resume pid {pid}"

            # Record dirty files after
            report.dirty_files_after = get_dirty_files(repo)

    return report


def format_report(report: QuiesceReport) -> str:
    """Format report for human-readable output."""
    lines = [
        f"writer: {report.writer_name} (pid {report.writer_pid or 'NOT FOUND'})",
        f"verdict: {report.verdict()}",
    ]
    if report.frozen:
        lines.append(f"frozen: yes (held {report.hold_seconds:.1f}s)")
    if report.resumed:
        lines.append("resumed: yes")
    if report.git_command:
        status = "ok" if report.git_exit_code == 0 else f"FAIL ({report.git_exit_code})"
        lines.append(f"git: {report.git_command} → {status}")
        if report.git_stdout.strip():
            for line in report.git_stdout.strip().splitlines()[:5]:
                lines.append(f"  {line}")
        if report.git_stderr.strip():
            for line in report.git_stderr.strip().splitlines()[:5]:
                lines.append(f"  ! {line}")
    if report.dirty_files_before:
        lines.append(f"dirty before: {len(report.dirty_files_before)} file(s)")
    if report.dirty_files_after:
        lines.append(f"dirty after: {len(report.dirty_files_after)} file(s)")
    if report.error:
        lines.append(f"error: {report.error}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Temporarily freeze the writer for safe git operations."
    )
    parser.add_argument("--writer", default="qwen", help="Writer name (default: qwen)")
    parser.add_argument("--hold", type=float, default=0, help="Hold frozen for N seconds")
    parser.add_argument("--exec", dest="git_command", default="", help="Git command to run while frozen")
    parser.add_argument("--freeze-only", action="store_true", help="Freeze and exit without resuming")
    parser.add_argument("--resume-only", action="store_true", help="Only resume a frozen writer")
    parser.add_argument("--repo", type=Path, default=None, help="Repo root path")
    parser.add_argument("--timeout", type=int, default=60, help="Git command timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args(argv)

    report = quiesce(
        writer_name=args.writer,
        hold_seconds=args.hold,
        git_command=args.git_command,
        freeze_only=args.freeze_only,
        resume_only=args.resume_only,
        repo=args.repo,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    # Exit codes
    if report.error:
        if "not found" in report.error:
            return 1
        if "could not resume" in report.error.lower():
            return 3
        return 2
    if report.git_exit_code is not None and report.git_exit_code != 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
