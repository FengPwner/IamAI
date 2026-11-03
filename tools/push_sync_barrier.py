#!/usr/bin/env python3
"""Pre-push synchronization barrier.

Checks whether the local branch can push cleanly to the remote before
attempting the push. Detects divergence early so the caller can invoke
auto_push_recovery proactively instead of reacting to a rejected push.

Usage:
    from push_sync_barrier import check_barrier, BarrierResult
    result = check_barrier(repo_path=".", remote="origin", branch="main")
    if not result.ok:
        print(f"barrier failed: {result.reason}")
        # call auto_push_recovery here

Design choices:
    - Uses only git plumbing commands (merge-base, rev-parse) for
      deterministic results; no porcelain parsing.
    - Zero external dependencies beyond subprocess.
    - Dry-run mode for testing without side effects.

Exit codes (CLI):
    0 - barrier passed, safe to push
    1 - barrier failed, divergence detected
    2 - error (no remote, no commits, etc.)
"""

import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class BarrierResult:
    """Result of a push synchronization barrier check."""
    ok: bool
    divergence: str  # "clean" | "ahead" | "behind" | "diverged" | "error"
    reason: str
    local_sha: str = ""
    remote_sha: str = ""
    merge_base: str = ""
    action: str = ""  # recommended action for the caller

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _git(repo: str, *args: str, check: bool = True) -> Optional[str]:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if check and result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _resolve_sha(repo: str, ref: str) -> Optional[str]:
    """Resolve a ref to a SHA."""
    return _git(repo, "rev-parse", "--verify", ref)


def _merge_base(repo: str, a: str, b: str) -> Optional[str]:
    """Find the merge base of two commits."""
    return _git(repo, "merge-base", a, b)


def _is_ancestor(repo: str, ancestor: str, descendant: str) -> bool:
    """Check if ancestor is an ancestor of descendant."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


def classify_divergence(
    repo: str,
    local_sha: str,
    remote_sha: str,
) -> str:
    """Classify the divergence between local and remote.

    Returns one of: "clean", "ahead", "behind", "diverged".
    """
    if local_sha == remote_sha:
        return "clean"

    # Is local ahead of remote?
    if _is_ancestor(repo, remote_sha, local_sha):
        return "ahead"

    # Is local behind remote?
    if _is_ancestor(repo, local_sha, remote_sha):
        return "behind"

    return "diverged"


def check_barrier(
    repo_path: str = ".",
    remote: str = "origin",
    branch: str = "main",
    dry_run: bool = False,
) -> BarrierResult:
    """Check whether it is safe to push.

    Args:
        repo_path: Path to the git repository.
        remote: Remote name (default: origin).
        branch: Branch name (default: main).
        dry_run: If True, skip the fetch step (for testing).

    Returns:
        BarrierResult with ok=True if push is safe, ok=False otherwise.
    """
    repo = str(Path(repo_path).resolve())

    # Ensure we have a valid repo
    if _git(repo, "rev-parse", "--git-dir") is None:
        return BarrierResult(
            ok=False,
            divergence="error",
            reason="not a git repository",
            action="verify repo_path",
        )

    # Fetch latest remote state (unless dry_run)
    if not dry_run:
        fetch_out = _git(repo, "fetch", remote, check=False)
        # fetch can fail for network reasons; we still have cached remote refs

    # Resolve local HEAD
    local_sha = _resolve_sha(repo, "HEAD")
    if not local_sha:
        return BarrierResult(
            ok=False,
            divergence="error",
            reason="cannot resolve HEAD (no commits?)",
            action="make an initial commit",
        )

    # Resolve remote ref
    remote_ref = f"{remote}/{branch}"
    remote_sha = _resolve_sha(repo, remote_ref)
    if not remote_sha:
        return BarrierResult(
            ok=False,
            divergence="error",
            reason=f"cannot resolve {remote_ref} (no remote or branch?)",
            action=f"check remote '{remote}' and branch '{branch}'",
        )

    # Find merge base
    base = _merge_base(repo, local_sha, remote_sha)
    if base is None:
        return BarrierResult(
            ok=False,
            divergence="diverged",
            reason="no common ancestor (unrelated histories)",
            local_sha=local_sha,
            remote_sha=remote_sha,
            action="manual intervention required",
        )

    # Classify
    divergence = classify_divergence(repo, local_sha, remote_sha)

    if divergence == "clean":
        return BarrierResult(
            ok=True,
            divergence="clean",
            reason="local and remote are identical",
            local_sha=local_sha,
            remote_sha=remote_sha,
            merge_base=base,
            action="push (nothing to push)",
        )

    if divergence == "ahead":
        return BarrierResult(
            ok=True,
            divergence="ahead",
            reason="local is ahead of remote, safe to push",
            local_sha=local_sha,
            remote_sha=remote_sha,
            merge_base=base,
            action="push",
        )

    if divergence == "behind":
        return BarrierResult(
            ok=False,
            divergence="behind",
            reason="local is behind remote, pull before push",
            local_sha=local_sha,
            remote_sha=remote_sha,
            merge_base=base,
            action="pull --rebase then push",
        )

    # diverged
    return BarrierResult(
        ok=False,
        divergence="diverged",
        reason="local and remote have diverged, rebase required",
        local_sha=local_sha,
        remote_sha=remote_sha,
        merge_base=base,
        action="rebase onto remote then push, or call auto_push_recovery",
    )


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Pre-push synchronization barrier")
    parser.add_argument("--repo", default=".", help="Path to git repo")
    parser.add_argument("--remote", default="origin", help="Remote name")
    parser.add_argument("--branch", default="main", help="Branch name")
    parser.add_argument("--dry-run", action="store_true", help="Skip fetch")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = check_barrier(
        repo_path=args.repo,
        remote=args.remote,
        branch=args.branch,
        dry_run=args.dry_run,
    )

    if args.json:
        print(result.to_json())
    else:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] divergence={result.divergence}")
        print(f"  reason: {result.reason}")
        print(f"  action: {result.action}")
        if result.local_sha:
            print(f"  local:  {result.local_sha[:12]}")
        if result.remote_sha:
            print(f"  remote: {result.remote_sha[:12]}")

    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
