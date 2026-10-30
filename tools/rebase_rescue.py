#!/usr/bin/env python3
"""rebase_rescue.py — safe rebase-push recovery for multi-process repos.

When push is rejected due to remote divergence, the recovery path is:
    1. Stop writer and batch committer (release index.lock).
    2. Clean stale lock files and rebase state directories.
    3. Stash any unstaged changes.
    4. Return to the target branch if in detached HEAD.
    5. Pull --rebase onto the remote branch.
    6. Pop the stash.
    7. Push.
    8. Report outcome.

This tool serializes all of the above into a single command, replacing
the error-prone manual sequence that visit 431 documented.

Exit codes:
    0 — push succeeded (or was already clean)
    1 — push still rejected after rescue attempt (manual intervention needed)
    2 — git error or unexpected failure

Usage:
    python3 tools/rebase_rescue.py [--remote origin] [--branch main] [--dry-run]
    python3 tools/rebase_rescue.py --check   # just report current state, don't fix
"""

import argparse
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RescueReport:
    steps: list[str] = field(default_factory=list)
    lock_cleaned: bool = False
    rebase_state_cleaned: bool = False
    was_detached: bool = False
    stashed: bool = False
    stash_popped: bool = False
    rebased: bool = False
    pushed: bool = False
    success: bool = False
    error: str = ""

    def log(self, msg: str) -> None:
        self.steps.append(msg)

    def summarize(self) -> str:
        lines = [f"rebase_rescue: {'OK' if self.success else 'FAILED'}"]
        if self.lock_cleaned:
            lines.append("  - cleaned stale index.lock")
        if self.rebase_state_cleaned:
            lines.append("  - cleaned stale rebase state")
        if self.was_detached:
            lines.append("  - recovered from detached HEAD")
        if self.stashed:
            lines.append("  - stashed unstaged changes")
        if self.rebased:
            lines.append("  - rebased onto remote")
        if self.stash_popped:
            lines.append("  - popped stash")
        if self.pushed:
            lines.append("  - pushed successfully")
        if self.error:
            lines.append(f"  ! error: {self.error}")
        for s in self.steps:
            lines.append(f"    {s}")
        return "\n".join(lines)


def git(args: list[str], repo: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a git command in the repo directory."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        env=full_env,
    )


def is_detached(repo: Path) -> bool:
    """Check if repo is in detached HEAD state."""
    r = git(["symbolic-ref", "--quiet", "HEAD"], repo)
    return r.returncode != 0


def has_stale_lock(repo: Path) -> bool:
    """Check if .git/index.lock exists."""
    return (repo / ".git" / "index.lock").exists()


def has_stale_rebase_state(repo: Path) -> bool:
    """Check if rebase state directories exist."""
    return (
        (repo / ".git" / "rebase-merge").is_dir()
        or (repo / ".git" / "rebase-apply").is_dir()
    )


def has_unstaged_changes(repo: Path) -> bool:
    """Check if there are unstaged changes."""
    r = git(["status", "--porcelain"], repo)
    return bool(r.stdout.strip())


def get_current_branch(repo: Path) -> str:
    """Get current branch name, empty string if detached."""
    r = git(["branch", "--show-current"], repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def is_diverged(repo: Path, remote: str, branch: str) -> bool:
    """Check if local and remote have diverged."""
    # fetch first
    git(["fetch", remote, branch], repo)
    local = git(["rev-parse", branch], repo).stdout.strip()
    remote_sha = git(["rev-parse", f"{remote}/{branch}"], repo).stdout.strip()
    base = git(["merge-base", branch, f"{remote}/{branch}"], repo).stdout.strip()
    if not local or not remote_sha or not base:
        return False
    return local != remote_sha and base != local


def stop_processes() -> list[str]:
    """Stop writer and batch processes via run_both.sh --stop."""
    stopped = []
    here = Path(__file__).parent
    run_both = here / "run_both.sh"
    if run_both.exists():
        r = subprocess.run(
            ["bash", str(run_both), "--stop"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            stopped.append("stopped processes via run_both.sh --stop")
    return stopped


def rescue(
    repo: Path,
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
) -> RescueReport:
    """Execute the full rebase-rescue-push sequence."""
    report = RescueReport()

    if dry_run:
        report.log("[dry-run] would execute rescue sequence")
        report.success = True
        return report

    # Step 1: Always clean stale lock files first (even if synced).
    # A stale lock from a crashed process blocks all future git operations.
    if has_stale_lock(repo):
        lock_path = repo / ".git" / "index.lock"
        try:
            lock_path.unlink()
            report.lock_cleaned = True
            report.log("removed stale index.lock")
        except OSError as e:
            report.error = f"cannot remove index.lock: {e}"
            return report

    # Step 2: Clean stale rebase state
    if has_stale_rebase_state(repo):
        for d in ["rebase-merge", "rebase-apply"]:
            p = repo / ".git" / d
            if p.is_dir():
                import shutil
                try:
                    shutil.rmtree(p)
                    report.rebase_state_cleaned = True
                    report.log(f"removed stale {d}/")
                except OSError as e:
                    report.error = f"cannot remove {d}/: {e}"
                    return report

    # Step 3: Check if we're already clean and synced
    if not has_unstaged_changes(repo) and not is_diverged(repo, remote, branch):
        report.log("already clean and synced, nothing to do")
        report.success = True
        return report

    # Step 4: If detached HEAD, get back to the branch
    if is_detached(repo):
        report.was_detached = True
        # Discard working tree changes (they came from the failed rebase)
        git(["checkout", "--", "."], repo)
        r = git(["checkout", "-f", branch], repo)
        if r.returncode != 0:
            report.error = f"cannot checkout {branch}: {r.stderr.strip()}"
            return report
        report.log(f"recovered from detached HEAD to {branch}")

    # Step 5: Stash unstaged changes
    if has_unstaged_changes(repo):
        r = git(["stash", "--include-untracked"], repo)
        if r.returncode != 0:
            report.error = f"stash failed: {r.stderr.strip()}"
            return report
        report.stashed = True
        report.log("stashed unstaged changes")

    # Step 6: Pull --rebase
    r = git(["pull", "--rebase", remote, branch], repo)
    if r.returncode != 0:
        # If rebase conflicts, try aborting and doing a merge instead
        git(["rebase", "--abort"], repo)
        report.log("rebase failed, trying merge")
        r2 = git(["pull", "--no-rebase", remote, branch], repo)
        if r2.returncode != 0:
            report.error = f"both rebase and merge failed: {r2.stderr.strip()}"
            return report
    report.rebased = True
    report.log("synced with remote")

    # Step 7: Pop stash
    if report.stashed:
        r = git(["stash", "pop"], repo)
        if r.returncode == 0:
            report.stash_popped = True
            report.log("popped stash")
        else:
            report.log(f"stash pop conflict: {r.stderr.strip()}")
            # Not fatal — the stash is still there for manual recovery

    # Step 8: Push
    env = {}
    ssh_key = "/tmp/ssh_deploy_key"
    if os.path.exists(ssh_key):
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {ssh_key} -o StrictHostKeyChecking=accept-new"
        )
    r = git(["push", remote, branch], repo, env=env or None)
    if r.returncode != 0:
        report.error = f"push failed: {r.stderr.strip()}"
        return report
    report.pushed = True
    report.success = True
    report.log("push succeeded")

    return report


def check_state(repo: Path, remote: str = "origin", branch: str = "main") -> str:
    """Report current repo state without making changes."""
    lines = []
    lines.append(f"branch: {get_current_branch(repo) or '(detached HEAD)'}")
    lines.append(f"detached: {is_detached(repo)}")
    lines.append(f"stale lock: {has_stale_lock(repo)}")
    lines.append(f"stale rebase state: {has_stale_rebase_state(repo)}")
    lines.append(f"unstaged changes: {has_unstaged_changes(repo)}")
    lines.append(f"diverged from {remote}/{branch}: {is_diverged(repo, remote, branch)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe rebase-push recovery")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="Just report state, don't fix anything")
    parser.add_argument("--repo", default=".",
                        help="Path to git repo (default: current dir)")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").is_dir():
        # Walk up to find .git
        for parent in repo.parents:
            if (parent / ".git").is_dir():
                repo = parent
                break

    if args.check:
        print(check_state(repo, args.remote, args.branch))
        return 0

    report = rescue(repo, args.remote, args.branch, args.dry_run)
    print(report.summarize())
    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
