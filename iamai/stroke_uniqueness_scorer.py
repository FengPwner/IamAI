#!/usr/bin/env python3
"""stroke_uniqueness_scorer — detect repetitive content in the stroke log.

The writer generates aphorisms, observations, and notes across six stroke
kinds (devlog, garden, note, thought, metrics, snippet).  When the creative
well runs dry, the writer may fall back to recycling earlier material —
producing near-identical text with minor variations.  This degrades the
value of the stroke log as a creative artifact.

This module provides a fast, non-destructive uniqueness analysis that
scores each stroke against the corpus and flags clusters of similar
content.

Scoring dimensions
------------------

==================  =====================================================
metric              meaning
==================  =====================================================
global_ratio        fraction of strokes that are unique (no near-dup)
dup_count           number of strokes with at least one near-duplicate
cluster_count       number of distinct duplicate clusters
worst_offender      (text, count) pair for the most repeated content
kind_breakdown      per-kind uniqueness ratios
entropy             Shannon entropy of the token distribution
==================  =====================================================

Similarity is measured using a configurable token-overlap threshold
(Jaccard similarity on word-level tokens after lowercasing and
stripping punctuation).  This avoids pulling in heavy NLP
dependencies while still catching the common failure mode: the writer
repeating the same aphorism with a different trailing clause.

Public API
----------
- ``UniquenessReport``: dataclass with all scoring dimensions
- ``score_corpus(strokes, threshold=0.7) -> UniquenessReport``
- ``score_text(text, corpus_texts, threshold=0.7) -> float``
- ``find_clusters(strokes, threshold=0.7) -> list[DuplicateCluster]``

Usage::

    from iamai.stroke_uniqueness_scorer import score_corpus
    import json

    strokes = [json.loads(line) for line in open("data/strokes.jsonl")]
    report = score_corpus(strokes, threshold=0.7)
    print(report.global_ratio)      # 0.94
    print(report.dup_count)         # 42
    print(report.worst_offender)    # ("deleting a file is progress too", 3)
"""

from __future__ import annotations

import json
import math
import re
import string
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DuplicateCluster:
    """A group of strokes whose text is near-identical."""

    representative: str
    indices: tuple[int, ...]
    size: int

    def __len__(self) -> int:
        return self.size


@dataclass
class UniquenessReport:
    """Full uniqueness analysis result."""

    total: int
    unique_count: int
    dup_count: int
    global_ratio: float
    cluster_count: int
    clusters: list[DuplicateCluster]
    kind_breakdown: dict[str, float]
    entropy: float
    worst_offender: Optional[tuple[str, int]]

    @property
    def is_healthy(self) -> bool:
        """Corpus is healthy when at least 90% of strokes are unique."""
        return self.global_ratio >= 0.90

    def clusters_of_size(self, min_size: int) -> list[DuplicateCluster]:
        """Return clusters with at least *min_size* members."""
        return [c for c in self.clusters if c.size >= min_size]

    def summary(self) -> str:
        """One-line human summary."""
        if self.dup_count == 0:
            return f"All {self.total} strokes are unique."
        return (
            f"{self.dup_count}/{self.total} strokes have near-duplicates "
            f"({self.cluster_count} clusters, "
            f"uniqueness={self.global_ratio:.1%})"
        )


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

_STRIP = str.maketrans("", "", string.punctuation)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    if not text:
        return []
    cleaned = text.lower().translate(_STRIP)
    return [t for t in cleaned.split() if t]


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def _extract_text(stroke: dict) -> str:
    """Extract the primary text content from a stroke dict."""
    return stroke.get("text", "") or ""


def score_text(text: str, corpus_texts: list[str], threshold: float = 0.7) -> float:
    """Score *text* against a corpus: 1.0 = fully unique, 0.0 = exact dup.

    Returns the **maximum** Jaccard similarity found.  If that maximum
    exceeds *threshold*, the text is considered a near-duplicate and
    the score drops to ``1 - max_similarity``.
    """
    tokens_a = set(_tokenize(text))
    if not tokens_a:
        return 0.0

    max_sim = 0.0
    for ct in corpus_texts:
        tokens_b = set(_tokenize(ct))
        sim = _jaccard(tokens_a, tokens_b)
        if sim > max_sim:
            max_sim = sim
        if max_sim >= 1.0:
            break

    if max_sim >= threshold:
        return round(1.0 - max_sim, 4)
    return 1.0


def find_clusters(
    strokes: list[dict],
    threshold: float = 0.7,
) -> list[DuplicateCluster]:
    """Find groups of near-duplicate strokes.

    Uses a simple greedy approach: iterate through strokes, and for
    each unassigned stroke, find all later strokes above the similarity
    threshold and group them into a cluster.  O(n²) in the worst case
    but fast for typical corpus sizes (< 10 000 strokes).
    """
    texts = [_extract_text(s) for s in strokes]
    token_sets = [set(_tokenize(t)) for t in texts]
    n = len(strokes)
    assigned: set[int] = set()
    clusters: list[DuplicateCluster] = []

    for i in range(n):
        if i in assigned:
            continue
        members = [i]
        tokens_i = token_sets[i]
        if not tokens_i:
            continue
        for j in range(i + 1, n):
            if j in assigned:
                continue
            if _jaccard(tokens_i, token_sets[j]) >= threshold:
                members.append(j)
                assigned.add(j)
        if len(members) > 1:
            assigned.add(i)
            clusters.append(
                DuplicateCluster(
                    representative=texts[i],
                    indices=tuple(members),
                    size=len(members),
                )
            )

    clusters.sort(key=lambda c: c.size, reverse=True)
    return clusters


def score_corpus(
    strokes: list[dict],
    threshold: float = 0.7,
) -> UniquenessReport:
    """Run a full uniqueness analysis on a corpus of strokes."""
    total = len(strokes)
    if total == 0:
        return UniquenessReport(
            total=0,
            unique_count=0,
            dup_count=0,
            global_ratio=1.0,
            cluster_count=0,
            clusters=[],
            kind_breakdown={},
            entropy=0.0,
            worst_offender=None,
        )

    clusters = find_clusters(strokes, threshold)

    # Count duplicated strokes
    dup_indices: set[int] = set()
    for c in clusters:
        dup_indices.update(c.indices)
    dup_count = len(dup_indices)
    unique_count = total - dup_count

    # Per-kind breakdown
    kind_groups: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(strokes):
        kind = s.get("kind", "unknown")
        kind_groups[kind].append(i)

    kind_breakdown: dict[str, float] = {}
    for kind, indices in sorted(kind_groups.items()):
        kind_dups = sum(1 for i in indices if i in dup_indices)
        kind_breakdown[kind] = round(
            (len(indices) - kind_dups) / len(indices), 4
        ) if indices else 1.0

    # Token entropy
    all_tokens: Counter = Counter()
    for s in strokes:
        all_tokens.update(_tokenize(_extract_text(s)))
    total_tokens = sum(all_tokens.values())
    entropy = 0.0
    if total_tokens > 0:
        for count in all_tokens.values():
            p = count / total_tokens
            if p > 0:
                entropy -= p * math.log2(p)

    # Worst offender
    worst: Optional[tuple[str, int]] = None
    if clusters:
        top = clusters[0]
        worst = (top.representative, top.size)

    return UniquenessReport(
        total=total,
        unique_count=unique_count,
        dup_count=dup_count,
        global_ratio=round(unique_count / total, 4),
        cluster_count=len(clusters),
        clusters=clusters,
        kind_breakdown=kind_breakdown,
        entropy=round(entropy, 4),
        worst_offender=worst,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``python -m iamai.stroke_uniqueness_scorer [path]``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Score uniqueness of strokes in a JSONL log."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="data/strokes.jsonl",
        help="Path to strokes JSONL file (default: data/strokes.jsonl)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Jaccard similarity threshold for near-duplicate (default: 0.7)",
    )
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 1

    strokes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    report = score_corpus(strokes, threshold=args.threshold)
    print(report.summary())
    if report.worst_offender:
        text, count = report.worst_offender
        print(f"worst offender ({count}x): {text[:80]}...")
    for kind, ratio in sorted(report.kind_breakdown.items()):
        flag = " ⚠" if ratio < 0.90 else ""
        print(f"  {kind}: {ratio:.1%} unique{flag}")

    return 0 if report.is_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
