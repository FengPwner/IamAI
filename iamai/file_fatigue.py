"""file_fatigue — detect files that are being over-edited.

A living repository has a healthy distribution of attention across its
files.  When a single file accumulates a disproportionate share of
edits, it signals *fatigue*: technical debt, a missing abstraction, or
a configuration file doing too much work.

The fatigue metaphor
--------------------

========================  ===================================================
concept                   what it maps to
========================  ===================================================
**edit count**            number of commits that touched a given file
**fatigue score**         normalised edit count relative to the repo median
**fatigue band**          classification of individual file health
**hotspot**               any file in the *exhausted* or *critical* band
**repo fatigue index**    0-100 composite; lower = healthier attention spread
========================  ===================================================

Fatigue bands
-------------

===========  ========  ================================================
band         score     meaning
===========  ========  ================================================
``fresh``    < 1.5     below or near the median — healthy
``warm``     1.5-3.0   above median but not alarming
``hot``      3.0-5.0   noticeably over-edited; review candidate
``exhausted`` 5.0-8.0  severe hotspot; likely missing abstraction
``critical`` >= 8.0    extreme concentration; refactor urgently
===========  ========  ================================================

Repository-level fatigue index
------------------------------

The *repo fatigue index* is computed from the Gini coefficient of the
edit-count distribution, scaled to 0-100.  A perfectly equal repo
scores 0; a repo where one file absorbs all edits scores 100.

============  =======  ================================================
state         index    interpretation
============  =======  ================================================
``balanced``  0-25     attention spread evenly
``skewed``    25-50    some hotspots but manageable
``strained``  50-75    significant concentration
``brittle``   75-100   extreme concentration; single-file fragility
============  =======  ================================================

Usage::

    from iamai.file_fatigue import analyse_fatigue, classify_fatigue

    edits = {"a.py": 10, "b.py": 3, "c.py": 50}
    result = analyse_fatigue(edits)
    print(result["index"])        # 62.3
    print(result["state"])        # "strained"
    print(result["hotspots"])     # [{"file": "c.py", "score": 8.33, ...}]
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------

_BANDS = [
    ("critical", 8.0),
    ("exhausted", 5.0),
    ("hot", 3.0),
    ("warm", 1.5),
]


def classify_fatigue(score: float) -> str:
    """Return the fatigue band for a given score."""
    for band, threshold in _BANDS:
        if score >= threshold:
            return band
    return "fresh"


# ---------------------------------------------------------------------------
# Gini coefficient
# ---------------------------------------------------------------------------


def _gini(values: List[float]) -> float:
    """Compute the Gini coefficient for a list of non-negative values.

    Returns 0.0 for an empty list or a list of all zeros.
    """
    if not values:
        return 0.0
    n = len(values)
    sorted_v = sorted(values)
    total = sum(sorted_v)
    if total == 0:
        return 0.0
    cumulative = 0.0
    weighted_sum = 0.0
    for i, v in enumerate(sorted_v):
        cumulative += v
        weighted_sum += (i + 1) * v
    gini = (2.0 * weighted_sum) / (n * total) - (n + 1) / n
    return max(0.0, min(1.0, gini))


# ---------------------------------------------------------------------------
# Repo-level state
# ---------------------------------------------------------------------------

_STATES = [
    ("brittle", 75),
    ("strained", 50),
    ("skewed", 25),
]


def _classify_repo_state(index: float) -> str:
    """Classify the repo-level fatigue state."""
    for state, threshold in _STATES:
        if index >= threshold:
            return state
    return "balanced"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyse_fatigue(
    edit_counts: Dict[str, int],
    top_n: int = 10,
) -> Dict[str, Any]:
    """Analyse file fatigue from a mapping of {filepath: commit_count}.

    Parameters
    ----------
    edit_counts:
        Mapping of file paths to the number of commits that touched them.
    top_n:
        Number of top hotspots to return (default 10).

    Returns
    -------
    dict with keys:
        - ``total_files``: int
        - ``total_edits``: int
        - ``median_edits``: float
        - ``mean_edits``: float
        - ``max_edits``: int
        - ``index``: float (0-100 repo fatigue index)
        - ``state``: str (balanced / skewed / strained / brittle)
        - ``band_distribution``: dict of {band: count}
        - ``hotspots``: list of top_n dicts (file, edits, score, band)
    """
    if not edit_counts:
        return {
            "total_files": 0,
            "total_edits": 0,
            "median_edits": 0.0,
            "mean_edits": 0.0,
            "max_edits": 0,
            "index": 0.0,
            "state": "balanced",
            "band_distribution": {
                "fresh": 0, "warm": 0, "hot": 0, "exhausted": 0, "critical": 0,
            },
            "hotspots": [],
        }

    counts = list(edit_counts.values())
    total_files = len(counts)
    total_edits = sum(counts)
    mean_edits = total_edits / total_files
    max_edits = max(counts)

    # Median
    sorted_counts = sorted(counts)
    mid = total_files // 2
    if total_files % 2 == 0:
        median_edits = (sorted_counts[mid - 1] + sorted_counts[mid]) / 2.0
    else:
        median_edits = float(sorted_counts[mid])

    # Scores: normalise to median (floor of 1 to avoid division by zero)
    denominator = max(median_edits, 1.0)
    scored: List[Dict[str, Any]] = []
    for filepath, count in edit_counts.items():
        score = count / denominator
        band = classify_fatigue(score)
        scored.append({
            "file": filepath,
            "edits": count,
            "score": round(score, 3),
            "band": band,
        })

    # Band distribution
    band_dist = {"fresh": 0, "warm": 0, "hot": 0, "exhausted": 0, "critical": 0}
    for entry in scored:
        band_dist[entry["band"]] += 1

    # Repo-level index (Gini * 100)
    gini = _gini([float(c) for c in counts])
    index = round(gini * 100, 1)
    state = _classify_repo_state(index)

    # Hotspots: top_n by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    hotspots = scored[:top_n]

    return {
        "total_files": total_files,
        "total_edits": total_edits,
        "median_edits": round(median_edits, 1),
        "mean_edits": round(mean_edits, 1),
        "max_edits": max_edits,
        "index": index,
        "state": state,
        "band_distribution": band_dist,
        "hotspots": hotspots,
    }


# ---------------------------------------------------------------------------
# Git log parsing (helper for CLI)
# ---------------------------------------------------------------------------


def parse_git_numstat(lines: List[str]) -> Dict[str, int]:
    """Parse ``git log --numstat`` output into per-file commit counts.

    Each commit block starts with ``commit <hash>``.  Numstat lines look
    like::

        10      5       path/to/file.py

    We count one edit per file per commit block (not per line changed).
    """
    counts: Dict[str, int] = {}
    block_files: set = set()

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line.startswith("commit "):
            # Flush previous block
            if block_files:
                for f in block_files:
                    counts[f] = counts.get(f, 0) + 1
            block_files = set()
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            added, removed, filepath = parts[0], parts[1], parts[2]
            if added != "-" and removed != "-":
                block_files.add(filepath)

    # Flush last block
    if block_files:
        for f in block_files:
            counts[f] = counts.get(f, 0) + 1

    return counts
