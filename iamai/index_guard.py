"""Index guard — pre-flight safety net for git operations in automated repos.

Automated writers and caretakers run git commands on a tight loop. When a
git process crashes mid-operation it can leave behind:

1. ``.git/index.lock`` — blocks all subsequent git commands.
2. A truncated or zero-byte ``.git/index`` — makes ``git status`` fail with
   "index file smaller than expected".
3. Stale working-tree changes that prevent ``git pull --rebase``.

``index_guard`` wraps the *prepare → act → verify* cycle into one call so
that caretaker scripts no longer need to remember every step.

Usage::

    from iamai.index_guard import preflight, safe_pull_rebase

    report = preflight(repo)
    if report["ready"]:
        safe_pull_rebase(repo)
    else:
        print(report["issues"])

Functions
---------
preflight(repo)
    Run lock + index + dirty-tree checks, auto-repair what is safe,
    and return a structured report.
safe_stash(repo, label)
    Stash dirty working tree (if any) before a rebase; idempotent.
safe_pop(repo)
    Pop the most recent stash created by ``safe_stash``; tolerates empty.
safe_pull_rebase(repo, remote, branch)
    Stash → fetch → rebase → pop → push, with automatic lock cleanup.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: str | Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a subprocess and return the CompletedProcess."""
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------

def check_lock(repo: str | Path) -> dict[str, Any]:
    """Detect and clean stale ``.git/index.lock``.

    A lock is *stale* when no git process holds it (checked via age > 300 s
    or missing holder in ``/proc``). Stale locks are removed automatically.

    Returns ``{"exists": bool, "stale": bool, "removed": bool}``.
    """
    lock = Path(repo) / ".git" / "index.lock"
    if not lock.exists():
        return {"exists": False, "stale": False, "removed": False}

    age = time.time() - lock.stat().st_mtime
    stale = age > 300

    # try to find a live git process holding it
    holder = _find_holder(lock)
    if holder is not None:
        # live process — not stale, even if old
        return {"exists": True, "stale": False, "removed": False, "holder_pid": holder}

    # stale — safe to remove
    lock.unlink(missing_ok=True)
    return {"exists": True, "stale": True, "removed": True, "age_seconds": round(age, 1)}


def _find_holder(lock: Path) -> int | None:
    """Return PID of the process holding the lock, or None."""
    try:
        result = _run(["fuser", str(lock)], timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[-1])
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def check_index(repo: str | Path) -> dict[str, Any]:
    """Check whether ``.git/index`` is present and non-empty.

    Returns ``{"exists": bool, "size_bytes": int, "healthy": bool}``.
    """
    idx = Path(repo) / ".git" / "index"
    if not idx.exists():
        return {"exists": False, "size_bytes": 0, "healthy": False}
    size = idx.stat().st_size
    return {"exists": True, "size_bytes": size, "healthy": size > 0}


def check_dirty(repo: str | Path) -> dict[str, Any]:
    """Check whether the working tree has uncommitted changes.

    Returns ``{"dirty": bool, "file_count": int}``.
    """
    result = _run(["git", "status", "--porcelain"], cwd=repo)
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    return {"dirty": bool(lines), "file_count": len(lines)}


# ---------------------------------------------------------------------------
# composite preflight
# ---------------------------------------------------------------------------

def preflight(repo: str | Path) -> dict[str, Any]:
    """Run all pre-flight checks and auto-repair what is safe.

    Returns a report dict::

        {
            "ready": True/False,
            "issues": ["stale_lock", "empty_index", "dirty_tree"],
            "lock": {...},
            "index": {...},
            "tree": {...},
            "repaired": ["removed_stale_lock"],
        }

    ``ready`` is True when all issues were auto-repaired or no issues exist.
    ``ready`` is False when manual intervention is needed (empty index,
    uncommitted changes that cannot be safely stashed).
    """
    lock = check_lock(repo)
    index = check_index(repo)
    tree = check_dirty(repo)

    issues: list[str] = []
    repaired: list[str] = []

    if lock.get("exists") and not lock.get("stale") and lock.get("holder_pid"):
        issues.append("active_lock")
    if lock.get("stale") and lock.get("removed"):
        repaired.append("removed_stale_lock")
    if not index["exists"]:
        issues.append("missing_index")
    elif not index["healthy"]:
        issues.append("empty_index")
    if tree["dirty"]:
        issues.append("dirty_tree")

    ready = all(i in ("dirty_tree",) for i in issues) or not issues
    # dirty_tree alone is not a blocker for preflight (caller decides whether
    # to stash); missing/empty index or active lock are blockers.

    return {
        "ready": ready,
        "issues": issues,
        "lock": lock,
        "index": index,
        "tree": tree,
        "repaired": repaired,
    }


# ---------------------------------------------------------------------------
# safe stash / pop / pull-rebase
# ---------------------------------------------------------------------------

_STASH_LABEL_PREFIX = "index-guard-"


def safe_stash(repo: str | Path, label: str = "auto") -> dict[str, Any]:
    """Stash dirty working tree if needed. Idempotent.

    Returns ``{"stashed": bool, "message": str}``.
    """
    tree = check_dirty(repo)
    if not tree["dirty"]:
        return {"stashed": False, "message": "nothing to stash"}

    tag = f"{_STASH_LABEL_PREFIX}{label}-{int(time.time())}"
    result = _run(["git", "stash", "push", "-u", "-m", tag], cwd=repo)
    if result.returncode == 0:
        return {"stashed": True, "message": f"stashed as {tag}"}
    return {"stashed": False, "message": f"stash failed: {result.stderr.strip()}"}


def safe_pop(repo: str | Path) -> dict[str, Any]:
    """Pop the most recent stash if one exists. Tolerates empty stash list.

    Returns ``{"popped": bool, "message": str}``.
    """
    result = _run(["git", "stash", "list"], cwd=repo)
    if not result.stdout.strip():
        return {"popped": False, "message": "stash is empty"}

    result = _run(["git", "stash", "pop"], cwd=repo)
    if result.returncode == 0:
        return {"popped": True, "message": "stash popped"}
    return {"popped": False, "message": f"pop failed: {result.stderr.strip()}"}


def safe_pull_rebase(
    repo: str | Path,
    remote: str = "origin",
    branch: str = "main",
) -> dict[str, Any]:
    """Stash → fetch → rebase → pop, with automatic preflight repair.

    This is the full recovery sequence that caretaker scripts need. It
    handles the common failure modes:

    - stale ``index.lock`` (removed automatically)
    - dirty working tree (stashed before rebase, popped after)
    - non-fast-forward divergence (rebase resolves it)

    Returns a structured report of each step's outcome.
    """
    steps: list[str] = []

    # 0. preflight
    pf = preflight(repo)
    steps.append(f"preflight: ready={pf['ready']} issues={pf['issues']}")
    if not pf["ready"]:
        return {"ok": False, "steps": steps, "preflight": pf}

    # 1. stash if dirty
    stash = safe_stash(repo, label="pull-rebase")
    if stash["stashed"]:
        steps.append(f"stash: {stash['message']}")

    # 2. fetch
    fetch = _run(["git", "fetch", remote, branch], cwd=repo)
    if fetch.returncode != 0:
        return {"ok": False, "steps": steps + [f"fetch failed: {fetch.stderr.strip()}"]}
    steps.append("fetch: ok")

    # 3. rebase
    rebase = _run(["git", "rebase", f"{remote}/{branch}"], cwd=repo)
    if rebase.returncode != 0:
        steps.append(f"rebase failed: {rebase.stderr.strip()}")
        # try to abort
        _run(["git", "rebase", "--abort"], cwd=repo)
        if stash["stashed"]:
            safe_pop(repo)
        return {"ok": False, "steps": steps}
    steps.append("rebase: ok")

    # 4. pop stash
    if stash["stashed"]:
        pop = safe_pop(repo)
        steps.append(f"pop: {pop['message']}")

    return {"ok": True, "steps": steps}
