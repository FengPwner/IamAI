"""Commit longevity — how long do file changes survive before being overwritten?

Most observability modules in this repo measure *output*: how many strokes,
how steady the cadence, how diverse the content.  ``commit_longevity``
measures *durability*: once a file is written, how long does it stay in
its committed state before the next commit touches it again?

This matters because a self-writing repo that constantly rewrites the same
files is churning, not growing.  A high churn rate means the writer is
editing its own edits — sometimes intentionally (iteration), sometimes
not (template loops rewriting ``notes/history.md`` every stroke).

Model
-----

For each file ``f`` that appears in the last *N* commits, record the
earliest appearance and the latest modification.  Longevity is::

    longevity(f) = last_modified(f) - first_committed(f)

Then classify the repo as a whole:

==============  ========================================================
verdict         meaning
==============  ========================================================
durable         median longevity > 3600 s  (files survive >1 hour)
transient       600 s < median ≤ 3600 s   (files change within an hour)
churning        median ≤ 600 s            (files rewritten every commit)
==============  ========================================================

Usage::

    from iamai.commit_longevity import commit_longevity, longevity_report

    info = commit_longevity(repo, count=30)
    print(info["median_longevity_s"])   # e.g. 4200
    print(info["churn_files"])           # files rewritten every commit
    print(info["verdict"])              # "durable"

    print(longevity_report(repo))
    # "durable — median file survives 4200s, 2 churning files"

Design choices:
  - Uses ``git log --name-status`` to enumerate changed files per commit.
  - Only considers commits in the observation window (default 30).
  - Files that appear only once are excluded (no longevity to measure).
  - Pure subprocess wrapper; no git library dependency.
"""

from __future__ import annotations

import subprocess
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional


# Thresholds (seconds)
DURABLE_THRESHOLD = 3600    # >1 hour → durable
TRANSIENT_THRESHOLD = 600   # >10 minutes → transient; ≤10 min → churning


def _parse_log(repo: Path, count: int = 30) -> List[dict]:
    """Parse ``git log --name-status`` into per-commit records.

    Returns a list of dicts (newest first) with keys:
      - ``sha``: short hash
      - ``timestamp``: epoch seconds
      - ``files``: list of changed file paths
    """
    try:
        out = subprocess.check_output(
            [
                "git", "log", f"-{count}",
                "--format=COMMIT:%h %at",
                "--name-status",
            ],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace").strip()
    except subprocess.CalledProcessError:
        return []

    commits: List[dict] = []
    current: Optional[dict] = None

    for line in out.splitlines():
        line = line.rstrip()
        if line.startswith("COMMIT:"):
            if current is not None:
                commits.append(current)
            parts = line[len("COMMIT:"):].split()
            sha = parts[0] if parts else "?"
            ts = int(parts[1]) if len(parts) > 1 else 0
            current = {"sha": sha, "timestamp": ts, "files": []}
        elif current is not None and line.strip():
            # format: "M\tfile" or "A\tfile" etc.
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[1].strip():
                current["files"].append(parts[1].strip())

    if current is not None:
        commits.append(current)

    return commits


def commit_longevity(repo: Path, count: int = 30) -> Dict[str, Any]:
    """Measure how long files survive between modifications.

    Parameters
    ----------
    repo : Path
        Path to the git repository root.
    count : int
        Number of recent commits to examine (default 30).

    Returns
    -------
    dict with keys:
      - ``commits``: number of commits examined
      - ``file_lifetimes``: dict mapping file path → seconds between
        first and last appearance in the window
      - ``median_longevity_s``: median lifetime across files (0 if none)
      - ``max_longevity_s``: longest-lived file
      - ``churn_files``: list of files modified in >80% of commits
        they appear in (i.e. rewritten almost every time)
      - ``verdict``: ``"durable"``, ``"transient"``, or ``"churning"``
    """
    commits = _parse_log(repo, count)
    if not commits:
        return {
            "commits": 0,
            "file_lifetimes": {},
            "median_longevity_s": 0,
            "max_longevity_s": 0,
            "churn_files": [],
            "verdict": "churning",
        }

    # Collect first-seen and last-seen timestamps per file
    file_first: Dict[str, int] = {}
    file_last: Dict[str, int] = {}
    file_commit_count: Dict[str, int] = {}

    for c in commits:
        ts = c["timestamp"]
        for f in c["files"]:
            if f not in file_first or ts < file_first[f]:
                file_first[f] = ts
            if f not in file_last or ts > file_last[f]:
                file_last[f] = ts
            file_commit_count[f] = file_commit_count.get(f, 0) + 1

    # Lifetime = last_seen - first_seen (files appearing once → 0, excluded)
    lifetimes: Dict[str, int] = {}
    for f in file_first:
        span = file_last[f] - file_first[f]
        if span > 0:
            lifetimes[f] = span

    values = list(lifetimes.values())
    median_s = int(statistics.median(values)) if values else 0
    max_s = max(values) if values else 0

    # Churn: files that appear in many commits relative to the window
    total_commits = len(commits)
    churn_files = sorted(
        f for f, n in file_commit_count.items()
        if n >= total_commits * 0.5 and n >= 3
    )

    # Verdict
    if median_s > DURABLE_THRESHOLD:
        verdict = "durable"
    elif median_s > TRANSIENT_THRESHOLD:
        verdict = "transient"
    else:
        verdict = "churning"

    return {
        "commits": total_commits,
        "file_lifetimes": lifetimes,
        "median_longevity_s": median_s,
        "max_longevity_s": max_s,
        "churn_files": churn_files,
        "verdict": verdict,
    }


def longevity_report(repo: Path, count: int = 30) -> str:
    """One-liner summary suitable for caretaker logs.

    Returns a string like::

        durable — median file survives 4200s, 2 churning files (30 commits)
    """
    info = commit_longevity(repo, count)
    n_churn = len(info["churn_files"])
    churn_note = f"{n_churn} churning file{'s' if n_churn != 1 else ''}"
    return (
        f"{info['verdict']} — median file survives {info['median_longevity_s']}s, "
        f"{churn_note} ({info['commits']} commits)"
    )
