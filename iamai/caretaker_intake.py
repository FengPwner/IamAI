"""Caretaker intake — single-call arrival diagnosis for every visit.

Every caretaker visit asks the same four questions:

1. Are the processes alive?
2. Is the working tree clean?
3. Is the push pipeline ready?
4. How deep is the commit backlog?

Instead of reimplementing the same checks every visit, this module
runs them all in one call and returns a structured ``IntakeReport``
with a single verdict.

Verdict logic
=============

===========  =================================================
verdict      condition
===========  =================================================
``healthy``  processes up, tree clean, push ready, no backlog
``attention`` minor issue (one process down, or small backlog)
``action``   something needs fixing now (push broken, big backlog,
             both processes dead)
===========  =================================================

Usage::

    from iamai.caretaker_intake import run_intake, format_intake

    report = run_intake()
    print(format_intake(report))
    # -> "attention: writer down, 3 uncommitted files, push ready, 1 unpushed commit"

    if report["verdict"] == "action":
        # escalate immediately
        ...
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from .process_liveness import check_liveness, LivenessReport


@dataclass
class TreeStatus:
    """Working tree cleanliness snapshot."""

    clean: bool = True
    uncommitted_files: int = 0
    staged_files: int = 0
    untracked_files: int = 0
    files: List[str] = field(default_factory=list)


@dataclass
class PushStatus:
    """Push pipeline readiness snapshot."""

    ready: bool = False
    unpushed_commits: int = 0
    ssh_key_present: bool = False
    remote_reachable: bool = False
    detail: str = ""


@dataclass
class BacklogStatus:
    """Commit backlog depth snapshot."""

    depth: int = 0
    oldest_unpushed_seconds: Optional[float] = None
    risk: str = "low"


@dataclass
class IntakeReport:
    """Combined arrival diagnosis for a caretaker visit."""

    liveness: dict = field(default_factory=dict)
    tree: TreeStatus = field(default_factory=TreeStatus)
    push: PushStatus = field(default_factory=PushStatus)
    backlog: BacklogStatus = field(default_factory=BacklogStatus)
    verdict: str = "action"
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "liveness": self.liveness,
            "tree": asdict(self.tree),
            "push": asdict(self.push),
            "backlog": asdict(self.backlog),
            "verdict": self.verdict,
            "checked_at": self.checked_at,
        }


def _check_tree(repo_path: Optional[str] = None) -> TreeStatus:
    """Check working tree cleanliness via ``git status --porcelain``."""
    cwd = repo_path or str(Path(__file__).resolve().parent.parent)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return TreeStatus(clean=False)

    if result.returncode != 0:
        return TreeStatus(clean=False)

    lines = [l for l in result.stdout.splitlines() if l.strip()]
    if not lines:
        return TreeStatus(clean=True)

    untracked = sum(1 for l in lines if l.startswith("??"))
    modified = sum(
        1 for l in lines if not l.startswith("??")
    )

    files = [l[3:].strip() for l in lines]

    return TreeStatus(
        clean=(modified == 0 and untracked == 0),
        uncommitted_files=modified + untracked,
        staged_files=0,
        untracked_files=untracked,
        files=files,
    )


def _check_push(repo_path: Optional[str] = None) -> PushStatus:
    """Check push readiness: SSH key, remote, unpushed commits."""
    cwd = repo_path or str(Path(__file__).resolve().parent.parent)

    # Check SSH deploy key
    ssh_key_paths = [
        os.environ.get("GIT_SSH_KEY", ""),
        "/tmp/ssh_deploy_key",
        os.path.expanduser("~/.ssh/id_ed25519"),
        os.path.expanduser("~/.ssh/id_rsa"),
    ]
    ssh_key_present = any(
        p and Path(p).exists() for p in ssh_key_paths
    )

    # Count unpushed commits
    unpushed = 0
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
        if result.returncode == 0 and result.stdout.strip():
            unpushed = len(result.stdout.strip().splitlines())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Quick remote reachability probe (ls-remote with 3s timeout)
    remote_ok = False
    try:
        env = os.environ.copy()
        ssh_cmd = os.environ.get("GIT_SSH_COMMAND", "")
        if ssh_cmd:
            env["GIT_SSH_COMMAND"] = ssh_cmd
        elif ssh_key_present:
            for p in ssh_key_paths:
                if p and Path(p).exists():
                    env["GIT_SSH_COMMAND"] = (
                        f"ssh -i {p} -o StrictHostKeyChecking=accept-new "
                        f"-o ConnectTimeout=3"
                    )
                    break
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
            env=env,
        )
        remote_ok = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    ready = ssh_key_present and remote_ok and unpushed == 0

    return PushStatus(
        ready=ready,
        unpushed_commits=unpushed,
        ssh_key_present=ssh_key_present,
        remote_reachable=remote_ok,
        detail="",
    )


def _check_backlog(repo_path: Optional[str] = None) -> BacklogStatus:
    """Assess commit backlog depth and risk tier."""
    cwd = repo_path or str(Path(__file__).resolve().parent.parent)

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return BacklogStatus(depth=0, risk="low")

    if result.returncode != 0 or not result.stdout.strip():
        return BacklogStatus(depth=0, risk="low")

    lines = result.stdout.strip().splitlines()
    depth = len(lines)

    # Estimate oldest unpushed commit age
    oldest_seconds: Optional[float] = None
    try:
        ts_result = subprocess.run(
            [
                "git", "log", "-1", "--format=%at",
                "origin/main..HEAD", "--reverse",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if ts_result.returncode == 0 and ts_result.stdout.strip():
            oldest_ts = int(ts_result.stdout.strip().splitlines()[0])
            oldest_seconds = time.time() - oldest_ts
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Risk tiers
    if depth == 0:
        risk = "low"
    elif depth <= 3:
        risk = "moderate"
    elif depth <= 10:
        risk = "high"
    else:
        risk = "critical"

    # Escalate by age if available
    if oldest_seconds is not None:
        if oldest_seconds > 86400:  # > 24h
            risk = "critical"
        elif oldest_seconds > 21600 and risk in ("low", "moderate"):  # > 6h
            risk = "high"

    return BacklogStatus(
        depth=depth,
        oldest_unpushed_seconds=oldest_seconds,
        risk=risk,
    )


def _compute_verdict(
    liveness: dict,
    tree: TreeStatus,
    push: PushStatus,
    backlog: BacklogStatus,
) -> str:
    """Determine overall intake verdict.

    - ``healthy``: everything nominal
    - ``attention``: minor issue, can wait a cycle
    - ``action``: needs immediate intervention
    """
    issues = []

    # Process health
    verdict_lv = liveness.get("verdict", "dead")
    if verdict_lv == "dead":
        issues.append("critical")
    elif verdict_lv == "degraded":
        issues.append("minor")

    # Tree cleanliness
    if not tree.clean and tree.uncommitted_files > 5:
        issues.append("critical")
    elif not tree.clean:
        issues.append("minor")

    # Push readiness
    if not push.ssh_key_present or not push.remote_reachable:
        issues.append("critical")

    # Backlog
    if backlog.risk in ("high", "critical"):
        issues.append("critical")
    elif backlog.risk == "moderate":
        issues.append("minor")

    if "critical" in issues:
        return "action"
    if "minor" in issues:
        return "attention"
    return "healthy"


def run_intake(repo_path: Optional[str] = None) -> IntakeReport:
    """Run all four checks and return a combined report.

    Parameters
    ----------
    repo_path : str, optional
        Path to the git repository root. Defaults to the parent of
        the ``iamai`` package directory.

    Returns
    -------
    IntakeReport
        Structured report with per-check results and overall verdict.
    """
    liveness_report = check_liveness()
    tree = _check_tree(repo_path)
    push = _check_push(repo_path)
    backlog = _check_backlog(repo_path)

    verdict = _compute_verdict(
        liveness_report.to_dict(), tree, push, backlog
    )

    return IntakeReport(
        liveness=liveness_report.to_dict(),
        tree=tree,
        push=push,
        backlog=backlog,
        verdict=verdict,
        checked_at=time.time(),
    )


def format_intake(report: IntakeReport) -> str:
    """Format an ``IntakeReport`` as a concise one-line string.

    Suitable for caretaker visit logs and commit messages.
    """
    parts = [report.verdict]

    # Liveness summary
    lv = report.liveness
    w_status = "up" if lv.get("writer_alive") else "down"
    b_status = "up" if lv.get("batch_alive") else "down"
    parts.append(f"writer {w_status}, batch {b_status}")

    # Tree summary
    if report.tree.clean:
        parts.append("tree clean")
    else:
        parts.append(f"{report.tree.uncommitted_files} uncommitted file(s)")

    # Push summary
    if report.push.ready:
        parts.append("push ready")
    else:
        missing = []
        if not report.push.ssh_key_present:
            missing.append("no key")
        if not report.push.remote_reachable:
            missing.append("remote unreachable")
        if report.push.unpushed_commits > 0:
            missing.append(f"{report.push.unpushed_commits} unpushed")
        parts.append(f"push issue ({', '.join(missing)})")

    # Backlog summary
    if report.backlog.depth == 0:
        parts.append("no backlog")
    else:
        parts.append(
            f"backlog {report.backlog.depth} commit(s), "
            f"risk={report.backlog.risk}"
        )

    return ": ".join(parts[:1]) + " \u2014 " + ", ".join(parts[1:])
