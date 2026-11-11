#!/usr/bin/env python3
"""writer_focus_score — measure how focused a writer is on their current work thread.

A focused writer stays on a coherent thread for multiple strokes before
deliberately switching context. An unfocused writer jumps between unrelated
files and topics, producing fragmented work. Focus isn't about staying in
one file forever — it's about completing a coherent unit before moving on.

This module quantifies focus by analyzing the semantic and structural
relatedness of consecutive strokes. High focus means strokes are building
on each other; low focus means scattered, disconnected work.

Focus dimensions
----------------

========================  ================================================
metric                    meaning
========================  ================================================
thread_length             average number of strokes in a coherent thread
                          before switching to a different area
context_switch_rate       fraction of strokes that switch to a completely
                          different file/topic cluster; lower = more focused
coherence_score           0.0–1.0 measure of how related consecutive strokes
                          are; based on file overlap, directory proximity,
                          and topic similarity
fragmentation_index       number of distinct file clusters touched in the
                          last N strokes divided by N; higher = more scattered
focus_class               laser | focused | drifting | scattered
========================  ================================================

Focus classes
-------------

==============  ============================================================
class           meaning
==============  ============================================================
laser           score ≥ 0.80 — writer stays deeply on one thread; excellent
                for complex refactors but may miss broader context
focused         0.60 ≤ score < 0.80 — good sustained work with occasional
                context switches; productive mode
drifting        0.40 ≤ score < 0.60 — moderate focus with frequent switches;
                may be exploring or losing thread
scattered       score < 0.40 — high fragmentation; writer is jumping around
                without completing threads; risk of incomplete work
==============  ============================================================
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _stroke_files(stroke: dict[str, Any]) -> set[str]:
    """Extract file paths from a stroke."""
    files = stroke.get("files", [])
    if isinstance(files, list):
        return {f if isinstance(f, str) else str(f) for f in files}
    return set()


def _file_cluster(filepath: str) -> str:
    """Get the top-level directory as a cluster identifier."""
    parts = Path(filepath).parts
    if len(parts) >= 1:
        return parts[0]
    return "root"


def _are_files_related(files1: set[str], files2: set[str]) -> bool:
    """Check if two sets of files are related (share cluster or files)."""
    if not files1 or not files2:
        return False
    
    # Direct file overlap
    if files1 & files2:
        return True
    
    # Cluster overlap
    clusters1 = {_file_cluster(f) for f in files1}
    clusters2 = {_file_cluster(f) for f in files2}
    
    return bool(clusters1 & clusters2)


def compute_focus_metrics(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
) -> dict[str, Any]:
    """Compute focus metrics for a list of strokes.
    
    Parameters
    ----------
    strokes : list[dict]
        List of stroke records, each containing a 'files' field
    window_size : int
        Number of recent strokes to analyze
        
    Returns
    -------
    dict
        Focus metrics including:
        - thread_length: average strokes per thread
        - context_switch_rate: fraction of strokes that switch context
        - coherence_score: 0.0–1.0 relatedness of consecutive strokes
        - fragmentation_index: distinct clusters / total strokes
        - focus_class: laser | focused | drifting | scattered
    """
    if not strokes:
        return {
            "thread_length": 0,
            "context_switch_rate": 1.0,
            "coherence_score": 0.0,
            "fragmentation_index": 1.0,
            "focus_score": 0.0,
            "focus_class": "scattered",
            "strokes_analyzed": 0,
            "distinct_clusters": 0,
            "context_switches": 0,
        }
    
    recent = strokes[-window_size:]
    
    # Track threads and context switches
    threads = []
    current_thread_length = 1
    context_switches = 0
    related_pairs = 0
    
    all_clusters = set()
    
    for i, stroke in enumerate(recent):
        files = _stroke_files(stroke)
        clusters = {_file_cluster(f) for f in files}
        all_clusters.update(clusters)
        
        if i == 0:
            continue
        
        prev_files = _stroke_files(recent[i - 1])
        
        if _are_files_related(prev_files, files):
            current_thread_length += 1
            related_pairs += 1
        else:
            # Context switch
            threads.append(current_thread_length)
            current_thread_length = 1
            context_switches += 1
    
    # Don't forget the last thread
    threads.append(current_thread_length)
    
    # Compute metrics
    thread_length = sum(threads) / len(threads) if threads else 0
    context_switch_rate = context_switches / (len(recent) - 1) if len(recent) > 1 else 1.0
    coherence_score = related_pairs / (len(recent) - 1) if len(recent) > 1 else 0.0
    fragmentation_index = len(all_clusters) / len(recent) if recent else 1.0
    
    # Composite focus score (weighted combination)
    # Higher thread length is better (normalize to 0-1, cap at 10)
    thread_score = min(thread_length / 10.0, 1.0)
    # Lower context switch rate is better
    switch_score = 1.0 - context_switch_rate
    # Higher coherence is better
    coherence_component = coherence_score
    # Lower fragmentation is better
    fragmentation_score = 1.0 - min(fragmentation_index, 1.0)
    
    focus_score = (
        0.3 * thread_score +
        0.25 * switch_score +
        0.3 * coherence_component +
        0.15 * fragmentation_score
    )
    
    # Classify
    if focus_score >= 0.80:
        focus_class = "laser"
    elif focus_score >= 0.60:
        focus_class = "focused"
    elif focus_score >= 0.40:
        focus_class = "drifting"
    else:
        focus_class = "scattered"
    
    return {
        "thread_length": round(thread_length, 2),
        "context_switch_rate": round(context_switch_rate, 3),
        "coherence_score": round(coherence_score, 3),
        "fragmentation_index": round(fragmentation_index, 3),
        "focus_score": round(focus_score, 3),
        "focus_class": focus_class,
        "strokes_analyzed": len(recent),
        "distinct_clusters": len(all_clusters),
        "context_switches": context_switches,
    }


def analyze_writer_focus(
    data_dir: str = "data",
    writer: str = "qwen",
    window_size: int = 20,
) -> dict[str, Any]:
    """Analyze focus for a specific writer.
    
    Parameters
    ----------
    data_dir : str
        Directory containing strokes.jsonl
    writer : str
        Writer name to analyze
    window_size : int
        Number of recent strokes to analyze
        
    Returns
    -------
    dict
        Focus metrics for the writer
    """
    strokes_path = Path(data_dir) / "strokes.jsonl"
    
    if not strokes_path.exists():
        return {
            "error": "strokes.jsonl not found",
            "thread_length": 0,
            "context_switch_rate": 1.0,
            "coherence_score": 0.0,
            "fragmentation_index": 1.0,
            "focus_class": "scattered",
        }
    
    # Load strokes for this writer
    writer_strokes = []
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
    
    metrics = compute_focus_metrics(writer_strokes, window_size)
    metrics["writer"] = writer
    metrics["total_strokes"] = len(writer_strokes)
    
    return metrics


def format_focus_report(metrics: dict[str, Any]) -> str:
    """Format focus metrics as a human-readable report."""
    if "error" in metrics:
        return f"Error: {metrics['error']}"
    
    writer = metrics.get("writer", "unknown")
    focus_class = metrics.get("focus_class", "unknown")
    
    report = f"""
Writer Focus Analysis: {writer}
{'=' * 50}

Focus Class: {focus_class.upper()}
Focus Score: {metrics.get('focus_score', 0):.3f} / 1.000

Thread Metrics:
  - Average thread length: {metrics.get('thread_length', 0):.1f} strokes
  - Context switches: {metrics.get('context_switches', 0)}
  - Context switch rate: {metrics.get('context_switch_rate', 0):.1%}

Coherence Metrics:
  - Coherence score: {metrics.get('coherence_score', 0):.3f}
  - Fragmentation index: {metrics.get('fragmentation_index', 0):.3f}
  - Distinct clusters: {metrics.get('distinct_clusters', 0)}

Analysis Window:
  - Strokes analyzed: {metrics.get('strokes_analyzed', 0)}
  - Total strokes: {metrics.get('total_strokes', 0)}

Interpretation:
"""
    
    if focus_class == "laser":
        report += "  Writer is deeply focused on a single thread. Excellent for\n"
        report += "  complex work but may benefit from occasional broader review.\n"
    elif focus_class == "focused":
        report += "  Writer maintains good focus with healthy context switches.\n"
        report += "  This is a productive, sustainable mode.\n"
    elif focus_class == "drifting":
        report += "  Writer shows moderate focus with frequent switches.\n"
        report += "  May be exploring or losing track of the main thread.\n"
    else:  # scattered
        report += "  Writer is highly fragmented, jumping between many areas.\n"
        report += "  Risk of incomplete work; consider focusing on one thread.\n"
    
    return report


if __name__ == "__main__":
    metrics = analyze_writer_focus()
    print(format_focus_report(metrics))
