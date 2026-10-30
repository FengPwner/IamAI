#!/usr/bin/env python3
"""stall_cluster_analyzer — identify and characterise stall clusters.

``stall_pattern.py`` tells you *that* stalls cluster; this module tells
you *where* and *how badly*.  A "cluster" is a run of consecutive stall
gaps (stall-to-stall distance ≤ *cluster_radius* commits) bounded by
quiet periods.

For each cluster the analyser reports:

    ┌──────────────┬──────────────────────────────────────────────┐
    │ Field        │ Meaning                                      │
    ├──────────────┼──────────────────────────────────────────────┤
    │ start        │ commit index of the first stall in cluster   │
    │ end          │ commit index of the last stall in cluster    │
    │ size         │ number of stalls in this cluster             │
    │ severity     │ "mild" | "moderate" | "severe"               │
    │ density      │ stalls per commit within the cluster window  │
    └──────────────┴──────────────────────────────────────────────┘

Severity thresholds:
    mild      — 2–3 stalls in a cluster, density < 0.5
    moderate  — 4–6 stalls, or density ≥ 0.5
    severe    — 7+ stalls, or density ≥ 0.8

Usage:
    python3 tools/stall_cluster_analyzer.py [--commits 100] [--stall-gap 300] [--cluster-radius 2]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import mean
from typing import List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.stall_pattern import (
    analyse as stall_analyse,
    compute_gaps,
    find_stalls,
    get_commit_timestamps,
)


# ── pure helpers (easily testable) ────────────────────────────────

def group_clusters(
    stall_indices: list[int],
    cluster_radius: int = 2,
) -> list[list[int]]:
    """Group stall indices into clusters.

    Two consecutive stalls belong to the same cluster if their index
    distance is ≤ *cluster_radius*.  A gap wider than *cluster_radius*
    starts a new cluster.

    Returns a list of clusters, each cluster being a list of stall
    indices.  Single-stall "clusters" are included — a lone stall
    surrounded by quiet commits is still worth noting.
    """
    if not stall_indices:
        return []

    clusters: list[list[int]] = [[stall_indices[0]]]
    for idx in stall_indices[1:]:
        if idx - clusters[-1][-1] <= cluster_radius:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])
    return clusters


def cluster_severity(size: int, density: float) -> str:
    """Classify a cluster's severity.

    Parameters
    ----------
    size : int
        Number of stalls in the cluster.
    density : float
        Stalls per commit within the cluster window (0.0–1.0).
    """
    if size >= 7 or density >= 0.8:
        return "severe"
    if size >= 4 or density >= 0.5:
        return "moderate"
    return "mild"


def cluster_density(cluster: list[int], total_commits: int) -> float:
    """Stalls per commit within the cluster's span.

    For a single-stall cluster the span is 1, so density is
    1/total_commits (very low — correct for a lone event).
    """
    if len(cluster) <= 1:
        return 1.0 / max(total_commits, 1)
    span = cluster[-1] - cluster[0] + 1
    return len(cluster) / span


def analyse_clusters(
    stall_indices: list[int],
    total_commits: int,
    cluster_radius: int = 2,
) -> list[dict]:
    """Full cluster analysis: group → measure → classify."""
    clusters = group_clusters(stall_indices, cluster_radius)
    results = []
    for cl in clusters:
        dens = cluster_density(cl, total_commits)
        results.append({
            "start": cl[0],
            "end": cl[-1],
            "size": len(cl),
            "density": round(dens, 3),
            "severity": cluster_severity(len(cl), dens),
        })
    return results


# ── summary statistics ────────────────────────────────────────────

def cluster_summary(clusters: list[dict]) -> dict:
    """Aggregate statistics across all clusters.

    Returns a dict with:
        total_clusters:     number of clusters found
        severe_clusters:    count of severe clusters
        moderate_clusters:  count of moderate clusters
        mild_clusters:      count of mild clusters
        mean_cluster_size:  average stalls per cluster
        max_cluster_size:   largest single cluster
        severe_ratio:       fraction of stalls in severe clusters
    """
    if not clusters:
        return {
            "total_clusters": 0,
            "severe_clusters": 0,
            "moderate_clusters": 0,
            "mild_clusters": 0,
            "mean_cluster_size": 0.0,
            "max_cluster_size": 0,
            "severe_ratio": 0.0,
        }

    severe = [c for c in clusters if c["severity"] == "severe"]
    moderate = [c for c in clusters if c["severity"] == "moderate"]
    mild = [c for c in clusters if c["severity"] == "mild"]
    total_stalls = sum(c["size"] for c in clusters)
    severe_stalls = sum(c["size"] for c in severe)

    return {
        "total_clusters": len(clusters),
        "severe_clusters": len(severe),
        "moderate_clusters": len(moderate),
        "mild_clusters": len(mild),
        "mean_cluster_size": round(mean(c["size"] for c in clusters), 2),
        "max_cluster_size": max(c["size"] for c in clusters),
        "severe_ratio": round(severe_stalls / total_stalls, 3) if total_stalls else 0.0,
    }


# ── end-to-end with git ───────────────────────────────────────────

def full_analysis(
    n_commits: int = 100,
    stall_gap: float = 300.0,
    cluster_radius: int = 2,
) -> dict:
    """End-to-end: git log → stalls → clusters → summary."""
    timestamps = get_commit_timestamps(n_commits)
    gaps = compute_gaps(timestamps)
    stall_indices = find_stalls(gaps, stall_gap)
    clusters = analyse_clusters(stall_indices, len(timestamps), cluster_radius)
    summary = cluster_summary(clusters)

    return {
        "total_commits": len(timestamps),
        "stall_count": len(stall_indices),
        "stall_gap_threshold": stall_gap,
        "cluster_radius": cluster_radius,
        "clusters": clusters,
        "summary": summary,
    }


# ── CLI ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse stall clusters in commit history"
    )
    parser.add_argument("--commits", type=int, default=100,
                        help="number of recent commits to analyse")
    parser.add_argument("--stall-gap", type=float, default=300.0,
                        help="minimum seconds to count as a stall")
    parser.add_argument("--cluster-radius", type=int, default=2,
                        help="max commit-index gap within a cluster")
    args = parser.parse_args()

    result = full_analysis(
        n_commits=args.commits,
        stall_gap=args.stall_gap,
        cluster_radius=args.cluster_radius,
    )

    s = result["summary"]
    print(f"commits:          {result['total_commits']}")
    print(f"stalls:           {result['stall_count']}")
    print(f"clusters:         {s['total_clusters']}")
    print(f"  severe:         {s['severe_clusters']}")
    print(f"  moderate:       {s['moderate_clusters']}")
    print(f"  mild:           {s['mild_clusters']}")
    print(f"mean cluster size: {s['mean_cluster_size']}")
    print(f"max cluster size:  {s['max_cluster_size']}")
    print(f"severe ratio:      {s['severe_ratio']:.1%}")
    print()
    for i, cl in enumerate(result["clusters"]):
        print(
            f"  cluster {i+1}: commits {cl['start']}–{cl['end']}, "
            f"{cl['size']} stalls, density {cl['density']}, "
            f"{cl['severity']}"
        )


if __name__ == "__main__":
    main()
