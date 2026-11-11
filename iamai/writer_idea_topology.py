#!/usr/bin/env python3
"""writer_idea_topology — map how a writer connects ideas across domains.

A writer doesn't work in a vacuum. Every stroke touches files, directories,
and conceptual clusters. The topology of these touches reveals whether the
writer is bridging distant ideas (creative synthesis), drilling deep into
one area (depth), or hopping between isolated islands (fragmentation).

Idea topology treats the codebase as a graph: directories are nodes, and
a single stroke that touches multiple directories creates an edge. Over
time, this graph reveals the writer's creative signature.

Some writers are bridge builders — they see connections between auth and
caching, between testing and documentation. Others are deep divers who
spend weeks in a single subsystem. Neither is wrong, but knowing which
mode you're in helps you make deliberate choices about when to broaden
or deepen.

Dimensions
----------

========================  ================================================
metric                    meaning
========================  ================================================
bridge_ratio              fraction of strokes that connect files from
                          two or more distinct top-level directories;
                          higher = more cross-domain linking
concept_density           average number of unique clusters touched per
                          stroke; higher = broader per-stroke reach
cross_pollination_index   0.0–1.0 composite measure of how often ideas
                          from one cluster appear alongside ideas from
                          another; captures the "creative friction"
idea_isolation_ratio      fraction of strokes that touch only a single
                          cluster with no prior bridge in the window;
                          higher = more siloed work
topology_class            archipelago | bridge_builder | deep_diver |
                          networker
========================  ================================================

Topology classes
----------------

==============  ============================================================
class           meaning
==============  ============================================================
bridge_builder  score ≥ 0.70 — writer frequently connects disparate
                domains; excellent for integration work and synthesis
networker       0.50 ≤ score < 0.70 — healthy mix of bridging and
                deepening; well-rounded creative profile
deep_diver      0.30 ≤ score < 0.50 — writer focuses intensely within
                one domain at a time; strong depth but may miss
                cross-cutting opportunities
archipelago     score < 0.30 — work is fragmented into isolated islands
                with few bridges; risk of disconnected knowledge
==============  ============================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _clusters_from_stroke(stroke: dict[str, Any]) -> set[str]:
    """Extract top-level directory clusters from a stroke's file list."""
    files = stroke.get("files", [])
    if not isinstance(files, list):
        return set()
    clusters = set()
    for f in files:
        f_str = str(f) if not isinstance(f, str) else f
        parts = Path(f_str).parts
        if len(parts) >= 2:
            clusters.add(parts[0])
        elif len(parts) == 1:
            # Root-level files form their own cluster
            clusters.add("__root__")
    return clusters


def _is_bridge_stroke(clusters: set[str]) -> bool:
    """A stroke is a bridge if it touches two or more clusters."""
    return len(clusters) >= 2


def compute_topology_metrics(
    strokes: list[dict[str, Any]],
    window_size: int = 30,
) -> dict[str, Any]:
    """Compute idea topology metrics for a list of strokes.

    Parameters
    ----------
    strokes : list[dict]
        List of stroke records, each with a 'files' field.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Topology metrics including bridge_ratio, concept_density,
        cross_pollination_index, idea_isolation_ratio, topology_class.
    """
    if not strokes:
        return {
            "bridge_ratio": 0.0,
            "concept_density": 0.0,
            "cross_pollination_index": 0.0,
            "idea_isolation_ratio": 1.0,
            "topology_score": 0.0,
            "topology_class": "archipelago",
            "strokes_analyzed": 0,
            "total_bridges": 0,
            "unique_clusters": 0,
        }

    recent = strokes[-window_size:]

    bridge_count = 0
    isolated_count = 0
    total_density = 0
    all_clusters: set[str] = set()

    # Track which clusters have been bridged before
    bridged_pairs: set[tuple[str, str]] = set()
    new_bridges = 0

    for i, stroke in enumerate(recent):
        clusters = _clusters_from_stroke(stroke)
        all_clusters.update(clusters)
        total_density += len(clusters) if clusters else 0

        if _is_bridge_stroke(clusters):
            bridge_count += 1

            # Check if this bridge connects previously unconnected clusters
            sorted_clusters = sorted(clusters)
            for a_idx in range(len(sorted_clusters)):
                for b_idx in range(a_idx + 1, len(sorted_clusters)):
                    pair = (sorted_clusters[a_idx], sorted_clusters[b_idx])
                    if pair not in bridged_pairs:
                        new_bridges += 1
                        bridged_pairs.add(pair)
        elif len(clusters) <= 1:
            # Single-cluster stroke: isolated if no recent bridge touched it
            isolated_count += 1

    n = len(recent)
    bridge_ratio = bridge_count / n if n > 0 else 0.0
    concept_density = total_density / n if n > 0 else 0.0
    idea_isolation_ratio = isolated_count / n if n > 0 else 1.0

    # Cross-pollination index: how many unique bridges relative to possible
    possible_pairs = len(all_clusters) * (len(all_clusters) - 1) / 2 if len(all_clusters) > 1 else 1
    cross_pollination_index = min(
        len(bridged_pairs) / possible_pairs if possible_pairs > 0 else 0.0,
        1.0,
    )

    # Composite topology score
    # Higher bridge_ratio is better for connectivity
    bridge_component = bridge_ratio
    # Higher cross_pollination is better
    pollination_component = cross_pollination_index
    # Lower isolation is better (invert)
    isolation_component = 1.0 - idea_isolation_ratio
    # Moderate density is best (too high = scattered, too low = narrow)
    # Normalize density to 0-1 with sweet spot around 2.0
    density_component = min(concept_density / 3.0, 1.0)

    topology_score = (
        0.30 * bridge_component
        + 0.30 * pollination_component
        + 0.20 * isolation_component
        + 0.20 * density_component
    )

    # Classify
    if topology_score >= 0.70:
        topology_class = "bridge_builder"
    elif topology_score >= 0.50:
        topology_class = "networker"
    elif topology_score >= 0.30:
        topology_class = "deep_diver"
    else:
        topology_class = "archipelago"

    return {
        "bridge_ratio": round(bridge_ratio, 3),
        "concept_density": round(concept_density, 2),
        "cross_pollination_index": round(cross_pollination_index, 3),
        "idea_isolation_ratio": round(idea_isolation_ratio, 3),
        "topology_score": round(topology_score, 3),
        "topology_class": topology_class,
        "strokes_analyzed": n,
        "total_bridges": bridge_count,
        "new_bridges": new_bridges,
        "unique_clusters": len(all_clusters),
        "bridged_pairs": len(bridged_pairs),
    }


def analyze_writer_topology(
    data_dir: str = "data",
    writer: str = "qwen",
    window_size: int = 30,
) -> dict[str, Any]:
    """Analyze idea topology for a specific writer.

    Parameters
    ----------
    data_dir : str
        Directory containing strokes.jsonl.
    writer : str
        Writer name to analyze.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Topology metrics for the writer.
    """
    strokes_path = Path(data_dir) / "strokes.jsonl"

    if not strokes_path.exists():
        return {
            "error": "strokes.jsonl not found",
            "bridge_ratio": 0.0,
            "concept_density": 0.0,
            "cross_pollination_index": 0.0,
            "idea_isolation_ratio": 1.0,
            "topology_class": "archipelago",
        }

    writer_strokes: list[dict[str, Any]] = []
    with open(strokes_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
                if stroke.get("writer") == writer:
                    writer_strokes.append(stroke)
            except json.JSONDecodeError:
                continue

    metrics = compute_topology_metrics(writer_strokes, window_size)
    metrics["writer"] = writer
    metrics["total_strokes"] = len(writer_strokes)

    return metrics


def format_topology_report(metrics: dict[str, Any]) -> str:
    """Format topology metrics as a human-readable report."""
    if "error" in metrics:
        return f"Error: {metrics['error']}"

    writer = metrics.get("writer", "unknown")
    tc = metrics.get("topology_class", "unknown")

    report = f"""
Writer Idea Topology: {writer}
{'=' * 50}

Topology Class: {tc.upper()}
Topology Score: {metrics.get('topology_score', 0):.3f} / 1.000

Bridge Metrics:
  - Bridge ratio: {metrics.get('bridge_ratio', 0):.1%}
  - Total bridges: {metrics.get('total_bridges', 0)}
  - New bridges in window: {metrics.get('new_bridges', 0)}
  - Bridged cluster pairs: {metrics.get('bridged_pairs', 0)}

Diversity Metrics:
  - Concept density: {metrics.get('concept_density', 0):.2f} clusters/stroke
  - Unique clusters: {metrics.get('unique_clusters', 0)}
  - Cross-pollination index: {metrics.get('cross_pollination_index', 0):.3f}
  - Idea isolation ratio: {metrics.get('idea_isolation_ratio', 0):.1%}

Analysis Window:
  - Strokes analyzed: {metrics.get('strokes_analyzed', 0)}
  - Total strokes: {metrics.get('total_strokes', 0)}

Interpretation:
"""

    if tc == "bridge_builder":
        report += "  Writer frequently bridges distant domains. This is the\n"
        report += "  signature of a synthesizer who sees connections others miss.\n"
    elif tc == "networker":
        report += "  Writer maintains a healthy balance between bridging and\n"
        report += "  deepening. Ideas flow between domains without losing focus.\n"
    elif tc == "deep_diver":
        report += "  Writer works intensively within single domains. Strong\n"
        report += "  depth but may miss cross-cutting opportunities.\n"
    else:  # archipelago
        report += "  Work is scattered across isolated islands with few\n"
        report += "  bridges. Consider deliberate integration strokes.\n"

    return report


def compute_topology_trend(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute topology metrics over sliding windows to detect trends.

    Parameters
    ----------
    strokes : list[dict]
        Full stroke history.
    window_size : int
        Size of each analysis window.
    step : int
        Step between consecutive windows.

    Returns
    -------
    list[dict]
        List of metrics dicts, one per window.
    """
    if len(strokes) < window_size:
        return [compute_topology_metrics(strokes, window_size)]

    snapshots: list[dict[str, Any]] = []
    for start in range(0, len(strokes) - window_size + 1, step):
        window = strokes[start : start + window_size]
        metrics = compute_topology_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)

    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the overall topology trend from snapshots.

    Returns
    -------
    str
        One of: increasing, stable, decreasing, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("topology_score", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "increasing"
    elif delta < -0.05:
        return "decreasing"
    else:
        return "stable"


if __name__ == "__main__":
    metrics = analyze_writer_topology()
    print(format_topology_report(metrics))
