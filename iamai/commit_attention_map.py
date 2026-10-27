"""commit_attention_map — classify what the repo is paying attention to.

Every commit touches files, and every file belongs to a *category*.
By mapping recent commits to the categories they touch, we can see
whether the repo is in a focused build phase, a scattered maintenance
phase, or something in between.

file categories
~~~~~~~~~~~~~~~

==============  =====================================================
category        what it covers
==============  =====================================================
``code``        .py files in ``iamai/``
``tests``       files matching ``test_*.py`` or in ``tests/``
``tools``       scripts in ``tools/``
``docs``        .md files in ``docs/`` or ``notes/``
``data``        files in ``data/``
``config``      CI files, config files, ``__init__.py``
``meta``        everything else
==============  =====================================================

focus bands
~~~~~~~~~~~

==============  ===========  ================================================
band            entropy      meaning
==============  ===========  ================================================
``tunnel``      0.00 – 0.30  nearly all commits touch one category
``focused``     0.30 – 0.55  clear primary focus with minor scatter
``balanced``    0.55 – 0.80  healthy spread across categories
``scattered``   0.80 – 1.00  attention fragmented; possible maintenance mode
==============  ===========  ================================================

The entropy is computed over the *category distribution* (not tokens),
normalised by the number of categories actually present.

public api
~~~~~~~~~~

- ``classify_file(path)``           — map a file path to its category
- ``attention_distribution(files)`` — count files per category
- ``focus_entropy(dist)``           — normalised Shannon entropy of dist
- ``classify_focus(h)``             — map entropy to a focus band
- ``analyse_attention(file_lists)`` — full pipeline from commits to report
- ``attention_report(file_lists)``  — one-call convenience wrapper
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Dict, List, Sequence


# ---------------------------------------------------------------------------
# file classification
# ---------------------------------------------------------------------------


def classify_file(path: str) -> str:
    """Map a relative file path to an attention category.

    >>> classify_file("iamai/commit_entropy.py")
    'code'
    >>> classify_file("tests/test_file_fatigue.py")
    'tests'
    >>> classify_file("tools/run_both.sh")
    'tools'
    >>> classify_file("docs/DEVLOG.md")
    'docs'
    >>> classify_file("notes/conventions.md")
    'docs'
    >>> classify_file("data/strokes.jsonl")
    'data'
    >>> classify_file(".github/workflows/ci.yml")
    'config'
    >>> classify_file("README.md")
    'docs'
    >>> classify_file("random_file.txt")
    'meta'
    """
    p = PurePosixPath(path)
    parts = p.parts
    name = p.name

    # Tests: test_*.py files or files under tests/
    if name.startswith("test_") and name.endswith(".py"):
        return "tests"
    if parts and parts[0] == "tests":
        return "tests"

    # Code: .py files in iamai/
    if parts and parts[0] == "iamai" and name.endswith(".py"):
        if name != "__init__.py":
            return "code"

    # Tools: scripts in tools/
    if parts and parts[0] == "tools":
        return "tools"

    # Docs: .md files in docs/, notes/, or repo root
    if name.endswith(".md"):
        return "docs"

    # Data: files in data/
    if parts and parts[0] == "data":
        return "data"

    # Config: CI, config files, __init__.py
    if parts and parts[0] in (".github", ".git"):
        return "config"
    if name in (
        "__init__.py",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        ".gitignore",
        "Makefile",
        "requirements.txt",
    ):
        return "config"

    return "meta"


# ---------------------------------------------------------------------------
# attention distribution
# ---------------------------------------------------------------------------


def attention_distribution(
    files: Sequence[str],
) -> Dict[str, int]:
    """Count how many files fall into each attention category.

    >>> attention_distribution(["iamai/a.py", "tests/test_a.py", "docs/X.md"])
    {'code': 1, 'tests': 1, 'docs': 1}
    """
    counts: Counter = Counter()
    for f in files:
        counts[classify_file(f)] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# focus entropy
# ---------------------------------------------------------------------------


def focus_entropy(dist: Dict[str, int]) -> float:
    """Compute normalised Shannon entropy of a category distribution.

    Returns 0.0 when there is only one category (maximum focus).
    Returns 1.0 when all categories are equally represented.

    >>> focus_entropy({"code": 10})
    0.0
    >>> abs(focus_entropy({"code": 5, "tests": 5}) - 1.0) < 1e-9
    True
    """
    total = sum(dist.values())
    if total == 0:
        return 0.0
    k = len(dist)
    if k <= 1:
        return 0.0

    raw = 0.0
    for count in dist.values():
        p = count / total
        if p > 0:
            raw -= p * math.log2(p)

    max_h = math.log2(k)
    if max_h == 0:
        return 0.0
    return min(raw / max_h, 1.0)


# ---------------------------------------------------------------------------
# focus band classification
# ---------------------------------------------------------------------------

_FOCUS_BANDS = [
    ("tunnel",    0.00, 0.30),
    ("focused",   0.30, 0.55),
    ("balanced",  0.55, 0.80),
    ("scattered", 0.80, 1.01),
]


def classify_focus(h: float) -> str:
    """Map a normalised entropy value to a focus band.

    >>> classify_focus(0.0)
    'tunnel'
    >>> classify_focus(0.4)
    'focused'
    >>> classify_focus(0.7)
    'balanced'
    >>> classify_focus(0.9)
    'scattered'
    >>> classify_focus(1.0)
    'scattered'
    """
    for band, lo, hi in _FOCUS_BANDS:
        if lo <= h < hi:
            return band
    return "scattered"


# ---------------------------------------------------------------------------
# commit-level analysis
# ---------------------------------------------------------------------------


def analyse_attention(
    file_lists: List[List[str]],
    window: int = 20,
) -> Dict[str, Any]:
    """Analyse attention across the most recent *window* commits.

    Each element of ``file_lists`` is the list of files touched by one
    commit (newest first, as from ``git log --name-only``).

    Returns a dict with:

    - ``focus``          — normalised entropy [0, 1]
    - ``band``           — focus band name
    - ``distribution``   — merged category counts across all commits
    - ``per_commit``      — per-commit category breakdown
    - ``dominant``        — the category with the highest share
    - ``dominant_share``  — percentage of files in the dominant category
    - ``sample_size``     — number of commits actually analysed
    - ``summary``         — human-readable one-liner
    """
    recent = file_lists[:window]
    merged: Counter = Counter()
    per_commit: List[Dict[str, int]] = []

    for fl in recent:
        dist = attention_distribution(fl)
        for cat, count in dist.items():
            merged[cat] += count
        per_commit.append(dist)

    merged_dict = dict(merged)
    h = focus_entropy(merged_dict)
    band = classify_focus(h)

    total_files = sum(merged.values())
    if total_files == 0:
        dominant, dominant_share = "none", 0.0
    else:
        dominant = max(merged, key=merged.get)
        dominant_share = round(merged[dominant] / total_files * 100, 1)

    return {
        "focus": round(h, 4),
        "band": band,
        "distribution": merged_dict,
        "per_commit": per_commit,
        "dominant": dominant,
        "dominant_share": dominant_share,
        "sample_size": len(recent),
        "summary": (
            f"{len(recent)} commits, {total_files} files: "
            f"{dominant} leads at {dominant_share}%, "
            f"entropy {h:.3f} ({band})"
        ),
    }


# ---------------------------------------------------------------------------
# convenience wrapper
# ---------------------------------------------------------------------------


def attention_report(
    file_lists: List[List[str]],
    window: int = 20,
) -> Dict[str, Any]:
    """One-call convenience wrapper: analyse and return full report.

    Identical to ``analyse_attention`` but includes a
    ``recommendation`` field suggesting corrective action.
    """
    result = analyse_attention(file_lists, window=window)

    recommendations = {
        "tunnel": (
            "all attention on one area — consider whether tests or docs "
            "are being neglected"
        ),
        "focused": (
            "clear primary focus with minor scatter — healthy build phase"
        ),
        "balanced": (
            "attention spread across multiple areas — sustainable pace"
        ),
        "scattered": (
            "attention fragmented across many categories — "
            "possible maintenance mode or context thrashing"
        ),
    }

    result["recommendation"] = recommendations.get(result["band"], "")
    return result
