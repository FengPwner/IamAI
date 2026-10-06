"""Git divergence — measure how far local and remote have drifted.

Push rejections in this repo almost always share one cause: the remote
has commits the local copy does not know about. The batch committer
accumulates local work, then ``git push`` fails because another writer
or caretaker pushed first.

Before attempting a push, it helps to know:

1. How many commits is local *ahead* of the merge-base?
   (These need to be pushed.)
2. How many commits is remote *ahead* of the merge-base?
   (These need to be pulled/rebased.)
3. Is the working tree dirty?

If behind > 0, a pull or rebase is required before push will succeed.
If ahead == 0 and behind == 0, there is nothing to push.
If ahead > 0 and behind == 0, push should succeed without conflict.

This module wraps subprocess calls to ``git`` so it works without any
Python git library. Every function accepts an explicit ``repo`` path
and returns plain integers or strings.

Usage::

    from iamai.git_divergence import divergence

    d = divergence("/path/to/IamAI")
    if d["behind"] > 0:
        # pull --rebase first
    if d["ahead"] > 0:
        # safe to push
    if d["dirty"]:
        # stash or commit before rebase

Design choices:
- Subprocess over GitPython: fewer dependencies, works in minimal containers.
- ``git fetch`` before counting: the remote ref must be fresh, or the
  behind/ahead counts are stale. Fetch failures are non-fatal (offline
  mode returns behind=0, ahead=N).
- Merge-base via ``git merge-base``: handles non-linear histories
  correctly, unlike simple rev-list counting.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict


def _git(repo: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given repository directory."""
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        check=check,
    )


def current_branch(repo: str | Path) -> str:
    """Return the current branch name, or 'HEAD' if detached."""
    r = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip()


def remote_for_branch(repo: str | Path, branch: str) -> str | None:
    """Return the configured remote for *branch*, defaulting to 'origin'."""
    r = _git(repo, "config", f"branch.{branch}.remote", check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    # fall back: check if origin exists
    r2 = _git(repo, "remote", check=False)
    remotes = r2.stdout.strip().splitlines()
    return "origin" if "origin" in remotes else None


def tracking_branch(repo: str | Path, branch: str) -> str | None:
    """Return the remote tracking ref (e.g. 'origin/main') for *branch*."""
    r = _git(repo, "config", f"branch.{branch}.merge", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    # merge config gives refs/heads/<name>; we need <remote>/<name>
    remote = remote_for_branch(repo, branch)
    if not remote:
        return None
    remote_ref = r.stdout.strip()
    # refs/heads/main -> main
    short = remote_ref.replace("refs/heads/", "", 1)
    return f"{remote}/{short}"


def fetch_remote(repo: str | Path, remote: str) -> bool:
    """Fetch from *remote*. Returns True on success."""
    r = _git(repo, "fetch", remote, check=False)
    return r.returncode == 0


def merge_base(repo: str | Path, ref_a: str, ref_b: str) -> str | None:
    """Return the merge-base commit SHA between two refs, or None."""
    r = _git(repo, "merge-base", ref_a, ref_b, check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return None


def count_commits(repo: str | Path, from_ref: str, to_ref: str) -> int:
    """Count commits reachable from *to_ref* but not from *from_ref*."""
    r = _git(repo, "rev-list", "--count", f"{from_ref}..{to_ref}", check=False)
    if r.returncode == 0 and r.stdout.strip():
        return int(r.stdout.strip())
    return 0


def is_dirty(repo: str | Path) -> bool:
    """Return True if the working tree has uncommitted changes."""
    r = _git(repo, "status", "--porcelain", check=False)
    return bool(r.stdout.strip())


def uncommitted_count(repo: str | Path) -> int:
    """Return the number of files with uncommitted changes."""
    r = _git(repo, "status", "--porcelain", check=False)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    return len(lines)


def is_rebasing(repo: str | Path) -> bool:
    """Return True if a rebase is in progress."""
    git_dir_result = _git(repo, "rev-parse", "--git-dir", check=False)
    if git_dir_result.returncode != 0:
        return False
    git_dir = Path(repo) / git_dir_result.stdout.strip()
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def is_merging(repo: str | Path) -> bool:
    """Return True if a merge is in progress."""
    git_dir_result = _git(repo, "rev-parse", "--git-dir", check=False)
    if git_dir_result.returncode != 0:
        return False
    git_dir = Path(repo) / git_dir_result.stdout.strip()
    return (git_dir / "MERGE_HEAD").exists()


def has_conflict_markers(repo: str | Path) -> list[str]:
    """Return a list of files containing git conflict markers."""
    r = _git(
        repo, "grep", "--name-only",
        "-e", "<<<<<<< ",
        "-e", "======= ",
        "-e", ">>>>>>> ",
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []
    seen: set[str] = set()
    for line in r.stdout.strip().splitlines():
        # git grep output: filename:matched_line or just filename with --name-only
        name = line.split(":")[0].strip()
        if name:
            seen.add(name)
    return sorted(seen)


def divergence(
    repo: str | Path,
    do_fetch: bool = True,
) -> Dict[str, Any]:
    """Compute full divergence status between local and remote.

    Parameters
    ----------
    repo : path-like
        Path to the git repository.
    do_fetch : bool
        If True (default), run ``git fetch`` before counting. Set to
        False if you have already fetched recently.

    Returns
    -------
    dict with keys:
        branch (str): current branch name
        remote (str|None): configured remote name
        tracking (str|None): remote tracking ref
        ahead (int): local commits not yet on remote
        behind (int): remote commits not yet local
        dirty (bool): working tree has uncommitted changes
        uncommitted (int): count of dirty files
        rebasing (bool): rebase in progress
        merging (bool): merge in progress
        conflict_files (list[str]): files with conflict markers
        fetch_ok (bool): whether fetch succeeded
    """
    branch = current_branch(repo)
    remote = remote_for_branch(repo, branch)
    tracking = tracking_branch(repo, branch)

    result: Dict[str, Any] = {
        "branch": branch,
        "remote": remote,
        "tracking": tracking,
        "ahead": 0,
        "behind": 0,
        "dirty": is_dirty(repo),
        "uncommitted": uncommitted_count(repo),
        "rebasing": is_rebasing(repo),
        "merging": is_merging(repo),
        "conflict_files": has_conflict_markers(repo),
        "fetch_ok": False,
    }

    if not tracking or not remote:
        return result

    if do_fetch:
        result["fetch_ok"] = fetch_remote(repo, remote)
        if not result["fetch_ok"]:
            # Cannot fetch (offline?) — behind count unreliable
            return result
    else:
        result["fetch_ok"] = True  # caller asserts it's fresh

    base = merge_base(repo, "HEAD", tracking)
    if base is None:
        # No common ancestor — orphan branches or corrupt repo
        return result

    result["ahead"] = count_commits(repo, base, "HEAD")
    result["behind"] = count_commits(repo, base, tracking)
    return result


def push_safe(repo: str | Path, do_fetch: bool = True) -> tuple[bool, str]:
    """Quick check: is it safe to push right now?

    Returns (safe, reason) where safe is True if push should succeed,
    and reason explains why not if safe is False.
    """
    d = divergence(repo, do_fetch=do_fetch)

    if d["rebasing"]:
        return False, "rebase in progress — finish or abort first"
    if d["merging"]:
        return False, "merge in progress — finish or abort first"
    if d["conflict_files"]:
        return False, f"conflict markers in {len(d['conflict_files'])} file(s)"
    if d["behind"] > 0:
        return False, f"local is {d['behind']} commit(s) behind — pull first"
    if d["ahead"] == 0 and d["uncommitted"] == 0:
        return False, "nothing to push"
    if d["dirty"] and d["ahead"] == 0:
        return False, "dirty tree with no commits — stash or commit first"

    return True, f"{d['ahead']} commit(s) ready to push"
