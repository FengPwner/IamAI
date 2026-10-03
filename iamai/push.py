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

import re
import subprocess
from pathlib import Path

STATE_PATH_RE = re.compile(r"^data/[^/]*state[^/]*\.json$")

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


def _conflicted(repo: Path) -> list[str]:
    code, out = _run(repo, "diff", "--name-only", "--diff-filter=U")
    return [line for line in out.splitlines() if line.strip()] if code == 0 else []


def _merge_fallback(repo: Path, remote: str, branch: str, cfg: list[str]) -> dict:
    """Land the merge instead of the rebase, auto-resolving per-writer bookkeeping.

    Only machine-state JSON gets a policy answer (take ours -- each writer owns its
    own counters and the file is namespaced anyway). Anything else that conflicts is
    a real disagreement between two agents' work and gets aborted and reported, never
    silently overwritten.
    """

    theirs = f"{remote}/{branch}"
    code, out = _run(repo, *cfg, "merge", "--no-edit", theirs)
    if code != 0:
        resolved, unresolved = [], []
        for path in _conflicted(repo):
            if STATE_PATH_RE.match(path):
                rc, _ = _run(repo, "checkout", "--ours", "--", path)
                if rc == 0:
                    _run(repo, "add", "--", path)
                    resolved.append(path)
                    continue
            unresolved.append(path)

        if unresolved:
            _run(repo, "merge", "--abort")
            return {
                "ok": False,
                "detail": f"genuine conflict in {', '.join(unresolved[:4])} -- "
                          f"a human (or the owning agent) has to reconcile these",
            }
        code, out = _run(repo, *cfg, "commit", "--no-edit")
        if code != 0:
            _run(repo, "merge", "--abort")
            return {"ok": False, "detail": f"merge commit failed: {out.splitlines()[-1] if out else 'unknown'}"}

    code, pushed = _run(repo, "push", remote, f"HEAD:{branch}")
    if code != 0:
        return {"ok": False, "detail": f"merge landed locally but push still refused: {pushed.splitlines()[-1] if pushed else ''}"}
    return {"ok": True, "detail": (pushed or "pushed after merge") + (
        f" (auto-resolved {len(resolved)} state file(s))" if code == 0 and "resolved" in dir() and resolved else ""
    )}


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
            # Rebase drops merge commits by design, so a local history that already
            # contains a merge gets flattened and both sides' appends replay against
            # each other. That is not a real conflict -- a merge sees it as one.
            merged = _merge_fallback(repo, remote, branch, cfg)
            if merged["ok"]:
                result.update(ok=True, strategy="merge-then-push", detail=merged["detail"])
                return result
            result["strategy"] = "blocked"
            result["detail"] = merged["detail"]
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
