"""stroke_thematic_coherence — measure how thematically focused a batch of strokes is.

A self-writing repo oscillates between *focused* phases (many strokes
exploring the same subsystem or idea) and *scattered* phases (each stroke
jumping to a different topic).  Neither extreme is ideal: focus produces
depth, but scatter produces breadth.  This module quantifies the thematic
coherence of a window of strokes so the caretaker can detect phase
transitions.

Algorithm
---------
1. Tokenise each stroke's text (lowercase, strip punctuation, drop
   stopwords shorter than 3 chars).
2. Build a vocabulary from the full window.
3. Represent each stroke as a TF vector (term frequency, no IDF weighting
   — IDF requires a larger corpus than a single window provides).
4. Compute pairwise cosine similarity for all stroke pairs in the window.
5. Summarise as:
   - ``mean_coherence``: arithmetic mean of all pairwise similarities.
   - ``median_coherence``: median of pairwise similarities.
   - ``min_coherence``: lowest pairwise similarity (the most divergent pair).
   - ``cohesion_index``: fraction of pairs above the ``coherence_threshold``.
   - ``thematic_centroid``: the centroid TF vector's top-k tokens, giving
     the dominant themes of the window.

Interpretation
--------------

=========================  =================================================
range                      meaning
=========================  =================================================
mean_coherence >= 0.35     focused — strokes orbit a common theme
mean_coherence 0.15–0.35   moderate — mixed focus, some thematic drift
mean_coherence < 0.15      scattered — strokes jump between unrelated topics
=========================  =================================================

* ``cohesion_index > 0.60`` — majority of stroke pairs are thematically related
* ``cohesion_index 0.30–0.60`` — partial alignment
* ``cohesion_index < 0.30`` — highly fragmented output

Edge cases
----------
* Fewer than 2 strokes → zeroed report.
* Empty text strokes → skipped; if all are empty, zeroed report.
* Single-token strokes → cosine similarity degrades to 0 or 1.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 722, 2026-11-19.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


# Common English stopwords to skip during tokenisation
_STOPWORDS = frozenset({
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
    'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been',
    'some', 'them', 'than', 'its', 'over', 'such', 'that', 'this',
    'with', 'will', 'each', 'from', 'they', 'into', 'more', 'other',
    'when', 'what', 'your', 'which', 'their', 'would', 'there', 'about',
    'could', 'where', 'after', 'those', 'these', 'being', 'while',
    'also', 'just', 'only', 'very', 'like', 'most', 'then', 'well',
    'much', 'here', 'still', 'even', 'back', 'should', 'because',
    'through', 'between', 'before', 'does', 'however', 'every',
})


@dataclass
class CoherenceReport:
    """Result of thematic coherence analysis."""

    total_strokes: int = 0
    valid_strokes: int = 0
    pairwise_similarities: List[float] = field(default_factory=list)
    mean_coherence: float = 0.0
    median_coherence: float = 0.0
    min_coherence: float = 0.0
    cohesion_index: float = 0.0
    thematic_centroid: List[Tuple[str, float]] = field(default_factory=list)
    vocabulary_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to plain dict."""
        return {
            'total_strokes': self.total_strokes,
            'valid_strokes': self.valid_strokes,
            'mean_coherence': round(self.mean_coherence, 4),
            'median_coherence': round(self.median_coherence, 4),
            'min_coherence': round(self.min_coherence, 4),
            'cohesion_index': round(self.cohesion_index, 4),
            'thematic_centroid': [
                (tok, round(w, 4)) for tok, w in self.thematic_centroid
            ],
            'vocabulary_size': self.vocabulary_size,
            'num_pairs': len(self.pairwise_similarities),
        }

    def classify(self) -> str:
        """Classify thematic coherence level."""
        if self.mean_coherence >= 0.35:
            return 'focused'
        elif self.mean_coherence >= 0.15:
            return 'moderate'
        else:
            return 'scattered'

    def classify_cohesion(self) -> str:
        """Classify cohesion index."""
        if self.cohesion_index > 0.60:
            return 'aligned'
        elif self.cohesion_index > 0.30:
            return 'partial'
        else:
            return 'fragmented'


def _tokenise(text: str) -> List[str]:
    """Lowercase tokenise, strip punctuation and short stopwords."""
    tokens = re.findall(r'[a-z0-9_]+', text.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]


def _term_frequency(tokens: List[str]) -> Dict[str, float]:
    """Compute normalised term frequency vector."""
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {tok: cnt / total for tok, cnt in counts.items()}


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Cosine similarity between two sparse TF vectors."""
    if not vec_a or not vec_b:
        return 0.0

    # Dot product over shared keys
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    if not common_keys:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _centroid(vectors: List[Dict[str, float]], top_k: int = 10) -> List[Tuple[str, float]]:
    """Compute the centroid vector and return top-k tokens by weight."""
    if not vectors:
        return []

    # Sum all TF vectors
    combined: Dict[str, float] = {}
    for vec in vectors:
        for tok, weight in vec.items():
            combined[tok] = combined.get(tok, 0.0) + weight

    # Normalise by number of vectors
    n = len(vectors)
    for tok in combined:
        combined[tok] /= n

    # Sort by weight descending, return top-k
    sorted_tokens = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return sorted_tokens[:top_k]


def analyse_coherence(
    texts: Sequence[str],
    coherence_threshold: float = 0.20,
    top_k: int = 10,
) -> CoherenceReport:
    """Analyse thematic coherence of a batch of stroke texts.

    Parameters
    ----------
    texts : sequence of strings
        The stroke text content to analyse.
    coherence_threshold : float
        Similarity threshold above which a pair is considered coherent.
    top_k : int
        Number of top centroid tokens to include in the report.

    Returns
    -------
    CoherenceReport
        Analysis results.
    """
    total = len(texts)

    # Tokenise and compute TF vectors, skipping empty texts
    tf_vectors: List[Dict[str, float]] = []
    valid_texts: List[str] = []

    for text in texts:
        tokens = _tokenise(text)
        if tokens:
            tf_vectors.append(_term_frequency(tokens))
            valid_texts.append(text)

    n_valid = len(tf_vectors)

    if n_valid < 2:
        return CoherenceReport(
            total_strokes=total,
            valid_strokes=n_valid,
        )

    # Compute all pairwise cosine similarities
    similarities: List[float] = []
    for i in range(n_valid):
        for j in range(i + 1, n_valid):
            sim = _cosine_similarity(tf_vectors[i], tf_vectors[j])
            similarities.append(sim)

    # Summary statistics
    mean_coh = statistics.mean(similarities)
    median_coh = statistics.median(similarities)
    min_coh = min(similarities)

    # Cohesion index: fraction of pairs above threshold
    above_threshold = sum(1 for s in similarities if s >= coherence_threshold)
    cohesion = above_threshold / len(similarities) if similarities else 0.0

    # Thematic centroid
    centroid_tokens = _centroid(tf_vectors, top_k=top_k)

    # Vocabulary size
    vocab = set()
    for vec in tf_vectors:
        vocab.update(vec.keys())

    return CoherenceReport(
        total_strokes=total,
        valid_strokes=n_valid,
        pairwise_similarities=similarities,
        mean_coherence=mean_coh,
        median_coherence=median_coh,
        min_coherence=min_coh,
        cohesion_index=cohesion,
        thematic_centroid=centroid_tokens,
        vocabulary_size=len(vocab),
    )


def analyse_strokes_coherence(
    strokes: Sequence[dict],
    coherence_threshold: float = 0.20,
    top_k: int = 10,
) -> CoherenceReport:
    """Analyse coherence from stroke records (dicts with 'text' field).

    Parameters
    ----------
    strokes : sequence of stroke dicts
        Stroke records with 'text' field.
    coherence_threshold : float
        Similarity threshold for cohesion calculation.
    top_k : int
        Number of centroid tokens to report.

    Returns
    -------
    CoherenceReport
        Analysis results.
    """
    texts = []
    for s in strokes:
        text = s.get('text', '') or ''
        texts.append(text)

    return analyse_coherence(texts, coherence_threshold, top_k)


def analyse_sliding_windows(
    texts: Sequence[str],
    window_size: int = 10,
    coherence_threshold: float = 0.20,
) -> List[CoherenceReport]:
    """Analyse coherence across sliding windows of strokes.

    Useful for tracking how coherence evolves over time.

    Parameters
    ----------
    texts : sequence of strings
        Full stroke text sequence.
    window_size : int
        Number of strokes per window.
    coherence_threshold : float
        Similarity threshold.

    Returns
    -------
    list of CoherenceReport
        One report per window.
    """
    if len(texts) < window_size:
        return [analyse_coherence(texts, coherence_threshold)]

    reports = []
    for i in range(0, len(texts) - window_size + 1, max(1, window_size // 2)):
        window = texts[i:i + window_size]
        report = analyse_coherence(window, coherence_threshold)
        reports.append(report)

    return reports


if __name__ == '__main__':
    import json
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage: python stroke_thematic_coherence.py <strokes.jsonl> [window_size]")
        sys.exit(1)

    path = Path(sys.argv[1])
    window = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    strokes = []
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))

    texts = [s.get('text', '') for s in strokes]

    if len(texts) <= window:
        report = analyse_coherence(texts)
        print(f"Strokes: {report.total_strokes} (valid: {report.valid_strokes})")
        print(f"Coherence: mean={report.mean_coherence:.3f}  "
              f"median={report.median_coherence:.3f}  "
              f"min={report.min_coherence:.3f}")
        print(f"Cohesion index: {report.cohesion_index:.2f}")
        print(f"Classification: {report.classify()} / {report.classify_cohesion()}")
        print(f"Vocabulary: {report.vocabulary_size} tokens")
        print(f"\nThematic centroid (top 10):")
        for tok, weight in report.thematic_centroid:
            print(f"  {tok:20s}  {weight:.4f}")
    else:
        reports = analyse_sliding_windows(texts, window_size=window)
        print(f"Sliding window analysis ({len(reports)} windows of {window}):")
        print(f"{'Window':>8s}  {'Mean':>7s}  {'Median':>7s}  {'Cohesion':>8s}  {'Class':>10s}")
        for idx, r in enumerate(reports):
            start = idx * max(1, window // 2) + 1
            print(f"{start:8d}  {r.mean_coherence:7.3f}  {r.median_coherence:7.3f}  "
                  f"{r.cohesion_index:8.2f}  {r.classify():>10s}")
