"""Caretaker: the part of recovery that a machine can do alone.

Reclamation events follow a fixed shape: processes dead, backlog uncommitted,
remote possibly ahead. The recovery checklist (iamai.recovery) names the steps;
this module does them. One function, ``intervene``, runs the full sequence:

    1. Kill any zombie processes (stale pidfiles)
    2. Stash uncommitted work
    3. Rebase local commits on top of upstream
    4. Pop the stash
    5. Restart writer and batch via run_both.sh
    6. Verify the new processes are alive

If any step fails, the function stops and reports where it stopped. The
caretaker does not guess; a partial recovery reported honestly is worth more
than a full recovery that skips a failing step and claims success.

This module is meant to be called by the pre-execution harness or by a
human who types ``python3 -m iamai.caretaker``. It is not meant to be
clever. It is meant to be correct.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
RUN_BOTH = TOOLS / "run_both.sh"


@dataclass
class InterventionResult:
    """Outcome of a caretaker intervention, step by step."""

    killed_stale: bool = False
    stashed: bool = False
    rebased: bool = False
    stash_popped: bool = False
    restarted: bool = False
    verified: bool = False
    writer_pid: Optional[int] = None
    batch_pid: Optional[int] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return all([
            self.killed_stale,
            self.stashed,
            self.rebased,
            self.stash_popped,
            self.restarted,
            self.verified,
        ])

    @property
    def failed_step(self) -> Optional[str]:
        steps = [
            ("killed_stale", self.killed_stale),
            ("stashed", self.stashed),
            ("rebased", self.rebased),
            ("stash_popped", self.stash_popped),
            ("restarted", self.restarted),
            ("verified", self.verified),
        ]
        for name, done in steps:
            if not done:
                return name
        return None

    def summary(self) -> str:
        if self.success:
            return (
                f"recovered: writer={self.writer_pid}, "
                f"batch={self.batch_pid}"
            )
        lines = [f"intervention stopped at: {self.failed_step}"]
        if self.error:
            lines.append(f"  error: {self.error}")
        done = []
        if self.killed_stale:
            done.append("killed stale processes")
        if self.stashed:
            done.append("stashed uncommitted work")
        if self.rebased:
            done.append("rebased on upstream")
        if self.stash_popped:
            done.append("restored stash")
        if self.restarted:
            done.append("restarted processes")
        if done:
            lines.append(f"  completed: {', '.join(done)}")
        return "\n".join(lines)


def _run(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 60) -> tuple[int, str]:
    """Run a command and return (exit_code, combined_output)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or REPO),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return -1, f"command not found: {cmd[0]}"


def _kill_stale_pids(pid_dir: Path = Path("/tmp"), writer_id: str = "qwen") -> bool:
    """Kill processes referenced by stale pidfiles, if any exist."""
    for kind in ("writer", "batch"):
        pidfile = pid_dir / f"iamai-{kind}-{writer_id}.pid"
        if not pidfile.exists():
            continue
        try:
            pid = int(pidfile.read_text().strip())
            # Check if alive
            os.kill(pid, 0)
            # Alive — kill it
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, PermissionError):
            pass  # already dead or unreadable
        finally:
            pidfile.unlink(missing_ok=True)
    return True


def _has_unstaged(repo: Path) -> bool:
    code, out = _run(["git", "status", "--porcelain"], cwd=repo)
    return code == 0 and bool(out.strip())


def _stash(repo: Path) -> tuple[bool, str]:
    code, out = _run(["git", "stash", "push", "-u", "-m", "caretaker-auto-stash"], cwd=repo)
    if code == 0:
        # "No local changes to save" is exit 0 but nothing was stashed
        return True, out
    return False, out


def _rebase(repo: Path, remote: str = "origin", branch: str = "main") -> tuple[bool, str]:
    code, out = _run(["git", "rebase", f"{remote}/{branch}"], cwd=repo)
    if code != 0:
        # Abort on failure so the repo is not left mid-rebase
        _run(["git", "rebase", "--abort"], cwd=repo)
        return False, out
    return True, out


def _stash_pop(repo: Path) -> tuple[bool, str]:
    """Pop the most recent stash, if any. No stash = success (nothing to pop)."""
    code, out = _run(["git", "stash", "list"], cwd=repo)
    if code != 0 or not out.strip():
        return True, "no stash to pop"
    # Check if top stash is ours
    first_line = out.strip().splitlines()[0]
    if "caretaker-auto-stash" not in first_line:
        return True, "top stash is not ours, leaving it alone"
    code, out = _run(["git", "stash", "pop"], cwd=repo)
    return code == 0, out


def _restart(repo: Path, writer_id: str = "qwen") -> tuple[bool, str]:
    """Restart writer and batch via run_both.sh."""
    if not RUN_BOTH.exists():
        return False, f"run_both.sh not found at {RUN_BOTH}"
    env = os.environ.copy()
    env["IAMAII_WRITER"] = writer_id
    try:
        proc = subprocess.run(
            ["bash", str(RUN_BOTH)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, output
    except Exception as e:
        return False, str(e)


def _verify_pids(pid_dir: Path = Path("/tmp"), writer_id: str = "qwen") -> tuple[bool, int | None, int | None]:
    """Check that both pidfiles exist and reference live processes."""
    w_pid = b_pid = None
    for kind in ("writer", "batch"):
        pidfile = pid_dir / f"iamai-{kind}-{writer_id}.pid"
        if not pidfile.exists():
            return False, w_pid, b_pid
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)  # check alive
            if kind == "writer":
                w_pid = pid
            else:
                b_pid = pid
        except (ProcessLookupError, ValueError, PermissionError):
            return False, w_pid, b_pid
    return True, w_pid, b_pid


def intervene(
    repo: Optional[Path] = None,
    writer_id: str = "qwen",
    remote: str = "origin",
    branch: str = "main",
    pid_dir: Optional[Path] = None,
) -> InterventionResult:
    """Run the full caretaker intervention sequence.

    Args:
        repo: path to the git repository. Defaults to the IamAI repo.
        writer_id: which writer to restart.
        remote: upstream remote name.
        branch: upstream branch name.
        pid_dir: directory containing pidfiles. Defaults to /tmp.

    Returns:
        InterventionResult with step-by-step status.
    """
    repo = repo or REPO
    pid_dir = pid_dir or Path("/tmp")
    result = InterventionResult()

    # Step 1: Kill stale processes
    result.killed_stale = _kill_stale_pids(pid_dir, writer_id)

    # Step 2: Stash uncommitted work
    if _has_unstaged(repo):
        ok, msg = _stash(repo)
        result.stashed = ok
        if not ok:
            result.error = f"stash failed: {msg}"
            return result
    else:
        result.stashed = True  # nothing to stash is fine

    # Step 3: Rebase on upstream
    # Fetch first
    fetch_code, fetch_out = _run(["git", "fetch", remote, branch], cwd=repo)
    if fetch_code != 0:
        result.error = f"fetch failed: {fetch_out}"
        return result

    ok, msg = _rebase(repo, remote, branch)
    result.rebased = ok
    if not ok:
        result.error = f"rebase failed: {msg}"
        return result

    # Step 4: Pop stash
    ok, msg = _stash_pop(repo)
    result.stash_popped = ok
    if not ok:
        result.error = f"stash pop failed: {msg}"
        return result

    # Step 5: Restart
    ok, msg = _restart(repo, writer_id)
    result.restarted = ok
    if not ok:
        result.error = f"restart failed: {msg}"
        return result

    # Step 6: Verify
    time.sleep(3)  # give processes a moment to write pidfiles
    ok, w_pid, b_pid = _verify_pids(pid_dir, writer_id)
    result.verified = ok
    result.writer_pid = w_pid
    result.batch_pid = b_pid
    if not ok:
        result.error = "processes not alive after restart"

    return result
