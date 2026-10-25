"""Commit dispersion — how scattered are file changes per commit?

A focused commit touches one area: a new module, a test file, a doc.
A scattered commit touches twenty files across the tree.  Both are
valid, but knowing which is which helps the caretaker decide whether
the writer is *working* or *thrashing*.

This module reads recent commits via ``git log --numstat`` and reports:

* ``files_per_commit``  — list of ints, files touched per commit
* ``median_files``      — median file count
* ``max_files``         — worst single commit
* ``dirs_per_commit``   — list of ints, distinct top-level dirs per commit
* ``median_dirs``       — median dir count
* ``dispersion``        — float 0–1 (normalised entropy across dirs)
* ``focus``             — str: ``"focused"``, ``"moderate"``, or ``"scattered"``

Focus thresholds::

    median_files ≤ 3   →  focused
    median_files ≤ 10  →  moderate
    median_files > 10  →  scattered

Usage::

    from iamai.commit_dispersion import commit_dispersion, dispersion_report

    info = commit_dispersion(repo, count=20)
    print(info["median_files"])   # 3
    print(info["focus"])          # "focused"

    print(dispersion_report(repo))
    # "focused — median 3 files across 1 dir per commit (20 commits)"
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path


def _parse_numstat(repo: Path, count: int = 20) -> list[dict]:
    """Parse ``git log --numstat`` into per-commit file lists.

    Returns a list of dicts, each with keys ``sha`` (short) and
    ``files`` (list of changed file paths).  Newest commit first.
    """
    try:
        out = subprocess.check_output(
            ["git", "log", f"-{count}", "--format=COMMIT:%h", "--numstat"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
    except subprocess.CalledProcessError:
        return []

    commits: list[dict] = []
    current: dict | None = None

    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("COMMIT:"):
            if current is not None:
                commits.append(current)
            current = {"sha": line[len("COMMIT:"):], "files": []}
        elif current is not None and "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 3:
                # parts: added, deleted, filepath
                # binary files show "-" for added/deleted — keep the path
                filepath = parts[2]
                # rename syntax: "old => new" or "{old => new}/path"
                if " => " in filepath:
                    filepath = filepath.split(" => ")[-1].rstrip("}")
                    if "{" in filepath:
                        filepath = filepath.split("{")[0] + filepath.split("}")[
                            -1
                        ]
                current["files"].append(filepath)

    if current is not None:
        commits.append(current)
    return commits


def _top_dirs(paths: list[str]) -> set[str]:
    """Extract unique top-level directory names from file paths."""
    dirs: set[str] = set()
    for p in paths:
        parts = Path(p).parts
        if len(parts) > 1:
            dirs.add(parts[0])
        else:
            dirs.add("(root)")
    return dirs


def _entropy(values: list[int]) -> float:
    """Shannon entropy of a list of non-negative ints, normalised to 0–1."""
    total = sum(values)
    if total == 0:
        return 0.0
    probs = [v / total for v in values if v > 0]
    if len(probs) <= 1:
        return 0.0
    raw = -sum(p * math.log2(p) for p in probs)
    max_entropy = math.log2(len(probs))
    return raw / max_entropy if max_entropy > 0 else 0.0


def _median(values: list[int]) -> int:
    """Integer median of a list."""
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


def commit_dispersion(
    repo: Path,
    count: int = 20,
) -> dict:
    """Measure file dispersion across the last *count* commits.

    Parameters
    ----------
    repo:
        Repository root.
    count:
        How many commits to inspect (default 20).

    Returns
    -------
    dict with keys:
        ``files_per_commit``, ``median_files``, ``max_files``,
        ``dirs_per_commit``, ``median_dirs``, ``dispersion``,
        ``focus``, ``commits_inspected``.
    """
    commits = _parse_numstat(repo, count=count)
    if not commits:
        return {
            "files_per_commit": [],
            "median_files": 0,
            "max_files": 0,
            "dirs_per_commit": [],
            "median_dirs": 0,
            "dispersion": 0.0,
            "focus": "unknown",
            "commits_inspected": 0,
        }

    files_per = [len(c["files"]) for c in commits]
    dirs_per = [len(_top_dirs(c["files"])) for c in commits]

    # Dispersion: entropy of file counts across commits
    disp = round(_entropy(files_per), 3)

    med_f = _median(files_per)
    if med_f <= 3:
        focus = "focused"
    elif med_f <= 10:
        focus = "moderate"
    else:
        focus = "scattered"

    return {
        "files_per_commit": files_per,
        "median_files": med_f,
        "max_files": max(files_per) if files_per else 0,
        "dirs_per_commit": dirs_per,
        "median_dirs": _median(dirs_per),
        "dispersion": disp,
        "focus": focus,
        "commits_inspected": len(commits),
    }


def dispersion_report(repo: Path, count: int = 20) -> str:
    """One-line human-readable dispersion summary."""
    info = commit_dispersion(repo, count=count)
    if info["commits_inspected"] == 0:
        return "no commits found"
    return (
        f"{info['focus']} — median {info['median_files']} files "
        f"across {info['median_dirs']} dir(s) per commit "
        f"({info['commits_inspected']} commits, "
        f"dispersion {info['dispersion']})"
    )
