"""Git index health diagnostics — detect locks, corruption, and stale refs.

When a git process crashes mid-commit it leaves behind:

1. ``.git/index.lock`` — blocks all subsequent git operations.
2. A truncated or zero-byte ``.git/index`` — makes ``git status`` fail.
3. Stale refs in ``.git/refs/`` that disagree with packed-refs.

``commit_guard`` and ``index_lock_detector`` already cover *some* of
these, but they focus on pre-commit timing.  This module is the
post-mortem toolkit: call it from a caretaker visit or a recovery
script to decide *what to do* when git is broken.

Functions
---------
check_lock(repo)
    Return whether ``.git/index.lock`` exists and how old it is.
check_index(repo)
    Return whether ``.git/index`` is readable and non-empty.
check_refs(repo)
    Return loose-ref / packed-ref inconsistencies.
diagnose(repo)
    Run all checks and return a verdict: ``healthy``, ``degraded``,
    or ``broken``, plus a list of recommended repair actions.
repair(repo, dry_run=True)
    Execute (or preview) the recommended repairs.

Usage::

    from iamai.git_index_health import diagnose, repair

    result = diagnose(repo)
    print(result["verdict"])  # "broken"
    print(result["issues"])   # ["stale_lock", "empty_index"]

    repair(repo, dry_run=False)  # actually fix things

"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------

def check_lock(repo: str | Path) -> dict[str, Any]:
    """Check for a stale ``.git/index.lock``.

    Returns a dict with keys ``exists`` (bool), ``age_seconds`` (float
    or None), and ``stale`` (bool — True if older than 300 s).
    """
    lock = Path(repo) / ".git" / "index.lock"
    if not lock.exists():
        return {"exists": False, "age_seconds": None, "stale": False}
    age = time.time() - lock.stat().st_mtime
    return {"exists": True, "age_seconds": round(age, 1), "stale": age > 300}


def check_index(repo: str | Path) -> dict[str, Any]:
    """Check whether ``.git/index`` is present and non-empty.

    Returns ``exists``, ``size_bytes``, and ``readable``.
    """
    idx = Path(repo) / ".git" / "index"
    if not idx.exists():
        return {"exists": False, "size_bytes": 0, "readable": False}
    size = idx.stat().st_size
    readable = size > 0
    return {"exists": True, "size_bytes": size, "readable": readable}


def check_refs(repo: str | Path) -> dict[str, Any]:
    """Detect loose refs that disagree with ``packed-refs``.

    We only flag *conflicts* — where both a loose ref and a packed ref
    exist for the same name but point to different SHAs.  Having both
    is normal after ``git pack-refs``; conflicting SHAs are not.

    Returns ``conflicts`` (list of ref names) and ``loose_count``.
    """
    git_dir = Path(repo) / ".git"
    refs_root = git_dir / "refs"
    packed = git_dir / "packed-refs"

    # read packed-refs into a dict
    packed_shas: dict[str, str] = {}
    if packed.exists():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                packed_shas[parts[1]] = parts[0]

    # walk loose refs
    loose_shas: dict[str, str] = {}
    if refs_root.exists():
        for ref_path in refs_root.rglob("*"):
            if ref_path.is_file():
                ref_name = str(ref_path.relative_to(git_dir))
                sha = ref_path.read_text(encoding="utf-8").strip()
                loose_shas[ref_name] = sha

    conflicts = [
        name
        for name, sha in loose_shas.items()
        if name in packed_shas and packed_shas[name] != sha
    ]

    return {
        "loose_count": len(loose_shas),
        "packed_count": len(packed_shas),
        "conflicts": sorted(conflicts),
    }


# ---------------------------------------------------------------------------
# composite diagnosis
# ---------------------------------------------------------------------------

_ISSUE_LABELS = {
    "stale_lock": "remove stale .git/index.lock",
    "missing_index": "rebuild index via git read-tree HEAD",
    "empty_index": "rebuild index via git read-tree HEAD",
    "ref_conflict": "prune conflicting loose refs",
}


def diagnose(repo: str | Path) -> dict[str, Any]:
    """Run all health checks and return a structured diagnosis.

    Keys: ``verdict`` (healthy / degraded / broken), ``issues`` (list
    of issue labels), ``checks`` (raw check results), ``repairs``
    (human-readable repair suggestions).
    """
    lock = check_lock(repo)
    index = check_index(repo)
    refs = check_refs(repo)

    issues: list[str] = []

    if lock["exists"] and lock["stale"]:
        issues.append("stale_lock")
    if not index["exists"]:
        issues.append("missing_index")
    elif not index["readable"]:
        issues.append("empty_index")
    if refs["conflicts"]:
        issues.append("ref_conflict")

    if not issues:
        verdict = "healthy"
    elif "missing_index" in issues or "empty_index" in issues:
        verdict = "broken"
    else:
        verdict = "degraded"

    repairs = [_ISSUE_LABELS[i] for i in issues if i in _ISSUE_LABELS]

    return {
        "verdict": verdict,
        "issues": issues,
        "checks": {"lock": lock, "index": index, "refs": refs},
        "repairs": repairs,
    }


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------

def repair(repo: str | Path, dry_run: bool = True) -> list[str]:
    """Execute (or preview) repairs for detected issues.

    Returns a list of actions taken (or that would be taken).
    Does NOT run git commands — it only does safe filesystem ops:

    - remove stale ``index.lock``
    - remove conflicting loose ref files

    Index rebuild is reported but not performed (it requires running
    ``git read-tree`` which the caller should do themselves).
    """
    diag = diagnose(repo)
    actions: list[str] = []
    git_dir = Path(repo) / ".git"

    if "stale_lock" in diag["issues"]:
        lock = git_dir / "index.lock"
        if dry_run:
            actions.append(f"[dry-run] would remove {lock}")
        else:
            lock.unlink(missing_ok=True)
            actions.append(f"removed {lock}")

    if "ref_conflict" in diag["issues"]:
        conflicts = diag["checks"]["refs"]["conflicts"]
        for ref_name in conflicts:
            ref_path = git_dir / ref_name
            if dry_run:
                actions.append(f"[dry-run] would remove conflicting loose ref {ref_path}")
            else:
                ref_path.unlink(missing_ok=True)
                actions.append(f"removed conflicting loose ref {ref_path}")

    if "missing_index" in diag["issues"] or "empty_index" in diag["issues"]:
        actions.append("index needs rebuild: run `git read-tree HEAD && git checkout-index -a`")

    return actions
