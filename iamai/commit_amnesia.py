"""commit_amnesia — detect when commit batches forget pending files.

The batch committer runs every 600 seconds and is supposed to sweep
*all* modified tracked files into a single commit.  Sometimes it
misses: a file was staged by the writer but the batch only picked
up a subset, or a lock prevented one file from being read, or a
race condition left a file in the working tree but out of the
commit.

This module quantifies that "forgetfulness" along three dimensions:

==================  ====================================================
dimension           what it measures
==================  ====================================================
omission_ratio      fraction of modified files that were *not* included
                    in the most recent commit — the raw amnesia rate
stale_file_age      how long the oldest forgotten file has been sitting
                    uncommitted — stale data rots
recovery_lag        how many commit cycles it took before forgotten
                    files were eventually picked up — the memory delay
==================  ====================================================

Each dimension scores 0–100 (higher = better memory).  The composite
is the weighted mean (omission 40%, stale 35%, recovery 25%) classified
into four grades:

==========  ===================================================
grade       meaning
==========  ===================================================
eidetic     ≥ 85 — batch remembers everything
sharp       ≥ 65 — minor omissions, recovered quickly
foggy       ≥ 40 — noticeable gaps, slow recovery
amnesiac    <  40 — significant files consistently forgotten
==========  ===================================================

Why weighted: omission_ratio is the most actionable signal because
it directly measures *current* data loss risk.  Stale file age
matters because forgotten files accumulate invisible debt.  Recovery
lag is softest because sometimes the next batch catches up anyway.

Usage::

    from iamai.commit_amnesia import amnesia, amnesia_report

    a = amnesia(
        modified_files=12,
        committed_files=9,
        oldest_uncommitted_age=340.0,  # seconds
        cycles_since_omission=2,
    )
    print(a["score"])    # 58.5
    print(a["grade"])    # "foggy"

    print(amnesia_report(a))
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def score_omission(modified: int, committed: int) -> float:
    """Score the fraction of modified files that made it into the commit.

    - all committed → 100
    - none committed → 0
    - linear scale between.

    If there are no modified files, there is nothing to forget → 100.
    """
    if modified <= 0:
        return 100.0
    omitted = max(0, modified - committed)
    ratio = omitted / modified  # 0 = perfect, 1 = total amnesia
    return 100.0 * (1.0 - ratio)


def score_stale_age(age_seconds: float, commit_interval: float = 600.0) -> float:
    """Score how long the oldest forgotten file has been uncommitted.

    - age ≤ 1× commit interval → 100 (just missed this cycle)
    - age ≥ 5× commit interval → 0   (forgotten for hours)
    - linear between.
    """
    if age_seconds <= 0:
        return 100.0
    low = commit_interval
    high = 5.0 * commit_interval
    if age_seconds <= low:
        return 100.0
    if age_seconds >= high:
        return 0.0
    return 100.0 * (high - age_seconds) / (high - low)


def score_recovery_lag(cycles: int) -> float:
    """Score how many commit cycles it took to recover forgotten files.

    - 0 cycles (nothing forgotten, or recovered same cycle) → 100
    - 1 cycle → 75
    - 2 cycles → 50
    - 3 cycles → 25
    - 4+ cycles → 0
    """
    if cycles <= 0:
        return 100.0
    return max(0.0, 100.0 - cycles * 25.0)


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "omission": 0.40,
    "stale": 0.35,
    "recovery": 0.25,
}

_GRADES = [
    (85, "eidetic"),
    (65, "sharp"),
    (40, "foggy"),
]


def _classify(score: float) -> str:
    for threshold, grade in _GRADES:
        if score >= threshold:
            return grade
    return "amnesiac"


def amnesia(
    modified_files: int,
    committed_files: int,
    oldest_uncommitted_age: float = 0.0,
    cycles_since_omission: int = 0,
    commit_interval: float = 600.0,
) -> dict[str, Any]:
    """Compute the commit amnesia composite.

    Parameters
    ----------
    modified_files : int
        Total number of tracked files with uncommitted modifications
        at the time the batch fired.
    committed_files : int
        Number of files actually included in the commit.
    oldest_uncommitted_age : float
        Seconds since the oldest still-uncommitted file was last
        modified (0 if nothing remains uncommitted).
    cycles_since_omission : int
        How many batch cycles elapsed between the first omission
        and eventual recovery (0 if nothing was forgotten).
    commit_interval : float
        Seconds between batch commits (default 600).

    Returns
    -------
    dict with keys: score, grade, dimensions, omitted_files,
    omission_ratio.
    """
    omitted = max(0, modified_files - committed_files)
    omission_ratio = omitted / modified_files if modified_files > 0 else 0.0

    d_omission = score_omission(modified_files, committed_files)
    d_stale = score_stale_age(oldest_uncommitted_age, commit_interval)
    d_recovery = score_recovery_lag(cycles_since_omission)

    score = (
        _WEIGHTS["omission"] * d_omission
        + _WEIGHTS["stale"] * d_stale
        + _WEIGHTS["recovery"] * d_recovery
    )
    score = round(score, 1)
    grade = _classify(score)

    return {
        "score": score,
        "grade": grade,
        "dimensions": {
            "omission": round(d_omission, 1),
            "stale": round(d_stale, 1),
            "recovery": round(d_recovery, 1),
        },
        "omitted_files": omitted,
        "omission_ratio": round(omission_ratio, 3),
    }


def amnesia_report(a: dict[str, Any]) -> str:
    """One-line human-readable summary."""
    d = a["dimensions"]
    return (
        f"amnesia {a['score']}/100 ({a['grade']}) — "
        f"omission {d['omission']}/100, stale {d['stale']}/100, "
        f"recovery {d['recovery']}/100 "
        f"| {a['omitted_files']} file(s) forgotten, "
        f"ratio {a['omission_ratio']}"
    )
