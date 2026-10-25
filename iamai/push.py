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


def safe_push_cli(repo: str | Path, remote: str = "origin", branch: str = "main") -> int:
    """Shell-callable wrapper around :func:`push_with_rebase`.

    Prints a JSON summary to stdout and returns an exit code suitable for
    ``sys.exit()``: 0 on success, 1 on failure.

    The pre-execution harness should call this instead of running
    ``git push`` directly.  It handles the fetch-rebase-push cycle that
    every caretaker visit since 15 has had to redo by hand.

    Usage from a shell script::

        python3 -c "import sys; from iamai.push import safe_push_cli; sys.exit(safe_push_cli('.'))"
    """

    import json
    import sys

    repo = Path(repo).resolve()
    if not (repo / ".git").is_dir():
        print(json.dumps({"ok": False, "detail": f"not a git repo: {repo}"}))
        return 1

    # Stash any uncommitted work so the rebase has a clean tree.
    code, stash_out = _run(repo, "stash", "--include-untracked", "--quiet")
    stashed = code == 0 and "No local changes" not in stash_out

    result = push_with_rebase(repo, remote, branch)

    # Restore the stash if we made one.
    if stashed:
        _run(repo, "stash", "pop", "--quiet")

    print(json.dumps(result))
    return 0 if result.get("ok") else 1


def pre_exec_push(
    repo: str | Path,
    writer_pid: int | None = None,
    remote: str = "origin",
    branch: str = "main",
) -> dict:
    """Full push cycle used by the pre-execution harness.

    The pre-execution harness restarts the writer, then tries to push the
    catch-up commit, and gets rejected because the remote moved.  Every
    caretaker visit since 15 has worked around this by hand.  This function
    automates the workaround:

    1. SIGSTOP the writer (if pid given) so the working tree stops changing.
    2. Stash any uncommitted changes.
    3. Pull --rebase from the remote.
    4. Push with the rebase retry logic from :func:`push_with_rebase`.
    5. Pop the stash.
    6. SIGCONT the writer.

    Steps 5 and 6 run unconditionally — a paused writer that stays paused
    is worse than a failed push.  The result dict includes ``ok``, ``strategy``,
    ``detail``, and ``writer_paused`` (whether the writer was successfully
    stopped and resumed).
    """
    import os
    import signal

    repo = Path(repo).resolve()
    result: dict = {
        "ok": False,
        "strategy": "pre-exec",
        "detail": "",
        "writer_paused": False,
    }

    paused = False
    if writer_pid is not None:
        try:
            os.kill(writer_pid, signal.SIGSTOP)
            paused = True
            result["writer_paused"] = True
        except OSError:
            # Process already gone — that is fine, nothing to pause.
            pass

    try:
        # Stash uncommitted work (the writer may have produced strokes
        # between the restart and this push attempt).
        # Use --porcelain to get a predictable output: prints "Saved working
        # directory ..." on success, nothing when there are no local changes.
        code, stash_out = _run(repo, "stash", "push", "--include-untracked")
        stashed = code == 0 and "No local changes" not in stash_out and stash_out.strip() != ""

        # Pull with rebase to integrate remote changes.
        code, pull_out = _run(
            repo, "-c", "rebase.autoStash=true",
            "pull", "--rebase", remote, branch,
        )
        if code != 0 and "up to date" not in pull_out.lower():
            result["detail"] = f"pull failed: {pull_out.splitlines()[-1] if pull_out else 'unknown'}"
            return result

        # Push using the rebase-aware logic.
        push_result = push_with_rebase(repo, remote, branch)
        result.update({
            "ok": push_result.get("ok", False),
            "strategy": push_result.get("strategy", "pre-exec"),
            "detail": push_result.get("detail", ""),
        })
        return result

    finally:
        # Always restore the stash and resume the writer, even on failure.
        try:
            if stashed:
                _run(repo, "stash", "pop", "--quiet")
        except Exception:
            pass
        if paused:
            try:
                os.kill(writer_pid, signal.SIGCONT)
            except OSError:
                pass
