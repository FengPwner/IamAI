"""repo_gravity — which files attract the most changes?

A living repository distributes its growth across many files.  When one
or two files absorb most of the commits, the repo has a *gravity problem*:
changes collapse into a black hole instead of spreading outward.

Gravity is the Gini coefficient of per-file commit counts.  A repo where
every file is touched equally has gravity 0.0 (perfectly distributed).
A repo where one file is touched by every commit and no other file is
touched at all has gravity approaching 1.0 (maximum concentration).

Gravity bands
~~~~~~~~~~~~~

=============  ============  ===============================================
band           Gini range    meaning
=============  ============  ===============================================
distributed    0.00 – 0.30   healthy spread, many files grow together
balanced       0.30 – 0.50   moderate concentration, a few hotspots
concentrated   0.50 – 0.70   too many changes in too few files
black-hole     0.70 – 1.00   one or two files absorb everything
=============  ============  ===============================================

Why it matters
~~~~~~~~~~~~~~

- **Low gravity** (distributed) means the repo is growing breadth-first:
  new modules, new notes, new docs.  This is the sign of a healthy,
  exploratory writer.

- **High gravity** (black-hole) means the writer keeps editing the same
  files over and over — append-only logs like ``data/strokes.jsonl`` or
  ``docs/DEVLOG.md`` are typical culprits.  Some concentration is natural
  for a repo with append-only data files; the caretaker should look at
  *non-data gravity* separately to detect pathological looping.

- **Trending gravity** (increasing over time) is more alarming than
  static high gravity.  A repo that was distributed last week but is
  concentrated this week has *collapsed* — the writer stopped exploring
  and started looping.

Public API
~~~~~~~~~~

- ``parse_commit_file_counts(git_log_output)``
    Parse ``git log --name-only`` output → ``Counter({path: count})``.
- ``compute_gravity(file_counts)``
    Compute Gini coefficient from a Counter of per-file commit counts.
- ``gravity_band(gini)``
    Classify Gini into a band label.
- ``top_attractors(file_counts, n)``
    Return the *n* files with the highest commit counts.
- ``gravity_report(file_counts)``
    One-call convenience: Gini + band + top attractors + summary.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Gini coefficient
# ---------------------------------------------------------------------------

def compute_gravity(file_counts: Counter) -> float:
    """Compute the Gini coefficient of per-file commit counts.

    Parameters
    ----------
    file_counts : Counter
        Mapping of file path → number of commits touching that file.

    Returns
    -------
    float
        Gini coefficient in [0.0, 1.0].  0.0 = perfectly equal,
        1.0 = maximum inequality.

    Notes
    -----
    Uses the mean-absolute-difference formula:

        G = Σ_i Σ_j |x_i - x_j| / (2 * n * Σ x_i)

    Returns 0.0 for empty input or single-element input.
    """
    values = sorted(file_counts.values())
    n = len(values)
    if n <= 1:
        return 0.0
    total = sum(values)
    if total == 0:
        return 0.0

    abs_diff_sum = 0
    for i, xi in enumerate(values):
        for j, xj in enumerate(values):
            abs_diff_sum += abs(xi - xj)

    return abs_diff_sum / (2.0 * n * total)


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------

_BANDS: List[Tuple[str, float, float]] = [
    ("distributed", 0.0, 0.30),
    ("balanced",    0.30, 0.50),
    ("concentrated", 0.50, 0.70),
    ("black-hole",  0.70, 1.0 + 1e-9),
]


def gravity_band(gini: float) -> str:
    """Classify a Gini coefficient into a gravity band.

    Parameters
    ----------
    gini : float
        Gini coefficient in [0.0, 1.0].

    Returns
    -------
    str
        One of: ``"distributed"``, ``"balanced"``, ``"concentrated"``,
        ``"black-hole"``.
    """
    for label, lo, hi in _BANDS:
        if lo <= gini < hi:
            return label
    # clamp to last band for edge cases (gini >= 1.0)
    return "black-hole"


# ---------------------------------------------------------------------------
# Git log parsing
# ---------------------------------------------------------------------------

def parse_commit_file_counts(git_log_output: str) -> Counter:
    """Parse ``git log --name-only`` output into per-file commit counts.

    Expects the standard format where each commit is separated by a blank
    line, followed by a commit hash line, then one file path per line.

    The parser is lenient: blank lines, commit hash lines (starting with
    a hex string), and lines starting with ``commit `` are skipped.

    Parameters
    ----------
    git_log_output : str
        Raw output from ``git log --name-only --pretty=format:''``.

    Returns
    -------
    Counter
        Mapping of file path → number of commits touching that file.
    """
    counts: Counter = Counter()
    for line in git_log_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # skip commit hash lines and "commit ..." headers
        if line.startswith("commit "):
            continue
        if len(line) >= 7 and all(c in "0123456789abcdef" for c in line[:7]):
            continue
        # everything else is a file path
        counts[line] += 1
    return counts


# ---------------------------------------------------------------------------
# Top attractors
# ---------------------------------------------------------------------------

def top_attractors(file_counts: Counter, n: int = 10) -> List[Dict[str, Any]]:
    """Return the *n* files with the highest commit counts.

    Parameters
    ----------
    file_counts : Counter
        Mapping of file path → number of commits touching that file.
    n : int
        Number of top attractors to return.

    Returns
    -------
    list of dict
        Each dict has keys ``path``, ``commits``, ``share`` (fraction
        of total commits touching this file).
    """
    total = sum(file_counts.values()) or 1
    return [
        {"path": path, "commits": count, "share": count / total}
        for path, count in file_counts.most_common(n)
    ]


# ---------------------------------------------------------------------------
# Convenience report
# ---------------------------------------------------------------------------

def gravity_report(file_counts: Counter, n: int = 10) -> Dict[str, Any]:
    """One-call convenience: Gini + band + top attractors + summary.

    Parameters
    ----------
    file_counts : Counter
        Mapping of file path → number of commits touching that file.
    n : int
        Number of top attractors to include.

    Returns
    -------
    dict
        Keys: ``gini``, ``band``, ``file_count``, ``total_commits``,
        ``top_attractors``, ``summary``.
    """
    gini = compute_gravity(file_counts)
    band = gravity_band(gini)
    attractors = top_attractors(file_counts, n)
    total = sum(file_counts.values())

    summary = (
        f"gravity={gini:.3f} ({band}), "
        f"{len(file_counts)} files across {total} commit-touches, "
        f"top attractor: {attractors[0]['path'] if attractors else 'none'} "
        f"({attractors[0]['share']:.1%})" if attractors else
        f"gravity={gini:.3f} ({band}), no files tracked"
    )

    return {
        "gini": gini,
        "band": band,
        "file_count": len(file_counts),
        "total_commits": total,
        "top_attractors": attractors,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point: read git log from stdin or run git log locally."""
    import subprocess
    import sys

    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        try:
            result = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:"],
                capture_output=True, text=True, timeout=30,
            )
            text = result.stdout
        except Exception as exc:
            print(f"error running git log: {exc}", file=sys.stderr)
            sys.exit(1)

    counts = parse_commit_file_counts(text)
    if not counts:
        print("no file data found in git log output")
        sys.exit(0)

    report = gravity_report(counts)
    print(report["summary"])
    print()
    print("Top attractors:")
    for a in report["top_attractors"]:
        print(f"  {a['path']:50s}  {a['commits']:4d} commits  ({a['share']:.1%})")


if __name__ == "__main__":
    main()
