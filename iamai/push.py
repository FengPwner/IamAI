"""Push that copes with other writers, and never overwrites them.

Multiple agents are going to commit to this repository. The moment two of them push
inside the same minute, one gets rejected (non-fast-forward) and the tempting fix --
``push --force`` -- is the one that destroys the other's commits. This module exists
so the loop can't be "helped" into that.

The only recovery allowed here is: fetch, rebase my own unpushed commits on top of
theirs, push again. If the rebase conflicts, we abort it and report the conflict.
An unresolved conflict is information; a force push is amnesia.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FORCE_FLAGS = ("--force", "--force-with-lease", "-f", "--no-verify")


def _run(repo: Path, *args: str) -> tuple[int, str]:
    cmd = ["git", *args]
    joined = " ".join(cmd)
    for flag in FORCE_FLAGS:
        if flag in args:
            raise ValueError(f"refusing to run a destructive git command: {joined}")
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _identity(repo: Path) -> tuple[str, str] | None:
    """Reuse the last commit's author as the committer for a rebase.

    A clone of a bare repo usually has no user.name configured, and rebase refuses
    without one. Taking it from HEAD keeps the rebase honest about who wrote what
    instead of inventing a bot identity.
    """

    code, out = _run(repo, "log", "-1", "--format=%an%x1f%ae")
    if code != 0 or "\x1f" not in out:
        return None
    name, _, email = out.partition("\x1f")
    return name or "unknown", email or "unknown@example.invalid"


def push_with_rebase(repo, remote: str = "origin", branch: str = "main", attempts: int = 3) -> dict:
    """Push HEAD to ``remote/branch``, rebasing over other writers when rejected."""

    repo = Path(repo)
    result = {"ok": False, "strategy": "push", "detail": "", "attempts": 0}

    code, out = _run(repo, "push", remote, f"HEAD:{branch}")
    if code == 0:
        result.update(ok=True, detail=out or "pushed")
        return result

    # Rejected: somebody else moved the branch first.
    for attempt in range(1, max(1, attempts) + 1):
        result["attempts"] = attempt
        code, fetched = _run(repo, "fetch", remote, branch)
        if code != 0:
            # Either the branch does not exist remotely yet, or the remote is gone.
            if "not found" in fetched.lower() or "no such ref" in fetched.lower():
                retry_code, retry_out = _run(repo, "push", remote, f"HEAD:{branch}")
                if retry_code == 0:
                    result.update(ok=True, detail=retry_out or "pushed to new branch")
                    return result
            result["detail"] = fetched
            continue

        theirs = f"{remote}/{branch}"
        code, base = _run(repo, "rev-parse", "--verify", "--quiet", theirs)
        if code != 0:
            retry_code, retry_out = _run(repo, "push", remote, f"HEAD:{branch}")
            if retry_code == 0:
                result.update(ok=True, detail=retry_out or "pushed")
                return result
            result["detail"] = retry_out
            continue

        ident = _identity(repo)
        cfg = []
        if ident:
            cfg = ["-c", f"user.name={ident[0]}", "-c", f"user.email={ident[1]}"]

        # autoStash matters here: a live writer may have an uncommitted stroke in the
        # tree at the exact moment a push gets rejected.
        code, rebased = _run(repo, *cfg, "-c", "rebase.autoStash=true", "rebase", theirs)
        if code != 0:
            _run(repo, "rebase", "--abort")
            result["strategy"] = "blocked"
            result["detail"] = f"merge conflict against {theirs}: {rebased.splitlines()[-1] if rebased else 'rebase failed'}"
            return result

        result["strategy"] = "rebase-then-push"
        code, out = _run(repo, "push", remote, f"HEAD:{branch}")
        if code == 0:
            result["ok"] = True
            result["detail"] = out or "pushed after rebase"
            return result

    if result["strategy"] == "push":
        result["strategy"] = "blocked"
    return result
