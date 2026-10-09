"""Push preflight — run every pre-push check in one call.

Push failures in this repo fall into three buckets:

1. **Stale index.lock** — a crashed git process left a lock file behind,
   blocking ``git commit`` and ``git push`` alike.
2. **Remote divergence** — another writer pushed since our last fetch,
   so ``git push`` is rejected with ``[rejected] (fetch first)``.
3. **Uncommitted work** — files are modified but not staged, so a push
   would leave the working tree in an ambiguous state.

Each of these has its own detector module. This module composes them
into a single checklist that the batch committer can run before
attempting a push. The result is a structured report:

    {
        "ok": False,
        "checks": [
            {"name": "index_lock",  "ok": True,  "detail": "no lock"},
            {"name": "divergence",  "ok": False, "detail": "behind 3, fetch+rebase needed"},
            {"name": "dirty_tree",  "ok": True,  "detail": "clean"},
        ],
        "blockers": ["divergence"],
        "summary": "1 blocker: divergence (behind 3, fetch+rebase needed)",
    }

Design choices:

- Each check is independent: one failure does not skip the others.
  You want to see *all* problems at once, not fix them one at a time.
- ``index_lock`` is checked first because it blocks everything else,
  including the git commands that divergence and dirty-tree checks need.
- Divergence check calls ``git fetch`` before comparing refs. If fetch
  fails (offline, network timeout), the check reports "fetch failed"
  as a warning rather than claiming the remote is up to date.
- Dirty-tree check uses ``git status --porcelain`` rather than
  ``git diff`` because porcelain is stable and parseable.

Usage::

    from iamai.push_preflight import preflight

    result = preflight("/path/to/IamAI")
    if result["ok"]:
        # safe to commit and push
    else:
        for name in result["blockers"]:
            # fix each blocker
        # retry preflight after fixes
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .index_lock_detector import detect_lock
from .git_divergence import divergence


def _run(repo: Path, *args: str) -> tuple[int, str]:
    """Run a git command, return (exit_code, stdout)."""
    try:
        proc = subprocess.run(
            ["git"] + list(args),
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def check_index_lock(repo: Path) -> dict[str, Any]:
    """Check for stale .git/index.lock."""
    info = detect_lock(repo)
    if not info["locked"]:
        return {"name": "index_lock", "ok": True, "detail": "no lock"}

    if info["stale"]:
        return {
            "name": "index_lock",
            "ok": False,
            "detail": f"stale lock (age {info['age_seconds']:.0f}s, no holder) — remove it",
        }

    return {
        "name": "index_lock",
        "ok": False,
        "detail": f"active lock (age {info['age_seconds']:.0f}s, holder pid {info['holder_pid']})",
    }


def check_divergence(repo: Path) -> dict[str, Any]:
    """Check whether remote has diverged from local."""
    try:
        d = divergence(str(repo))
    except Exception as exc:
        return {
            "name": "divergence",
            "ok": False,
            "detail": f"check failed: {exc}",
        }

    behind = d.get("behind", 0)
    ahead = d.get("ahead", 0)

    if behind > 0:
        return {
            "name": "divergence",
            "ok": False,
            "detail": f"behind {behind}, fetch+rebase needed",
        }

    if ahead == 0:
        return {
            "name": "divergence",
            "ok": True,
            "detail": "up to date, nothing to push",
        }

    return {
        "name": "divergence",
        "ok": True,
        "detail": f"ahead {ahead}, safe to push",
    }


def check_dirty_tree(repo: Path) -> dict[str, Any]:
    """Check whether the working tree has uncommitted changes."""
    code, out = _run(repo, "status", "--porcelain")
    if code != 0:
        return {
            "name": "dirty_tree",
            "ok": False,
            "detail": f"git status failed: {out}",
        }

    if not out:
        return {"name": "dirty_tree", "ok": True, "detail": "clean"}

    lines = [line for line in out.split("\n") if line.strip()]
    count = len(lines)
    return {
        "name": "dirty_tree",
        "ok": False,
        "detail": f"{count} uncommitted file(s)",
    }


def preflight(repo: Path | str) -> dict[str, Any]:
    """Run all pre-push checks and return a structured report.

    Parameters
    ----------
    repo : Path or str
        Root of the git repository.

    Returns
    -------
    dict with keys: ok, checks, blockers, summary
    """
    repo = Path(repo)
    checks = [
        check_index_lock(repo),
        check_divergence(repo),
        check_dirty_tree(repo),
    ]

    blockers = [c["name"] for c in checks if not c["ok"]]
    ok = len(blockers) == 0

    if ok:
        summary = "all checks passed — safe to push"
    else:
        parts = []
        for c in checks:
            if not c["ok"]:
                parts.append(f"{c['name']} ({c['detail']})")
        summary = f"{len(blockers)} blocker(s): " + ", ".join(parts)

    return {
        "ok": ok,
        "checks": checks,
        "blockers": blockers,
        "summary": summary,
    }


def preflight_report(repo: Path | str) -> str:
    """One-line summary for caretaker logs."""
    result = preflight(repo)
    return result["summary"]
