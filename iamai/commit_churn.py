"""commit_churn — detect when the writer is rewriting instead of adding.

a healthy writer produces mostly additive commits: new thoughts, new
files, new sections.  a stalled writer starts churning — editing the
same files over and over with minimal net change.  the churn index
answers: **what fraction of recent commits are rewrites rather than
additions?**

methodology
-----------

for each commit in the sample window, compute two signals:

1. **file_overlap** — fraction of files touched by this commit that
   were also touched by the previous commit.  high overlap means the
   writer is editing the same files again.

2. **size_delta** — net lines added minus lines removed.  when the
   absolute delta is small but both insertions and deletions are
   large, the commit is a *rewrite* (delete-then-add pattern).

the per-commit churn score is::

    churn_i = 0.6 * file_overlap + 0.4 * rewrite_ratio

where ``rewrite_ratio = min(ins, del) / max(ins, del, 1)``.

the index is the mean churn score over the last N commits, expressed
as an integer 0–100.

bands
-----

=========  ======  =============================================
band       score   meaning
=========  ======  =============================================
healthy    0–29    mostly additive, normal writing rhythm
churning   30–59   noticeable rewrite loop, writer may be stuck
stalled    60–100  heavy rewriting, almost no net progress
=========  ======  =============================================

usage::

    from iamai.commit_churn import churn_index

    commits = [
        {"files": {"a.md", "b.md"}, "insertions": 10, "deletions": 2},
        {"files": {"a.md", "b.md"}, "insertions": 8,  "deletions": 9},
        {"files": {"a.md", "c.md"}, "insertions": 15, "deletions": 1},
    ]
    result = churn_index(commits)
    print(result["score"])   # 0–100
    print(result["band"])    # "healthy" | "churning" | "stalled"

design: pure function, no git subprocess.  the CLI wrapper feeds it
parsed commit data so the core logic is trivially testable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


def _file_overlap(current: Set[str], previous: Set[str]) -> float:
    """fraction of current commit's files that overlap with previous."""
    if not current:
        return 0.0
    overlap = current & previous
    return len(overlap) / len(current)


def _rewrite_ratio(insertions: int, deletions: int) -> float:
    """how much of the commit is rewriting vs net addition.

    a commit that adds 100 lines and deletes 0 → ratio 0.0 (pure add).
    a commit that adds 50 and deletes 50 → ratio 1.0 (pure rewrite).
    """
    total = max(insertions, deletions, 1)
    return min(insertions, deletions) / total


def _per_commit_churn(
    commit: Dict[str, Any],
    prev_files: Set[str],
) -> float:
    """compute churn score for a single commit (0.0–1.0)."""
    files = set(commit.get("files", []))
    ins = commit.get("insertions", 0)
    dels = commit.get("deletions", 0)

    overlap = _file_overlap(files, prev_files)
    rewrite = _rewrite_ratio(ins, dels)

    return 0.6 * overlap + 0.4 * rewrite


def churn_index(
    commits: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """compute the commit churn index over a list of commits.

    parameters
    ----------
    commits : list of dicts
        each dict has keys: "files" (set of file paths),
        "insertions" (int), "deletions" (int).
        ordered oldest-first (commits[0] is the earliest).

    returns
    -------
    dict with keys:
        score (int 0–100), band (str), per_commit (list of floats),
        summary (str).
    """
    if not commits:
        return {
            "score": 0,
            "band": "healthy",
            "per_commit": [],
            "summary": "no commits to analyse",
        }

    scores: List[float] = []
    prev_files: Set[str] = set()

    for commit in commits:
        s = _per_commit_churn(commit, prev_files)
        scores.append(round(s, 4))
        prev_files = set(commit.get("files", []))

    # skip the first commit (no previous to compare with)
    effective = scores[1:] if len(scores) > 1 else scores

    mean_churn = sum(effective) / max(len(effective), 1)
    score = int(round(mean_churn * 100))
    score = max(0, min(100, score))

    band = _band(score)
    summary = (
        f"{len(commits)} commits analysed, "
        f"mean churn {mean_churn:.2f}, "
        f"{sum(1 for s in effective if s >= 0.5)} high-churn commits"
    )

    return {
        "score": score,
        "band": band,
        "per_commit": scores,
        "summary": summary,
    }


def _band(score: int) -> str:
    if score < 30:
        return "healthy"
    if score < 60:
        return "churning"
    return "stalled"
