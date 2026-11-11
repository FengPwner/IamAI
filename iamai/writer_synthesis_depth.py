#!/usr/bin/env python3
"""writer_synthesis_depth — measure how deeply a writer integrates multiple
prior sources into new content.

Synthesis is the difference between a writer who weaves threads together
and one who lays them side by side. A high-synthesis writer reads what
they wrote five minutes ago, connects it to what they wrote an hour ago,
and produces something that draws on both. A low-synthesis writer treats
every stroke as an independent artifact — correct in isolation but never
deliberately referencing or building on the broader body of work.

Synthesis is not the same as momentum. Momentum measures whether a
writer *extends* recent work (touches the same files, continues the same
thread). Synthesis measures whether a writer *connects* disparate pieces
— pulling together ideas from different areas, referencing multiple
prior strokes, producing content that could not have been written without
the full body of preceding work.

A writer with high momentum but low synthesis is a focused builder —
each stroke adds a brick to the same wall. A writer with high synthesis
but low momentum is a weaver — each stroke draws on multiple prior
strokes but may not extend any single one. The ideal is both: extending
recent work *while* weaving in connections to the broader context.

Dimensions
----------

======================  ================================================
metric                  meaning
======================  ================================================
cross_reference_rate    fraction of strokes that reference content from
                        two or more prior strokes; higher = more often
                        drawing on multiple sources simultaneously
integration_index       average number of distinct prior source areas
                        (clusters or files) referenced per stroke;
                        measures breadth of integration
synthesis_density       ratio of actual cross-references to maximum
                        possible; measures how densely interconnected
                        the references are within a window
isolation_ratio         fraction of strokes that reference zero prior
                        strokes or areas; the inverse of synthesis
synthesis_class         deep_synthesizer | compiler | aggregator | collager
======================  ================================================

Synthesis classes
-----------------

==================  ============================================================
class               meaning
==================  ============================================================
deep_synthesizer    score ≥ 0.70 — writer consistently weaves multiple prior
                    sources into each new stroke; content shows evidence of
                    connecting ideas across domains
compiler            0.50 ≤ score < 0.70 — healthy integration of prior work
                    with occasional isolated strokes; the normal productive
                    mode for most sustained writing
aggregator          0.30 ≤ score < 0.50 — occasional cross-references but
                    most strokes stand alone; the writer collects information
                    without weaving it together
collager            score < 0.30 — most strokes are independent fragments;
                    prior work is rarely referenced; the output is a
                    collection of isolated pieces rather than an integrated
                    body of work
==================  ============================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stroke_refs(stroke: dict[str, Any]) -> set[str]:
    """Extract normalized reference identifiers from a stroke record.

    References can be:
    - A list of prior stroke IDs or indices under ``references``
    - A list of source file paths under ``sources``
    - A list of cluster/area names under ``areas`` or ``clusters``
    """
    refs: set[str] = set()
    for key in ("references", "sources", "areas", "clusters", "refs"):
        val = stroke.get(key, [])
        if isinstance(val, list):
            for item in val:
                if isinstance(item, (str, int)):
                    s = str(item).strip()
                    if s:
                        refs.add(s)
        elif isinstance(val, (str, int)):
            s = str(val).strip()
            if s:
                refs.add(s)
    return refs


def _stroke_files(stroke: dict[str, Any]) -> set[str]:
    """Extract normalized file paths from a stroke record."""
    files = stroke.get("files", [])
    if not isinstance(files, list):
        return set()
    result = set()
    for f in files:
        if isinstance(f, (str, Path)):
            s = str(f).strip()
            if s:
                result.add(s)
    return result


def _stroke_cluster(stroke: dict[str, Any]) -> str | None:
    """Extract the primary cluster or area from a stroke record."""
    for key in ("cluster", "area", "topic", "category"):
        val = stroke.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _prior_source_set(
    strokes: list[dict[str, Any]],
    index: int,
    lookback: int,
) -> set[str]:
    """Collect all source identifiers from the ``lookback`` strokes before
    ``index``, including file paths and clusters as implicit sources."""
    start = max(0, index - lookback)
    sources: set[str] = set()
    for j in range(start, index):
        sources |= _stroke_refs(strokes[j])
        # File paths are implicit sources — touching the same file
        # constitutes a reference even without explicit citation.
        sources |= _stroke_files(strokes[j])
        # Cluster is an implicit grouping source.
        cluster = _stroke_cluster(strokes[j])
        if cluster:
            sources.add(f"cluster:{cluster}")
    return sources


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def compute_synthesis_metrics(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
    lookback: int = 5,
) -> dict[str, Any]:
    """Compute synthesis depth metrics for a list of strokes.

    Parameters
    ----------
    strokes : list[dict]
        List of stroke records. Each may contain ``references``,
        ``sources``, ``areas``, ``clusters``, ``files``, ``cluster``,
        and ``content`` fields.
    window_size : int
        Number of recent strokes to analyze.
    lookback : int
        How many prior strokes to check when computing cross-references.

    Returns
    -------
    dict
        Synthesis metrics including:
        - cross_reference_rate, integration_index, synthesis_density,
          isolation_ratio, synthesis_score, synthesis_class,
          strokes_analyzed, areas_count.
    """
    if not strokes:
        return {
            "cross_reference_rate": 0.0,
            "integration_index": 0.0,
            "synthesis_density": 0.0,
            "isolation_ratio": 1.0,
            "synthesis_score": 0.0,
            "synthesis_class": "collager",
            "strokes_analyzed": 0,
            "areas_count": 0,
        }

    recent = strokes[-window_size:]
    n = len(recent)

    if n < 2:
        refs0 = _stroke_refs(recent[0]) if n == 1 else set()
        return {
            "cross_reference_rate": 0.0,
            "integration_index": float(len(refs0)),
            "synthesis_density": 0.0,
            "isolation_ratio": 0.0 if refs0 else 1.0,
            "synthesis_score": 0.0,
            "synthesis_class": "collager",
            "strokes_analyzed": n,
            "areas_count": 1 if refs0 else 0,
        }

    cross_ref_count = 0
    total_refs = 0
    isolation_count = 0
    all_areas: set[str] = set()

    # For synthesis density: track all unique sources in the window
    all_window_sources: set[str] = set()
    per_stroke_sources: list[set[str]] = []

    for i in range(n):
        cur_refs = _stroke_refs(recent[i])
        cur_files = _stroke_files(recent[i])
        cur_cluster = _stroke_cluster(recent[i])

        # What prior sources are available
        prior_sources = _prior_source_set(recent, i, lookback)
        all_window_sources |= prior_sources

        # Explicit references that overlap with prior sources
        explicit_overlap = cur_refs & prior_sources

        # Implicit references: files touched that were also touched recently
        file_overlap = cur_files & {
            f for f in prior_sources
            if not f.startswith("cluster:")
        }

        # Combined: explicit refs + implicit file overlap + cluster overlap
        combined_refs = explicit_overlap | file_overlap
        if cur_cluster and f"cluster:{cur_cluster}" in prior_sources:
            combined_refs.add(f"cluster:{cur_cluster}")

        per_stroke_sources.append(combined_refs)

        # Count cross-references (2+ distinct prior sources)
        if len(combined_refs) >= 2:
            cross_ref_count += 1

        total_refs += len(combined_refs)

        # Track areas
        all_areas |= cur_refs
        if cur_cluster:
            all_areas.add(f"cluster:{cur_cluster}")
        all_areas |= cur_files

        # Isolation: zero references to prior work
        if len(combined_refs) == 0:
            isolation_count += 1

    cross_reference_rate = cross_ref_count / n
    integration_index = total_refs / n if n > 0 else 0.0
    isolation_ratio = isolation_count / n

    # Synthesis density: ratio of actual cross-references to theoretical maximum
    # Maximum possible: each stroke could reference all prior sources
    max_possible_refs = sum(
        len(_prior_source_set(recent, i, lookback)) for i in range(n)
    )
    synthesis_density = total_refs / max_possible_refs if max_possible_refs > 0 else 0.0

    # Composite score: weighted combination
    # cross_reference_rate (35%) — frequency of multi-source synthesis
    # integration_index normalized (25%) — breadth of integration
    # synthesis_density (25%) — density of connections
    # inverse isolation (15%) — absence of isolated strokes
    #
    # Normalize integration_index to [0, 1] using sigmoid-like scaling
    # where 5+ refs per stroke scores near 1.0
    norm_integration = min(integration_index / 5.0, 1.0) if integration_index > 0 else 0.0

    synthesis_score = (
        0.35 * cross_reference_rate
        + 0.25 * norm_integration
        + 0.25 * synthesis_density
        + 0.15 * (1.0 - isolation_ratio)
    )

    return {
        "cross_reference_rate": round(cross_reference_rate, 4),
        "integration_index": round(integration_index, 4),
        "synthesis_density": round(synthesis_density, 4),
        "isolation_ratio": round(isolation_ratio, 4),
        "synthesis_score": round(synthesis_score, 4),
        "synthesis_class": _classify(synthesis_score),
        "strokes_analyzed": n,
        "areas_count": len(all_areas),
    }


def _classify(score: float) -> str:
    """Classify a writer's synthesis depth based on composite score."""
    if score >= 0.70:
        return "deep_synthesizer"
    elif score >= 0.50:
        return "compiler"
    elif score >= 0.30:
        return "aggregator"
    else:
        return "collager"


# ---------------------------------------------------------------------------
# High-level analysis
# ---------------------------------------------------------------------------

def analyze_writer_synthesis(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
    lookback: int = 5,
) -> dict[str, Any]:
    """Run full synthesis depth analysis on a stroke list.

    Convenience wrapper around :func:`compute_synthesis_metrics` that
    returns the metrics dict augmented with a human-readable report.

    Parameters
    ----------
    strokes : list[dict]
        Stroke records.
    window_size : int
        Analysis window size.
    lookback : int
        Prior stroke lookback window.

    Returns
    -------
    dict
        Metrics dict with added ``report`` field.
    """
    metrics = compute_synthesis_metrics(strokes, window_size, lookback)
    metrics["report"] = format_synthesis_report(metrics)
    return metrics


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_synthesis_report(metrics: dict[str, Any]) -> str:
    """Format synthesis metrics as a human-readable report.

    Parameters
    ----------
    metrics : dict
        Output from :func:`compute_synthesis_metrics`.

    Returns
    -------
    str
        Multi-line formatted report string.
    """
    lines = [
        "Writer Synthesis Depth Report",
        "=" * 40,
        f"Strokes analyzed:    {metrics['strokes_analyzed']}",
        f"Areas detected:      {metrics['areas_count']}",
        "",
        "Metrics:",
        f"  cross_reference_rate:  {metrics['cross_reference_rate']:.4f}",
        f"  integration_index:     {metrics['integration_index']:.4f}",
        f"  synthesis_density:     {metrics['synthesis_density']:.4f}",
        f"  isolation_ratio:       {metrics['isolation_ratio']:.4f}",
        "",
        f"Synthesis score:     {metrics['synthesis_score']:.4f}",
        f"Synthesis class:     {metrics['synthesis_class']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def compute_synthesis_trend(
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze how synthesis depth changes across multiple snapshots.

    Parameters
    ----------
    snapshots : list[dict]
        List of synthesis metric dicts (from successive time windows).

    Returns
    -------
    dict
        Trend information including:
        - direction: increasing | stable | decreasing
        - delta: score change from first to last snapshot
        - snapshots: number of snapshots analyzed
    """
    if len(snapshots) < 2:
        return {
            "direction": "insufficient_data",
            "delta": 0.0,
            "snapshots": len(snapshots),
        }

    scores = [s.get("synthesis_score", 0.0) for s in snapshots]
    delta = scores[-1] - scores[0]

    if delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "delta": round(delta, 4),
        "snapshots": len(snapshots),
        "first_score": scores[0],
        "last_score": scores[-1],
    }


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Return just the trend direction string."""
    return compute_synthesis_trend(snapshots)["direction"]
