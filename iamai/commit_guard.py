"""Commit guard — pre-flight checks before attempting git commit/push.

The batch committer and caretaker both race against the git index.
A failed commit leaves the repo in a dirty state that cascades:
stale index.lock blocks the next commit, a mid-rebase state corrupts
the next pull, and a phantom push process holds credentials open.

This module consolidates the scattered safety checks into one place:

    guard = CommitGuard()
    result = guard.preflight()
    if not result["safe"]:
        for issue in result["issues"]:
            print(f"  blocked: {issue}")

Checks performed:

1. **index_lock** — .git/index.lock exists (another git op in progress)
2. **rebase_in_progress** — .git/rebase-merge/ or .git/rebase-apply/ exists
3. **merge_in_progress** — .git/MERGE_HEAD exists
4. **pending_push** — a push process is still running
5. **stale_pause** — writer pause file exists but no committer is running
6. **dirty_beyond_threshold** — too many uncommitted files (likely a crash)

Each check returns independently so the caller can decide which
failures are fatal and which are warnings.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class GuardResult:
    """Result of a pre-flight check."""

    safe: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe": self.safe,
            "issues": self.issues,
            "warnings": self.warnings,
            "checks": self.checks,
        }


class CommitGuard:
    """Pre-flight safety checks for git operations.

    Args:
        repo_root: path to the repository root
        max_pending_files: threshold for dirty-beyond-threshold check
        writer_id: writer identifier for pause file lookup
    """

    def __init__(
        self,
        repo_root: Path | str | None = None,
        max_pending_files: int = 30,
        writer_id: str = "qwen",
    ) -> None:
        self.repo = Path(repo_root) if repo_root else REPO_ROOT
        self.git_dir = self.repo / ".git"
        self.max_pending = max_pending_files
        self.writer_id = writer_id

    # ── individual checks ────────────────────────────────────────────

    def check_index_lock(self) -> bool:
        """True if .git/index.lock exists (another git op is running)."""
        return (self.git_dir / "index.lock").exists()

    def check_rebase_in_progress(self) -> bool:
        """True if a rebase is in progress."""
        return (
            (self.git_dir / "rebase-merge").exists()
            or (self.git_dir / "rebase-apply").exists()
        )

    def check_merge_in_progress(self) -> bool:
        """True if a merge is in progress."""
        return (self.git_dir / "MERGE_HEAD").exists()

    def check_pending_push(self) -> bool:
        """True if a push process appears to be running."""
        try:
            out = subprocess.run(
                ["pgrep", "-f", "git push"],
                capture_output=True, text=True, timeout=5,
            )
            return out.returncode == 0 and bool(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False

    def check_stale_pause(self) -> bool:
        """True if writer is paused but no committer is running.

        This usually means the committer crashed after pausing the writer
        but before resuming it — the writer is stuck in RED GATE.
        """
        pause_file = Path(f"/tmp/iamai-writer-pause-{self.writer_id}")
        if not pause_file.exists():
            return False

        # Check if committer is alive
        batch_pid = Path(f"/tmp/iamai-batch-{self.writer_id}.pid")
        if not batch_pid.exists():
            return True

        try:
            pid = int(batch_pid.read_text().strip())
            os.kill(pid, 0)  # signal 0 = alive check
            return False
        except (ValueError, OSError):
            return True

    def check_dirty_count(self) -> int:
        """Count uncommitted files."""
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo, capture_output=True, text=True, timeout=10,
            )
            lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
            return len(lines)
        except (OSError, subprocess.SubprocessError):
            return 0

    # ── composite ────────────────────────────────────────────────────

    def preflight(self) -> GuardResult:
        """Run all checks and return a composite result.

        Fatal issues (block commit):
        - index.lock present
        - rebase in progress
        - merge in progress

        Warnings (proceed with caution):
        - pending push (may cause push race)
        - stale pause (writer stuck)
        - dirty beyond threshold
        """
        issues: list[str] = []
        warnings: list[str] = []
        checks: dict[str, bool] = {}

        # Fatal checks
        checks["index_lock"] = self.check_index_lock()
        if checks["index_lock"]:
            issues.append("index.lock exists — another git operation is in progress")

        checks["rebase"] = self.check_rebase_in_progress()
        if checks["rebase"]:
            issues.append("rebase in progress — .git/rebase-merge or rebase-apply exists")

        checks["merge"] = self.check_merge_in_progress()
        if checks["merge"]:
            issues.append("merge in progress — .git/MERGE_HEAD exists")

        # Warning checks
        checks["pending_push"] = self.check_pending_push()
        if checks["pending_push"]:
            warnings.append("push process detected — may cause push race on commit")

        checks["stale_pause"] = self.check_stale_pause()
        if checks["stale_pause"]:
            warnings.append("writer paused but no committer running — RED GATE stuck")

        dirty = self.check_dirty_count()
        checks["dirty_beyond_threshold"] = dirty > self.max_pending
        if checks["dirty_beyond_threshold"]:
            warnings.append(
                f"{dirty} uncommitted files (threshold: {self.max_pending})"
            )

        safe = len(issues) == 0
        return GuardResult(safe=safe, issues=issues, warnings=warnings, checks=checks)

    def snapshot(self) -> dict[str, Any]:
        """Produce a JSON-serialisable snapshot for checkpoint logging."""
        result = self.preflight()
        return {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "safe": result.safe,
            "issues": result.issues,
            "warnings": result.warnings,
            "checks": result.checks,
            "pending_files": self.check_dirty_count(),
        }
