#!/usr/bin/env python3
"""post_restart_clarity — did the writer come back sharper or duller?

When a writer process stalls and gets restarted, there's a moment of
truth: the first few strokes it produces afterwards.  Sometimes the
restart clears the fog and the writer comes back with fresh, diverse
content.  Other times it just regurgitates the same patterns that led
to the stall in the first place.

This module scores that transition.  It compares the last *N* strokes
**before** the stall with the first *N* strokes **after** the restart,
producing a ``clarity_score`` from 0 to 100:

==========  ============================================================
score       meaning
==========  ============================================================
80–100      **clarified** — post-restart content is noticeably fresher
60–79       **refreshed** — modest improvement in diversity
40–59       **unchanged** — about the same quality before and after
20–39       **foggy** — post-restart content is more repetitive
0–19        **stuck** — writer came back writing nearly identical stuff
==========  ============================================================

Signals analysed
----------------

- **vocabulary_delta**: change in unique-word ratio between windows
- **content_overlap**: Jaccard similarity of n-gram sets
- **length_variance**: does the writer vary sentence length or drone on?
- **topic_shift**: how different are the topics (via word-set distance)?
- **repetition_rate**: fraction of post-restart strokes that echo pre-stall

Usage::

    from iamai.post_restart_clarity import clarity_report

    pre = ["the repo accumulates files like a landfill", ...]
    post = ["naming things is the hardest part of design", ...]

    report = clarity_report(pre_strokes=pre, post_strokes=post)
    print(report.score)     # 72
    print(report.verdict)   # "refreshed"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_STOP_WORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "and", "but",
    "or", "nor", "not", "so", "yet", "both", "either", "neither", "each",
    "every", "all", "any", "few", "more", "most", "other", "some", "such",
    "no", "only", "own", "same", "than", "too", "very", "just", "because",
    "if", "when", "where", "how", "what", "which", "who", "whom", "this",
    "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "about", "up", "out", "then", "also", "like",
}


def _tokenize(text: str) -> List[str]:
    """Lowercase tokenise, stripping punctuation and stop words."""
    words = re.findall(r"[a-z']+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _bigrams(tokens: List[str]) -> List[str]:
    """Generate bigram strings from a token list."""
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def _vocabulary_richness(tokens: List[str]) -> float:
    """Type-token ratio (unique / total), 0.0–1.0."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def _jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Individual signals
# ---------------------------------------------------------------------------

def signal_vocabulary_delta(
    pre_tokens: List[str], post_tokens: List[str],
) -> float:
    """Positive when post-restart vocabulary is richer.

    Returns a value in [-1.0, 1.0]:
      +1.0  post is much richer
       0.0  same richness
      -1.0  post is much poorer
    """
    pre_rich = _vocabulary_richness(pre_tokens)
    post_rich = _vocabulary_richness(post_tokens)
    if pre_rich == 0.0 and post_rich == 0.0:
        return 0.0
    return post_rich - pre_rich


def signal_content_overlap(
    pre_tokens: List[str], post_tokens: List[str],
) -> float:
    """Jaccard overlap of bigram sets, inverted so lower overlap = higher score.

    Returns 0.0–1.0 where 1.0 means completely different content.
    """
    pre_bg = set(_bigrams(pre_tokens))
    post_bg = set(_bigrams(post_tokens))
    return 1.0 - _jaccard(pre_bg, post_bg)


def signal_length_variance(texts: Sequence[str]) -> float:
    """Coefficient of variation of text lengths (normalised 0–1).

    Higher = more varied sentence lengths = more human-like writing.
    Capped at 1.0.
    """
    if len(texts) < 2:
        return 0.0
    lengths = [len(t.split()) for t in texts]
    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return 0.0
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    cv = (variance ** 0.5) / mean
    return min(cv, 1.0)


def signal_topic_shift(
    pre_tokens: List[str], post_tokens: List[str],
) -> float:
    """Word-set distance: how different are the vocabularies?

    Returns 0.0–1.0 where 1.0 means completely different word sets.
    """
    pre_set = set(pre_tokens)
    post_set = set(post_tokens)
    return 1.0 - _jaccard(pre_set, post_set)


def signal_repetition_rate(
    pre_texts: Sequence[str], post_texts: Sequence[str],
) -> float:
    """Fraction of post-restart texts that are near-duplicates of pre-stall.

    Uses bigram Jaccard > 0.6 as "near-duplicate" threshold.
    Returns 0.0–1.0 where 0.0 means no repetition (good).
    """
    if not post_texts:
        return 0.0
    pre_bg_sets = [set(_bigrams(_tokenize(t))) for t in pre_texts]
    echoes = 0
    for post_text in post_texts:
        post_bg = set(_bigrams(_tokenize(post_text)))
        for pre_bg in pre_bg_sets:
            if _jaccard(post_bg, pre_bg) > 0.6:
                echoes += 1
                break
    return echoes / len(post_texts)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

@dataclass
class ClarityReport:
    """Result of a post-restart clarity analysis."""
    score: int  # 0–100
    verdict: str  # clarified / refreshed / unchanged / foggy / stuck
    signals: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"score": self.score, "verdict": self.verdict, "signals": self.signals}


def _score_to_verdict(score: int) -> str:
    """Map numeric score to qualitative verdict."""
    if score >= 80:
        return "clarified"
    if score >= 60:
        return "refreshed"
    if score >= 40:
        return "unchanged"
    if score >= 20:
        return "foggy"
    return "stuck"


def _compute_score(
    vocab_delta: float,
    content_overlap: float,
    post_length_var: float,
    topic_shift: float,
    repetition_rate: float,
) -> int:
    """Combine signals into a 0–100 score.

    Weights:
      content_overlap    30%  — most important: is the content actually different?
      repetition_rate    25%  — penalise echo-chamber restarts
      vocabulary_delta   20%  — richness improvement
      topic_shift        15%  — how far did topics move?
      length_variance    10%  — writing rhythm variety
    """
    # Normalise vocab_delta from [-1,1] to [0,1]
    vocab_norm = (vocab_delta + 1.0) / 2.0

    raw = (
        content_overlap * 0.30
        + (1.0 - repetition_rate) * 0.25
        + vocab_norm * 0.20
        + topic_shift * 0.15
        + post_length_var * 0.10
    )
    return max(0, min(100, int(round(raw * 100))))


def clarity_report(
    pre_strokes: Sequence[str],
    post_strokes: Sequence[str],
) -> ClarityReport:
    """Analyse post-restart clarity.

    Parameters
    ----------
    pre_strokes : sequence of str
        The last N stroke texts before the stall.
    post_strokes : sequence of str
        The first N stroke texts after the restart.

    Returns
    -------
    ClarityReport with score, verdict, and individual signal values.
    """
    pre_tokens = _tokenize(" ".join(pre_strokes))
    post_tokens = _tokenize(" ".join(post_strokes))

    vocab_delta = signal_vocabulary_delta(pre_tokens, post_tokens)
    content_overlap = signal_content_overlap(pre_tokens, post_tokens)
    post_length_var = signal_length_variance(post_strokes)
    topic_shift_val = signal_topic_shift(pre_tokens, post_tokens)
    repetition_rate = signal_repetition_rate(pre_strokes, post_strokes)

    score = _compute_score(
        vocab_delta, content_overlap, post_length_var,
        topic_shift_val, repetition_rate,
    )

    signals = {
        "vocabulary_delta": round(vocab_delta, 4),
        "content_overlap": round(content_overlap, 4),
        "length_variance": round(post_length_var, 4),
        "topic_shift": round(topic_shift_val, 4),
        "repetition_rate": round(repetition_rate, 4),
    }

    return ClarityReport(
        score=score,
        verdict=_score_to_verdict(score),
        signals=signals,
    )


def clarity_over_time(
    stroke_texts: Sequence[str],
    restart_indices: Sequence[int],
    window: int = 5,
) -> List[ClarityReport]:
    """Track clarity across multiple restarts in a stroke log.

    Parameters
    ----------
    stroke_texts : sequence of str
        All stroke texts in chronological order.
    restart_indices : sequence of int
        Indices into stroke_texts where a restart occurred.
    window : int
        Number of strokes to compare on each side of the restart.

    Returns
    -------
    List of ClarityReport, one per restart index.
    """
    reports = []
    for idx in restart_indices:
        pre_start = max(0, idx - window)
        pre = stroke_texts[pre_start:idx]
        post_end = min(len(stroke_texts), idx + window)
        post = stroke_texts[idx:post_end]
        if pre and post:
            reports.append(clarity_report(pre, post))
    return reports
