"""Pre-push divergence check: will a plain ``git push`` succeed right now?

The caretaker harness used to commit the backlog and immediately push, assuming
the remote hadn't moved. That assumption broke every time another writer pushed
between our last fetch and our push attempt — the rejection left ten files
committed locally but never synced, and the next reclamation event found them
still sitting there.

This module answers one question before you push: *has the remote moved since
my last fetch?* If yes, fetch first and rebase; if no, push is safe.

The check is deliberately cheap: one ``git rev-parse`` per side, one comparison.
No network call unless the cached remote ref is stale — and staleness is itself
a signal that you should fetch before trusting the answer.

    from iamai.push_guard import needs_rebase
    if needs_rebase(repo):
        # fetch + rebase before pushing
    else:
        # plain push is safe
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def local_head(repo: Path) -> str | None:
    """Return the SHA of HEAD, or None if the repo has no commits yet."""
    code, out = _run(repo, "rev-parse", "--verify", "--quiet", "HEAD")
    return out.splitlines()[0] if code == 0 and out else None


def remote_tip(repo: Path, remote: str = "origin", branch: str = "main") -> str | None:
    """Return the cached SHA of ``remote/branch`` (no network call).

    Returns None when the tracking ref does not exist locally — which means
    either the branch was never fetched, or it was deleted on the remote.
    Either way, a push *might* work, but you should fetch first to be sure.
    """
    code, out = _run(repo, "rev-parse", "--verify", "--quiet", f"{remote}/{branch}")
    return out.splitlines()[0] if code == 0 and out else None


def merge_base(repo: Path, left: str, right: str) -> str | None:
    """Return the merge-base of two commits, or None if they're unrelated."""
    code, out = _run(repo, "merge-base", left, right)
    return out.splitlines()[0] if code == 0 and out else None


def needs_rebase(
    repo: Path | str,
    remote: str = "origin",
    branch: str = "main",
) -> bool:
    """True when the remote has commits that local HEAD doesn't include.

    This is the condition that causes ``git push`` to be rejected with a
    non-fast-forward error. When True, the caller should ``git fetch`` and
    then ``git rebase`` before attempting to push.

    Returns False when:
    - local HEAD is a descendant of the cached remote tip (push is safe)
    - the remote tracking ref doesn't exist (first push, nothing to rebase onto)
    - there are no local commits yet
    """
    repo = Path(repo)
    head = local_head(repo)
    if head is None:
        return False  # nothing to push, nothing to rebase

    tip = remote_tip(repo, remote, branch)
    if tip is None:
        return False  # no remote tracking ref; first push

    if head == tip:
        return False  # in sync

    base = merge_base(repo, head, tip)
    if base == tip:
        return False  # local is ahead of remote; push should work

    # remote has commits that local doesn't descend from → push will be rejected
    return True


def divergence_info(
    repo: Path | str,
    remote: str = "origin",
    branch: str = "main",
) -> dict:
    """Detailed divergence report for logging and diagnostics.

    Returns a dict with:
    - ``local``: local HEAD SHA (or None)
    - ``remote``: cached remote tip SHA (or None)
    - ``base``: merge-base SHA (or None)
    - ``local_ahead``: number of local-only commits
    - ``remote_ahead``: number of remote-only commits
    - ``needs_rebase``: boolean, same as ``needs_rebase()``
    """
    repo = Path(repo)
    head = local_head(repo)
    tip = remote_tip(repo, remote, branch)
    base = merge_base(repo, head, tip) if head and tip else None

    local_ahead = 0
    remote_ahead = 0

    if head and tip and head != tip:
        code, out = _run(repo, "rev-list", "--count", f"{tip}..{head}")
        if code == 0 and out:
            local_ahead = int(out.strip())
        code, out = _run(repo, "rev-list", "--count", f"{head}..{tip}")
        if code == 0 and out:
            remote_ahead = int(out.strip())

    return {
        "local": head,
        "remote": tip,
        "base": base,
        "local_ahead": local_ahead,
        "remote_ahead": remote_ahead,
        "needs_rebase": remote_ahead > 0,
    }
