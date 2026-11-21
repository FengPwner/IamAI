"""file_coupling — measure which files tend to change together.

When two files are modified in the same commit, they share a *coupling
edge*.  Over time these edges accumulate into a graph that reveals
implicit architectural boundaries — or the lack of them.

A healthy codebase has strong coupling within modules and weak coupling
between them.  A codebase where everything changes together on every
commit is either very small or very fragile.

This module computes:

========================  ================================================
metric                    meaning
========================  ================================================
``coupling_score``        0.0–1.0: fraction of commits that touch files
                          in ≥2 distinct areas (lower = better modularity)
``hot_edges``             file pairs that co-change most often
``area_cohesion``         per-area ratio of intra-area to inter-area changes
``dispersion_index``      how spread out changes are per commit
========================  ================================================

Public API
----------
- ``CoChangeEvent`` — one pair of files changing in the same commit
- ``compute_coupling(commits, ...) -> CouplingResult``
- ``classify_coupling(score) -> str``
- ``coupling_report(result) -> str``

Usage::

    from iamai.file_coupling import compute_coupling

    commits = [
        {"files": ["iamai/foo.py", "tests/test_foo.py"]},
        {"files": ["iamai/bar.py", "iamai/baz.py"]},
    ]
    result = compute_coupling(commits)
    print(result.coupling_score)  # e.g. 0.5
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CoChangeEvent:
    """One pair of files that changed in the same commit."""
    file_a: str
    file_b: str
    commit_count: int

    def __post_init__(self) -> None:
        # Always store in sorted order for consistency
        if self.file_a > self.file_b:
            a, b = self.file_a, self.file_b
            object.__setattr__(self, "file_a", b)
            object.__setattr__(self, "file_b", a)


@dataclass(frozen=True)
class CouplingResult:
    """Summary of file coupling analysis."""
    total_commits: int
    coupling_score: float          # 0.0–1.0
    coupling_class: str            # tight | moderate | loose | modular
    hot_edges: List[CoChangeEvent]
    area_cohesion: Dict[str, float]
    dispersion_index: float        # avg distinct areas per commit
    cross_area_fraction: float     # fraction of commits touching ≥2 areas

    @property
    def is_modular(self) -> bool:
        return self.coupling_class in ("modular", "loose")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _area(filepath: str) -> str:
    """Extract top-level directory from a file path.

    >>> _area("iamai/foo.py")
    'iamai'
    >>> _area("README.md")
    '.'
    """
    parts = filepath.replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else "."


def _normalize_edge(a: str, b: str) -> Tuple[str, str]:
    """Return a canonical (sorted) pair."""
    return (a, b) if a <= b else (b, a)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def compute_coupling(
    commits: Sequence[dict],
    *,
    top_n: int = 10,
    area_fn=None,
) -> CouplingResult:
    """Analyze file coupling from a sequence of commit dicts.

    Each commit dict must have a ``"files"`` key containing a list of
    file paths modified in that commit.

    Args:
        commits: list of ``{"files": ["path/a.py", "path/b.py", ...], ...}``
        top_n: how many hot edges to return
        area_fn: optional function to extract area from path (default: top dir)

    Returns:
        CouplingResult with all metrics computed
    """
    if area_fn is None:
        area_fn = _area

    if not commits:
        return CouplingResult(
            total_commits=0,
            coupling_score=0.0,
            coupling_class="modular",
            hot_edges=[],
            area_cohesion={},
            dispersion_index=0.0,
            cross_area_fraction=0.0,
        )

    # --- Edge counting ---
    edge_counter: Counter[Tuple[str, str]] = Counter()
    # --- Per-area stats ---
    area_intra: Counter[str] = Counter()     # commits where all files in same area
    area_inter: Counter[str] = Counter()     # commits where files span areas
    area_touches: Counter[str] = Counter()   # total commits touching each area
    # --- Dispersion ---
    areas_per_commit: List[int] = []
    cross_area_commits = 0

    for commit in commits:
        files = commit.get("files", [])
        if len(files) < 2:
            # Single-file or empty commits: no coupling, but track area
            if files:
                a = area_fn(files[0])
                area_touches[a] += 1
                area_intra[a] += 1
                areas_per_commit.append(1)
            continue

        # Count edges (pairs of files in same commit)
        unique_files = list(set(files))
        for fa, fb in combinations(sorted(unique_files), 2):
            edge = _normalize_edge(fa, fb)
            edge_counter[edge] += 1

        # Area analysis
        areas = set(area_fn(f) for f in unique_files)
        areas_per_commit.append(len(areas))
        n_areas = len(areas)

        if n_areas > 1:
            cross_area_commits += 1

        for a in areas:
            area_touches[a] += 1
            if n_areas == 1:
                area_intra[a] += 1
            else:
                area_inter[a] += 1

    # --- Compute metrics ---
    total = len(commits)

    # Coupling score: fraction of commits that cross area boundaries
    cross_area_fraction = cross_area_commits / total if total > 0 else 0.0
    coupling_score = round(cross_area_fraction, 4)

    # Dispersion index: average distinct areas per commit
    dispersion_index = (
        sum(areas_per_commit) / len(areas_per_commit)
        if areas_per_commit else 0.0
    )

    # Area cohesion: intra / (intra + inter) per area
    area_cohesion: Dict[str, float] = {}
    for a in sorted(area_touches.keys()):
        intra = area_intra.get(a, 0)
        inter = area_inter.get(a, 0)
        total_a = intra + inter
        area_cohesion[a] = round(intra / total_a, 4) if total_a > 0 else 0.0

    # Hot edges: top N most co-changed pairs
    hot_edges = [
        CoChangeEvent(file_a=ea, file_b=eb, commit_count=cnt)
        for (ea, eb), cnt in edge_counter.most_common(top_n)
    ]

    return CouplingResult(
        total_commits=total,
        coupling_score=coupling_score,
        coupling_class=classify_coupling(coupling_score),
        hot_edges=hot_edges,
        area_cohesion=area_cohesion,
        dispersion_index=round(dispersion_index, 4),
        cross_area_fraction=round(cross_area_fraction, 4),
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_coupling(score: float) -> str:
    """Classify coupling score into human-readable category.

    ============  ====================================================
    class         meaning
    ============  ====================================================
    tight         score ≥ 0.80 — most commits cross area boundaries
    moderate      0.50 ≤ score < 0.80 — significant cross-area work
    loose         0.20 ≤ score < 0.50 — mostly within-area changes
    modular       score < 0.20 — changes stay within their area
    ============  ====================================================
    """
    if score >= 0.80:
        return "tight"
    elif score >= 0.50:
        return "moderate"
    elif score >= 0.20:
        return "loose"
    else:
        return "modular"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def coupling_report(result: CouplingResult) -> str:
    """Format a CouplingResult as a human-readable summary."""
    lines = [
        f"file coupling: {result.coupling_class} (score {result.coupling_score:.2f})",
        f"  commits analyzed: {result.total_commits}",
        f"  cross-area fraction: {result.cross_area_fraction:.1%}",
        f"  dispersion index: {result.dispersion_index:.2f} areas/commit",
    ]

    if result.hot_edges:
        lines.append("  hot edges:")
        for edge in result.hot_edges[:5]:
            lines.append(f"    {edge.file_a} ↔ {edge.file_b}  ({edge.commit_count}×)")

    if result.area_cohesion:
        lines.append("  area cohesion:")
        for area, cohesion in sorted(result.area_cohesion.items()):
            lines.append(f"    {area}: {cohesion:.1%}")

    return "\n".join(lines)
