#!/usr/bin/env python3
"""writer_linearity — measure whether prose advances or circles in place.

Linearity tracks the *forward progression* of ideas through a text.
Linear prose moves from point A to point B to point C: each sentence
introduces information the reader did not already know, each paragraph
advances the argument or narrative.  Non-linear prose loops: the same
idea rephrased three ways, the same question asked and re-asked, the
same scene described from angles that add no new information.

This module is orthogonal to the other writer metrics:

- **momentum** tracks *stroke-level* build-up — whether the writer's
  next action extends the previous one.  Linearity tracks *within-text*
  progression — whether sentence N+1 says something sentence N did not
  already say.  A writer can have high momentum (always extending
  recent work) while producing non-linear prose (circling the same
  idea within each piece).

- **coherence** tracks *logical flow between sentences*.  Coherent text
  has ideas that connect logically.  Linear text has ideas that
  *advance* — each sentence adds something new.  A text can be
  coherent (ideas connect) while being non-linear (the same idea
  restated with different connectives: "because X, therefore X, in
  other words X").

- **concision** tracks *word economy*.  Concise text uses the fewest
  words needed.  Linear text moves forward.  A text can be concise
  ("stop. halt. cease. desist.") while being non-linear (four words,
  one idea).  Concision measures length; linearity measures progress.

- **topic_drift** tracks *thematic wandering*.  A text can drift off
  topic while being perfectly linear (each paragraph introduces a
  genuinely new sub-topic).  A text can stay on topic while being
  non-linear (circling the same point for ten paragraphs).  Topic
  drift measures thematic focus; linearity measures informational
  progress.

Linearity asks: **does the reader know something after sentence N+1
that they did not know after sentence N?**

Dimensions
----------

========================  ==============================================
metric                    meaning
========================  ==============================================
back_reference_density    fraction of sentences that primarily refer
                          back to information already stated rather than
                          introducing new content; detected via
                          anaphoric patterns (this/that/these/those +
                          previously mentioned noun), restatement
                          markers ("in other words", "that is", "i.e."),
                          and echo patterns (same content words as
                          preceding 2 sentences)
rephrasing_loop_rate      fraction of consecutive sentence pairs where
                          the later sentence restates the earlier one
                          with different words but no new information;
                          detected via high word overlap after removing
                          function words + absence of new content words
                          not present in the preceding sentence
idea_recursion_rate       fraction of paragraphs that return to an idea
                          already covered earlier in the same paragraph;
                          detected by clustering content words into
                          idea-groups and measuring revisits
forward_build_ratio       fraction of sentences that introduce at least
                          one content word not present in any of the
                          preceding 3 sentences; the core "does this
                          add something new?" measure
paragraph_drift_rate      fraction of paragraph-internal sentence
                          transitions where the topic shifts without
                          advancing (measured by content-word Jaccard
                          similarity between consecutive sentences
                          below threshold + absence of temporal or
                          causal connectives)
========================  ==============================================

Linearity classes
-----------------

==============  ============================================================
class           meaning
==============  ============================================================
arrow           score ≥ 0.75 — prose moves decisively forward; each
                sentence builds on the last with new information; the
                reader is always learning something
river             0.55 ≤ score < 0.75 — healthy forward flow with
                occasional eddies; the writer sometimes circles back
                for emphasis but mostly advances
meandering      0.35 ≤ score < 0.55 — frequent loops and restatements
                interrupt forward progress; the reader often feels they
                have read this before
stagnant        score < 0.35 — prose circles in place; the same ideas
                recur without development; reading feels like treading
                water
==============  ============================================================
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FUNCTION_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "nor", "for", "yet", "so",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "will", "would", "shall", "should", "may",
    "might", "must", "can", "could", "have", "has", "had",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him",
    "his", "she", "her", "it", "its", "they", "them", "their",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "in", "on", "at", "to", "from", "by", "with", "of", "about",
    "as", "if", "then", "than", "when", "where", "how", "why",
    "not", "no", "yes", "all", "each", "every", "both", "few",
    "more", "most", "some", "any", "such", "only", "own", "same",
    "just", "also", "very", "too", "quite", "rather",
    "because", "since", "although", "though", "while", "whereas",
    "therefore", "thus", "hence", "consequently", "however",
    "nevertheless", "nonetheless", "instead", "meanwhile",
    "furthermore", "moreover", "additionally", "besides",
})

BACK_REFERENCE_PATTERNS = [
    re.compile(r"\b(?:this|that|these|those)\s+(?:same|very|particular)\b", re.I),
    re.compile(r"\bin other words\b", re.I),
    re.compile(r"\bthat is(?:\s+to say)?\b", re.I),
    re.compile(r"\bi\.e\.", re.I),
    re.compile(r"\bas (?:mentioned|noted|stated|said|discussed|described) (?:above|before|earlier|previously)\b", re.I),
    re.compile(r"\b(?:same|aforementioned|above-mentioned)\b", re.I),
    re.compile(r"\bgoing back to\b", re.I),
    re.compile(r"\bas (?:we|I) (?:saw|said|noted|mentioned)\b", re.I),
]

TEMPORAL_CONNECTIVES = re.compile(
    r"\b(?:then|next|after|later|subsequently|following|now|today|"
    r"currently|recently|meanwhile|simultaneously|finally|lastly|"
    r"first|second|third|finally)\b", re.I
)

CAUSAL_CONNECTIVES = re.compile(
    r"\b(?:because|therefore|thus|hence|consequently|so|as a result|"
    r"accordingly|for this reason|due to|caused by|leads to|"
    r"results in|produces|generates|creates|enables)\b", re.I
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using conservative heuristics."""
    if not text or not isinstance(text, str):
        return []
    # Handle common abbreviations before splitting
    normalized = re.sub(r"(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|i\.e|e\.g)\.", "§", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[]|[-—])", normalized)
    result = []
    for p in parts:
        cleaned = p.replace("§", ".").strip()
        if cleaned and len(cleaned) > 5:
            result.append(cleaned)
    return result


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    if not text or not isinstance(text, str):
        return []
    parts = re.split(r"\n\s*\n", text)
    result = []
    for p in parts:
        cleaned = p.strip()
        if cleaned and len(cleaned) > 10:
            result.append(cleaned)
    return result


def _content_words(text: str) -> set[str]:
    """Extract lowercased content words (non-function, length ≥ 3)."""
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {w for w in words if w not in FUNCTION_WORDS}


def _word_overlap(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two word sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def compute_back_reference_density(sentences: list[str]) -> float:
    """Fraction of sentences containing back-reference patterns.

    Back references signal that the sentence is primarily about
    previously stated information rather than new content.
    """
    if not sentences:
        return 0.0
    count = 0
    for s in sentences:
        for pat in BACK_REFERENCE_PATTERNS:
            if pat.search(s):
                count += 1
                break
    return count / len(sentences)


def compute_rephrasing_loop_rate(sentences: list[str]) -> float:
    """Fraction of consecutive pairs where the later restates the earlier.

    A rephrasing loop is detected when:
    1. Content-word Jaccard similarity > 0.40 (high overlap)
    2. The later sentence introduces fewer than 2 new content words
    3. The later sentence is not shorter than half the earlier one
       (to avoid counting legitimate summaries)
    """
    if len(sentences) < 2:
        return 0.0
    loops = 0
    pairs = 0
    for i in range(1, len(sentences)):
        words_prev = _content_words(sentences[i - 1])
        words_curr = _content_words(sentences[i])
        if not words_prev or not words_curr:
            continue
        pairs += 1
        overlap = _word_overlap(words_prev, words_curr)
        new_words = words_curr - words_prev
        len_ratio = len(sentences[i]) / max(len(sentences[i - 1]), 1)
        if overlap > 0.40 and len(new_words) < 2 and len_ratio >= 0.5:
            loops += 1
    return loops / pairs if pairs else 0.0


def compute_idea_recursion_rate(paragraphs: list[str]) -> float:
    """Fraction of paragraphs that revisit an earlier idea internally.

    An idea revisit is detected when a sentence's content words overlap
    heavily (>0.50 Jaccard) with a non-adjacent earlier sentence in the
    same paragraph, while the intervening sentences cover different
    content.
    """
    if not paragraphs:
        return 0.0
    recursive_count = 0
    for para in paragraphs:
        sents = _split_sentences(para)
        if len(sents) < 3:
            continue
        sent_words = [_content_words(s) for s in sents]
        has_recursion = False
        for i in range(2, len(sents)):
            for j in range(0, i - 1):
                overlap = _word_overlap(sent_words[i], sent_words[j])
                if overlap > 0.50:
                    # Check that intervening sentences are different
                    intervening_different = True
                    for k in range(j + 1, i):
                        mid_overlap = _word_overlap(sent_words[k], sent_words[j])
                        if mid_overlap > 0.50:
                            intervening_different = False
                            break
                    if intervening_different:
                        has_recursion = True
                        break
            if has_recursion:
                break
        if has_recursion:
            recursive_count += 1
    return recursive_count / len(paragraphs)


def compute_forward_build_ratio(sentences: list[str]) -> float:
    """Fraction of sentences introducing at least one new content word.

    A sentence is 'building forward' if it contains at least one content
    word not present in any of the preceding ``window`` sentences.
    """
    if not sentences:
        return 0.0
    window = 3
    building = 0
    for i in range(len(sentences)):
        current_words = _content_words(sentences[i])
        if not current_words:
            continue
        # Gather context words from preceding window
        context = set()
        for j in range(max(0, i - window), i):
            context |= _content_words(sentences[j])
        new_words = current_words - context
        if i == 0 or new_words:
            building += 1
    return building / len(sentences)


def compute_paragraph_drift_rate(paragraphs: list[str]) -> float:
    """Fraction of sentence transitions that shift without advancing.

    A drift is detected when consecutive sentences have low content-word
    overlap (< 0.15 Jaccard) AND neither temporal nor causal connectives
    bridge them.  This signals a topic shift without logical progression.
    """
    if not paragraphs:
        return 0.0
    total_transitions = 0
    drift_transitions = 0
    for para in paragraphs:
        sents = _split_sentences(para)
        for i in range(1, len(sents)):
            words_prev = _content_words(sents[i - 1])
            words_curr = _content_words(sents[i])
            if not words_prev or not words_curr:
                continue
            total_transitions += 1
            overlap = _word_overlap(words_prev, words_curr)
            has_temporal = bool(TEMPORAL_CONNECTIVES.search(sents[i]))
            has_causal = bool(CAUSAL_CONNECTIVES.search(sents[i]))
            if overlap < 0.15 and not has_temporal and not has_causal:
                drift_transitions += 1
    return drift_transitions / total_transitions if total_transitions else 0.0


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

WEIGHTS = {
    "back_reference": 0.20,
    "rephrasing_loop": 0.25,
    "idea_recursion": 0.20,
    "forward_build": 0.25,
    "paragraph_drift": 0.10,
}


def compute_linearity_metrics(text: str) -> dict[str, float]:
    """Compute all linearity sub-metrics from raw text."""
    sentences = _split_sentences(text)
    paragraphs = _split_paragraphs(text)

    back_ref = compute_back_reference_density(sentences)
    rephrasing = compute_rephrasing_loop_rate(sentences)
    recursion = compute_idea_recursion_rate(paragraphs)
    forward = compute_forward_build_ratio(sentences)
    drift = compute_paragraph_drift_rate(paragraphs)

    return {
        "back_reference_density": round(back_ref, 4),
        "rephrasing_loop_rate": round(rephrasing, 4),
        "idea_recursion_rate": round(recursion, 4),
        "forward_build_ratio": round(forward, 4),
        "paragraph_drift_rate": round(drift, 4),
    }


def compute_linearity_index(metrics: dict[str, float]) -> float:
    """Weighted composite: higher = more linear prose.

    Forward build ratio contributes positively; the others are inverted
    (high back-reference, rephrasing, recursion, drift → lower score).
    """
    score = (
        WEIGHTS["forward_build"] * metrics.get("forward_build_ratio", 0.5)
        + WEIGHTS["back_reference"] * (1.0 - metrics.get("back_reference_density", 0.0))
        + WEIGHTS["rephrasing_loop"] * (1.0 - metrics.get("rephrasing_loop_rate", 0.0))
        + WEIGHTS["idea_recursion"] * (1.0 - metrics.get("idea_recursion_rate", 0.0))
        + WEIGHTS["paragraph_drift"] * (1.0 - metrics.get("paragraph_drift_rate", 0.0))
    )
    return round(score, 4)


def classify_linearity(score: float) -> str:
    """Map composite score to a human-readable class."""
    if score >= 0.75:
        return "arrow"
    if score >= 0.55:
        return "river"
    if score >= 0.35:
        return "meandering"
    return "stagnant"


def analyze_linearity(text: str) -> dict[str, Any]:
    """Full linearity analysis pipeline."""
    metrics = compute_linearity_metrics(text)
    index = compute_linearity_index(metrics)
    label = classify_linearity(index)
    return {
        "metrics": metrics,
        "linearity_index": index,
        "linearity_class": label,
        "sentence_count": len(_split_sentences(text)),
        "paragraph_count": len(_split_paragraphs(text)),
    }


def format_linearity_report(analysis: dict[str, Any]) -> str:
    """Human-readable linearity report."""
    m = analysis["metrics"]
    lines = [
        f"Linearity: {analysis['linearity_class']} ({analysis['linearity_index']:.2f})",
        f"  Forward build ratio:    {m['forward_build_ratio']:.3f}",
        f"  Back-reference density:  {m['back_reference_density']:.3f}",
        f"  Rephrasing loop rate:    {m['rephrasing_loop_rate']:.3f}",
        f"  Idea recursion rate:     {m['idea_recursion_rate']:.3f}",
        f"  Paragraph drift rate:    {m['paragraph_drift_rate']:.3f}",
        f"  ({analysis['sentence_count']} sentences, {analysis['paragraph_count']} paragraphs)",
    ]
    return "\n".join(lines)
