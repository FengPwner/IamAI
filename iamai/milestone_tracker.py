"""Milestone tracker — detect when the repo crosses numeric thresholds.

Caretakers often note round numbers in visit logs ("stroke 400", "675 files",
"1377 commits") but there's no systematic way to detect them. This module
answers one question: *has the repo crossed any milestones since the last check?*

A milestone is a (metric, threshold) pair. When the current value meets or
exceeds the threshold and the previous value (from the last check) was below
it, the milestone is "crossed". The tracker stores the last-seen values in
``data/milestone_state.json`` so it can detect crossings across restarts.

Metrics tracked:

- **strokes** — total stroke count from ``data/strokes.jsonl``
- **files** — tracked file count from ``git ls-files``
- **commits** — total commit count from ``git rev-list``
- **lines** — total line count across tracked files

Usage::

    from iamai.milestone_tracker import (
        check_milestones,
        milestone_summary,
        default_thresholds,
    )

    crossed = check_milestones(repo)
    for m in crossed:
        print(f"{m['metric']} crossed {m['threshold']} (now {m['value']})")

    print(milestone_summary(repo))
    # "milestones: strokes crossed 17000 (now 17023), files crossed 680 (now 683)"
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent

# Default milestone thresholds for this repo.
# Each key is a metric name; each value is a sorted list of thresholds.
_DEFAULT_THRESHOLDS: Dict[str, List[int]] = {
    "strokes": [100, 200, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 3000, 5000, 10000],
    "files": [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
    "commits": [100, 200, 500, 1000, 1500, 2000, 2500, 3000],
    "lines": [10000, 25000, 50000, 75000, 100000, 125000, 150000, 200000],
}


def default_thresholds() -> Dict[str, List[int]]:
    """Return a copy of the default milestone thresholds."""
    return {k: list(v) for k, v in _DEFAULT_THRESHOLDS.items()}


def _state_path(repo: Optional[Path] = None) -> Path:
    root = Path(repo) if repo else REPO_ROOT
    return root / "data" / "milestone_state.json"


def _load_state(repo: Optional[Path] = None) -> Dict[str, int]:
    path = _state_path(repo)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: Dict[str, int], repo: Optional[Path] = None) -> None:
    path = _state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def _measure(metric: str, repo: Optional[Path] = None) -> int:
    """Measure the current value of a metric."""
    root = Path(repo) if repo else REPO_ROOT

    if metric == "strokes":
        strokes_path = root / "data" / "strokes.jsonl"
        if not strokes_path.exists():
            return 0
        count = 0
        with open(strokes_path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    elif metric == "files":
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                capture_output=True, text=True, cwd=str(root),
                timeout=30,
            )
            if result.returncode != 0:
                return 0
            return len([l for l in result.stdout.strip().split("\n") if l])
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0

    elif metric == "commits":
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, cwd=str(root),
                timeout=30,
            )
            if result.returncode != 0:
                return 0
            return int(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return 0

    elif metric == "lines":
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                capture_output=True, text=True, cwd=str(root),
                timeout=30,
            )
            if result.returncode != 0:
                return 0
            files = [l for l in result.stdout.strip().split("\n") if l]
            total = 0
            for filepath in files:
                full = root / filepath
                if full.is_file():
                    try:
                        with open(full, errors="ignore") as fh:
                            total += sum(1 for _ in fh)
                    except OSError:
                        pass
            return total
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return 0

    return 0


def check_milestones(
    repo: Optional[Path] = None,
    thresholds: Optional[Dict[str, List[int]]] = None,
    update_state: bool = True,
) -> List[Dict[str, Any]]:
    """Check which milestones have been crossed since the last check.

    Returns a list of dicts, each with keys:
    - ``metric`` — the metric name (e.g. "strokes")
    - ``threshold`` — the threshold value that was crossed
    - ``value`` — the current measured value
    - ``previous`` — the value at the last check

    If ``update_state`` is True (default), saves the current values so the
    next call only reports *new* crossings.
    """
    if thresholds is None:
        thresholds = default_thresholds()

    state = _load_state(repo)
    crossed: List[Dict[str, Any]] = []

    for metric, levels in thresholds.items():
        current = _measure(metric, repo)
        previous = state.get(metric, 0)

        for level in sorted(levels):
            if previous < level <= current:
                crossed.append({
                    "metric": metric,
                    "threshold": level,
                    "value": current,
                    "previous": previous,
                })

        if update_state:
            state[metric] = current

    if update_state:
        _save_state(state, repo)

    return crossed


def milestone_summary(
    repo: Optional[Path] = None,
    thresholds: Optional[Dict[str, List[int]]] = None,
) -> str:
    """One-line summary of milestone crossings for caretaker logs.

    Returns a string like:
    "milestones: strokes crossed 500 (now 523), files crossed 700 (now 712)"
    or "milestones: none crossed" if nothing new.
    """
    crossed = check_milestones(repo, thresholds)
    if not crossed:
        return "milestones: none crossed"

    parts = []
    for m in crossed:
        parts.append(f"{m['metric']} crossed {m['threshold']} (now {m['value']})")
    return "milestones: " + ", ".join(parts)
