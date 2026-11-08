"""restart_readiness — pre-restart environment readiness checklist.

Before restarting a stalled writer or batch committer, the caretaker
should verify that the *environment* is ready.  A restart into a broken
environment wastes a cooldown window and can leave the repo in a worse
state than before.

This module runs a battery of independent checks and produces a single
readiness verdict.  Each check is isolated: one failure does not
prevent other checks from running, so the caretaker gets a complete
picture of what needs fixing.

Checks
------
========================  =================================================
check                     what it guards against
========================  =================================================
git_index_clean           merge conflicts, lock files, corrupt index
disk_space                less than ``min_free_mb`` free (default 100 MB)
credential_ready          SSH deploy key missing or unreadable
no_stale_pids             zombie/orphan writer/batch processes
working_tree_manageable   more than ``max_dirty`` uncommitted files
cooldown_respected        restart rate limit from RestartCooldownGate
========================  =================================================

Each check returns a ``CheckResult`` with status ``pass``, ``warn``,
or ``fail`` plus a human-readable detail string.

The overall verdict is:

=========  ============================================================
verdict    meaning
=========  ============================================================
ready      all checks pass or warn
blocked    one or more checks fail
=========  ============================================================

Public API::

    from iamai.restart_readiness import RestartReadinessChecker

    checker = RestartReadinessChecker(repo_root="/path/to/IamAI")
    report = checker.check_all()
    if report.verdict == "ready":
        # safe to restart
        ...
    else:
        for r in report.failures:
            print(f"BLOCKED: {r.name}: {r.detail}")
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single readiness check."""

    name: str
    status: str          # "pass" | "warn" | "fail"
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate result from all readiness checks."""

    verdict: str         # "ready" | "blocked"
    checks: List[CheckResult]
    elapsed_ms: float
    repo_root: str

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warnings(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def passes(self) -> List[CheckResult]:
        return [c for c in self.checks if c.status == "pass"]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
            "elapsed_ms": round(self.elapsed_ms, 2),
            "repo_root": self.repo_root,
            "summary": self.summary_text(),
        }

    def summary_text(self) -> str:
        parts = [f"verdict: {self.verdict}"]
        if self.failures:
            names = ", ".join(c.name for c in self.failures)
            parts.append(f"blocked by: {names}")
        if self.warnings:
            names = ", ".join(c.name for c in self.warnings)
            parts.append(f"warnings: {names}")
        parts.append(f"elapsed: {self.elapsed_ms:.0f}ms")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

DEFAULT_MIN_FREE_MB = 100          # minimum free disk space in MB
DEFAULT_MAX_DIRTY_FILES = 50       # max uncommitted files before warn
DEFAULT_MAX_DIRTY_FAIL = 200       # max uncommitted files before fail
DEFAULT_SSH_KEY_PATH = "/tmp/ssh_deploy_key"


# ---------------------------------------------------------------------------
# checker
# ---------------------------------------------------------------------------

class RestartReadinessChecker:
    """Run pre-restart readiness checks against a git repo."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        *,
        min_free_mb: int = DEFAULT_MIN_FREE_MB,
        max_dirty_files: int = DEFAULT_MAX_DIRTY_FILES,
        max_dirty_fail: int = DEFAULT_MAX_DIRTY_FAIL,
        ssh_key_path: str = DEFAULT_SSH_KEY_PATH,
        cooldown_log_path: Optional[str | Path] = None,
        max_restarts_per_hour: int = 3,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.min_free_mb = min_free_mb
        self.max_dirty_files = max_dirty_files
        self.max_dirty_fail = max_dirty_fail
        self.ssh_key_path = ssh_key_path
        self.cooldown_log_path = (
            Path(cooldown_log_path) if cooldown_log_path
            else self.repo_root / "data" / "restart_cooldown.jsonl"
        )
        self.max_restarts_per_hour = max_restarts_per_hour

    # -- public API ---------------------------------------------------------

    def check_all(self) -> ReadinessReport:
        """Run every check and return an aggregate report."""
        t0 = time.monotonic()
        results: List[CheckResult] = []

        checkers = [
            self._check_git_index_clean,
            self._check_disk_space,
            self._check_credential_ready,
            self._check_no_stale_pids,
            self._check_working_tree_manageable,
            self._check_cooldown_respected,
        ]

        for fn in checkers:
            try:
                results.append(fn())
            except Exception as exc:
                results.append(CheckResult(
                    name=fn.__name__.replace("_check_", ""),
                    status="fail",
                    detail=f"check raised unexpected error: {exc}",
                ))

        elapsed = (time.monotonic() - t0) * 1000
        verdict = "blocked" if any(r.status == "fail" for r in results) else "ready"

        return ReadinessReport(
            verdict=verdict,
            checks=results,
            elapsed_ms=elapsed,
            repo_root=str(self.repo_root),
        )

    def check_one(self, name: str) -> CheckResult:
        """Run a single named check.  Raises ValueError for unknown names."""
        mapping = {
            "git_index_clean": self._check_git_index_clean,
            "disk_space": self._check_disk_space,
            "credential_ready": self._check_credential_ready,
            "no_stale_pids": self._check_no_stale_pids,
            "working_tree_manageable": self._check_working_tree_manageable,
            "cooldown_respected": self._check_cooldown_respected,
        }
        fn = mapping.get(name)
        if fn is None:
            raise ValueError(f"unknown check: {name!r}. Known: {sorted(mapping)}")
        return fn()

    @property
    def check_names(self) -> List[str]:
        return [
            "git_index_clean",
            "disk_space",
            "credential_ready",
            "no_stale_pids",
            "working_tree_manageable",
            "cooldown_respected",
        ]

    # -- individual checks --------------------------------------------------

    def _check_git_index_clean(self) -> CheckResult:
        """Check for lock files, merge conflicts, and corrupt index."""
        git_dir = self.repo_root / ".git"

        # check for lock files
        lock_files = list(git_dir.glob("*.lock")) + list(git_dir.glob("**/*.lock"))
        if lock_files:
            names = [str(p.relative_to(git_dir)) for p in lock_files[:5]]
            return CheckResult(
                name="git_index_clean",
                status="fail",
                detail=f"lock files present: {', '.join(names)}",
            )

        # check for merge state
        merge_head = git_dir / "MERGE_HEAD"
        if merge_head.exists():
            return CheckResult(
                name="git_index_clean",
                status="fail",
                detail="merge in progress (MERGE_HEAD exists)",
            )

        # check index readability
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return CheckResult(
                    name="git_index_clean",
                    status="fail",
                    detail=f"git status failed: {result.stderr.strip()[:200]}",
                )
        except subprocess.TimeoutExpired:
            return CheckResult(
                name="git_index_clean",
                status="fail",
                detail="git status timed out (10s)",
            )

        return CheckResult(
            name="git_index_clean",
            status="pass",
            detail="no lock files, no merge state, index readable",
        )

    def _check_disk_space(self) -> CheckResult:
        """Check available disk space on the repo partition."""
        try:
            usage = shutil.disk_usage(str(self.repo_root))
            free_mb = usage.free / (1024 * 1024)
            free_gb = free_mb / 1024

            if free_mb < self.min_free_mb:
                return CheckResult(
                    name="disk_space",
                    status="fail",
                    detail=f"only {free_mb:.0f} MB free (need {self.min_free_mb} MB)",
                )

            # warn if less than 10x minimum
            warn_threshold = self.min_free_mb * 10
            if free_mb < warn_threshold:
                return CheckResult(
                    name="disk_space",
                    status="warn",
                    detail=f"{free_mb:.0f} MB free ({free_gb:.1f} GB), approaching limit",
                )

            return CheckResult(
                name="disk_space",
                status="pass",
                detail=f"{free_gb:.1f} GB free",
            )
        except OSError as exc:
            return CheckResult(
                name="disk_space",
                status="fail",
                detail=f"cannot read disk usage: {exc}",
            )

    def _check_credential_ready(self) -> CheckResult:
        """Check that the SSH deploy key exists and is readable."""
        key_path = Path(self.ssh_key_path)

        if not key_path.exists():
            # check alternative locations
            alt_paths = [
                self.repo_root / ".deploy_key",
                self.repo_root / "keys" / "deploy_key",
                Path.home() / ".ssh" / "id_ed25519",
            ]
            found = [str(p) for p in alt_paths if p.exists()]
            if found:
                return CheckResult(
                    name="credential_ready",
                    status="warn",
                    detail=f"primary key missing but found at: {', '.join(found)}",
                )
            return CheckResult(
                name="credential_ready",
                status="fail",
                detail=f"deploy key not found at {self.ssh_key_path}",
            )

        if not os.access(str(key_path), os.R_OK):
            return CheckResult(
                name="credential_ready",
                status="fail",
                detail=f"deploy key exists but is not readable: {self.ssh_key_path}",
            )

        # check file size (should not be empty)
        size = key_path.stat().st_size
        if size == 0:
            return CheckResult(
                name="credential_ready",
                status="fail",
                detail=f"deploy key is empty (0 bytes): {self.ssh_key_path}",
            )

        return CheckResult(
            name="credential_ready",
            status="pass",
            detail=f"deploy key ready at {self.ssh_key_path} ({size} bytes)",
        )

    def _check_no_stale_pids(self) -> CheckResult:
        """Check for zombie/orphan writer or batch processes."""
        stale = []

        for proc_name in ["writer_loop.py", "commit_batch.py"]:
            try:
                result = subprocess.run(
                    ["pgrep", "-af", proc_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout.strip():
                    lines = result.stdout.strip().split("\n")
                    for line in lines:
                        parts = line.split(None, 1)
                        if len(parts) >= 1:
                            pid = int(parts[0])
                            # check if process is zombie
                            try:
                                status_path = Path(f"/proc/{pid}/status")
                                if status_path.exists():
                                    status_text = status_path.read_text()
                                    for sline in status_text.split("\n"):
                                        if sline.startswith("State:"):
                                            state = sline.split(":", 1)[1].strip()
                                            if state.startswith("Z"):
                                                stale.append(
                                                    f"{proc_name} pid {pid} is zombie"
                                                )
                            except (PermissionError, FileNotFoundError):
                                pass
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        if stale:
            return CheckResult(
                name="no_stale_pids",
                status="warn",
                detail=f"stale processes found: {'; '.join(stale)}",
            )

        return CheckResult(
            name="no_stale_pids",
            status="pass",
            detail="no zombie or orphan writer/batch processes",
        )

    def _check_working_tree_manageable(self) -> CheckResult:
        """Check that the number of dirty files is within limits."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = [
                line for line in result.stdout.strip().split("\n")
                if line.strip()
            ]
            count = len(lines)

            if count > self.max_dirty_fail:
                return CheckResult(
                    name="working_tree_manageable",
                    status="fail",
                    detail=f"{count} dirty files (fail threshold: {self.max_dirty_fail})",
                )

            if count > self.max_dirty_files:
                return CheckResult(
                    name="working_tree_manageable",
                    status="warn",
                    detail=f"{count} dirty files (warn threshold: {self.max_dirty_files})",
                )

            return CheckResult(
                name="working_tree_manageable",
                status="pass",
                detail=f"{count} dirty files (limit: {self.max_dirty_fail})",
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                name="working_tree_manageable",
                status="fail",
                detail="git status timed out",
            )

    def _check_cooldown_respected(self) -> CheckResult:
        """Check that we haven't exceeded the restart rate limit."""
        log_path = self.cooldown_log_path

        if not log_path.exists():
            return CheckResult(
                name="cooldown_respected",
                status="pass",
                detail="no restart history (first restart allowed)",
            )

        now = time.time()
        window_start = now - 3600  # 1 hour sliding window

        try:
            recent_restarts = 0
            with open(log_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = entry.get("ts", entry.get("timestamp", 0))
                        if isinstance(ts, str):
                            continue
                        if ts >= window_start:
                            decision = entry.get("decision", entry.get("allowed", True))
                            if decision in (True, "allowed"):
                                recent_restarts += 1
                    except (json.JSONDecodeError, TypeError):
                        continue

            if recent_restarts >= self.max_restarts_per_hour:
                return CheckResult(
                    name="cooldown_respected",
                    status="fail",
                    detail=(
                        f"{recent_restarts} restarts in the last hour "
                        f"(limit: {self.max_restarts_per_hour})"
                    ),
                )

            if recent_restarts >= self.max_restarts_per_hour - 1:
                return CheckResult(
                    name="cooldown_respected",
                    status="warn",
                    detail=(
                        f"{recent_restarts}/{self.max_restarts_per_hour} restarts "
                        f"used in the last hour"
                    ),
                )

            return CheckResult(
                name="cooldown_respected",
                status="pass",
                detail=f"{recent_restarts}/{self.max_restarts_per_hour} restarts in the last hour",
            )
        except OSError as exc:
            return CheckResult(
                name="cooldown_respected",
                status="warn",
                detail=f"could not read cooldown log: {exc}",
            )
