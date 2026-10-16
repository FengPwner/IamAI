"""Stroke tide — is the repo expanding or contracting?

A self-writing repository does not only grow.  Caretaker visits prune
stale notes, compaction merges duplicate strokes, and occasionally a
bad module gets deleted outright.  The *net* direction — additions minus
deletions — tells you whether the repo is in an **expansion** phase
(writer producing new content faster than the caretaker prunes) or a
**contraction** phase (more being removed than added).

This module measures that direction by reading ``git log --numstat``
over a rolling window of recent commits and computing:

- **added**: total lines added in the window
- **deleted**: total lines deleted in the window
- **net**: added − deleted (positive = expansion)
- **tide**: one of ``expanding``, ``contracting``, or ``flat``
- **magnitude**: abs(net) — how strongly the tide is pulling

Verdict thresholds (applied to ``net``)::

    net ≥  +threshold  →  expanding
    net ≤  −threshold  →  contracting
    otherwise          →  flat

Default ``threshold`` is 50 lines — enough to ignore noise from small
edits but sensitive enough to catch real trends within a 20-commit
window.

Usage::

    from iamai.stroke_tide import tide_report, measure_tide

    info = measure_tide(window=20)
    print(info["tide"])        # "expanding"
    print(info["net"])         # 312
    print(tide_report())
    # "expanding — net +312 lines over 20 commits (added 1840, deleted 1528)"

Design choices:

- Uses ``git log --numstat`` which is fast and available in every repo.
- Binary files (images, etc.) show as ``-`` in numstat and are skipped.
- Merge commits are included to avoid blind spots.
- Returns ``flat`` when no commits exist in the window.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent

# Default minimum |net| to declare a direction rather than noise.
DEFAULT_THRESHOLD = 50


def measure_tide(
    root: Optional[Path | str] = None,
    window: int = 20,
    threshold: int = DEFAULT_THRESHOLD,
) -> dict:
    """Measure the expansion/contraction tide over recent commits.

    Parameters
    ----------
    root : Path or str, optional
        Repository root.  Defaults to the IamAI repo.
    window : int
        Number of recent commits to analyse.  Default 20.
    threshold : int
        Minimum absolute net change to declare expanding/contracting.

    Returns
    -------
    dict
        Keys: ``added``, ``deleted``, ``net``, ``tide``, ``magnitude``,
        ``commits_analysed``.
    """
    if root is None:
        root = REPO_ROOT
    root = Path(root)

    added = 0
    deleted = 0
    commits_analysed = 0

    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--max-count={window}",
                "--numstat",
                "--format=%H",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(root),
        )
        if result.returncode != 0:
            return {
                "added": 0, "deleted": 0, "net": 0,
                "tide": "flat", "magnitude": 0,
                "commits_analysed": 0,
            }

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Commit hash lines are 40 hex chars.
            if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
                commits_analysed += 1
                continue
            # Numstat lines: "added\tdeleted\tfilename"
            parts = line.split("\t")
            if len(parts) >= 3:
                a_str, d_str = parts[0], parts[1]
                # Binary files show "-" for both columns.
                if a_str == "-" or d_str == "-":
                    continue
                try:
                    added += int(a_str)
                    deleted += int(d_str)
                except ValueError:
                    continue

    except (subprocess.TimeoutExpired, OSError):
        return {
            "added": 0, "deleted": 0, "net": 0,
            "tide": "flat", "magnitude": 0,
            "commits_analysed": 0,
        }

    net = added - deleted
    magnitude = abs(net)

    if net >= threshold:
        tide = "expanding"
    elif net <= -threshold:
        tide = "contracting"
    else:
        tide = "flat"

    return {
        "added": added,
        "deleted": deleted,
        "net": net,
        "tide": tide,
        "magnitude": magnitude,
        "commits_analysed": commits_analysed,
    }


def tide_report(
    root: Optional[Path | str] = None,
    window: int = 20,
    threshold: int = DEFAULT_THRESHOLD,
) -> str:
    """One-liner for caretaker status reports.

    Example::

        "expanding — net +312 lines over 20 commits (added 1840, deleted 1528)"
    """
    info = measure_tide(root=root, window=window, threshold=threshold)

    if info["commits_analysed"] == 0:
        return "no commits to analyse"

    sign = "+" if info["net"] >= 0 else ""
    return (
        f"{info['tide']} — net {sign}{info['net']} lines "
        f"over {info['commits_analysed']} commits "
        f"(added {info['added']}, deleted {info['deleted']})"
    )
