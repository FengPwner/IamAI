#!/usr/bin/env python3
"""writer_transitions — measure how smoothly prose flows between adjacent units.

Transitions track the *connective tissue* between sentences and
paragraphs.  Well-transitioned prose guides the reader from one idea
to the next with explicit bridges: transitional words ("however",
"therefore"), logical connectives ("because", "although"), shared
vocabulary that ties adjacent sentences together, and topic sentences
that orient the reader at paragraph boundaries.  Poorly-transitioned
prose feels choppy — each sentence arrives without warning, each
paragraph begins in a new place with no link to what came before.

This module is orthogonal to the other writer metrics:

- **coherence** tracks *logical flow of ideas*.  Coherent prose has
  ideas that connect meaningfully.  Transitions measure the *surface
  devices* that signal connections — a text can be logically coherent
  but lack explicit transitions (relying on the reader to infer
  connections), or have many transitional words while being logically
  disjointed ("therefore" between unrelated claims).

- **linearity** tracks *forward progression*.  Linear prose advances;
  non-linear prose circles.  Transitions measure *how* the advance
  happens — whether adjacent units are bridged — not *whether* they
  advance.  A text can be highly linear (each sentence adds new
  information) but poorly transitioned (no connective tissue between
  additions).

- **cohesion** tracks *discourse-level reference chains* — pronouns
  pointing to antecedents, ellipsis, substitution.  Transitions
  measure *explicit connective devices* at sentence and paragraph
  boundaries, not reference chains within a paragraph.

- **concision** tracks *word economy*.  Transitional words cost tokens.
  A text can be concise (few words) while being well-transitioned
  ("but", "so") or verbose (many words) while being choppy (no
  connectives).  Concision measures length; transitions measure flow.

Transitions ask: **does the reader feel guided from one unit to the
next, or dropped into each sentence cold?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
transitional_word_rate       fraction of sentence boundaries preceded by
                             a transitional word or phrase (however,
                             therefore, moreover, furthermore, likewise,
                             conversely, nevertheless, accordingly, etc.);
                             counts the word at sentence start or within
                             the first clause
logical_connector_density    fraction of sentences containing at least
                             one logical connective (because, since,
                             although, though, while, if, unless, despite,
                             whereas, provided that, in order to) that
                             signals a causal, concessive, conditional,
                             or purposive relationship
semantic_bridge_ratio        fraction of consecutive sentence pairs that
                             share at least one content word (noun, verb,
                             adjective — excluding function words); shared
                             vocabulary creates implicit cohesion even
                             without explicit transitional devices
temporal_sequence_rate       fraction of sentences containing a temporal
                             marker (before, after, then, meanwhile,
                             subsequently, previously, simultaneously,
                             thereafter, meanwhile) relative to all
                             sentences; relevant for narrative and
                             procedural prose
paragraph_transition_density fraction of paragraph breaks where the
                             opening sentence of the new paragraph
                             contains an explicit transition: a
                             transitional word, a logical connective,
                             a repeated key term from the preceding
                             paragraph's final sentence, or a
                             demonstrative pronoun pointing back
===========================  ===========================================

Transition classes
------------------

============  ============================================================
class         meaning
============  ============================================================
seamless      score >= 0.75 — every sentence boundary is bridged; the
              reader always knows how the next unit relates to the
              previous one
smooth        0.55 <= score < 0.75 — most transitions are explicit;
              occasional jumps that the reader can bridge with minimal
              effort
adequate      0.35 <= score < 0.55 — some transitions present but gaps
              between units where the reader must infer the connection
choppy        0.20 <= score < 0.35 — few transitions; sentences feel
              isolated, paragraphs begin without orientation
disjointed    score < 0.20 — almost no connective tissue; each unit
              arrives without warning, the reader is constantly
              disoriented
============  ============================================================
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRANSITIONAL_WORDS: frozenset[str] = frozenset({
    # additive
    "also", "besides", "furthermore", "likewise", "moreover",
    "similarly", "in addition", "what is more",
    # adversative / contrastive
    "conversely", "however", "instead", "nevertheless",
    "nonetheless", "on the contrary", "on the other hand",
    "rather", "still", "yet", "but",
    # causal / result
    "accordingly", "as a result", "consequently", "hence",
    "therefore", "thus", "as a consequence",
    # sequential / temporal
    "first", "second", "third", "finally", "lastly",
    "next", "then", "subsequently", "meanwhile",
    "previously", "simultaneously", "thereafter",
    # illustrative
    "for example", "for instance", "specifically",
    "in particular", "notably",
    # summary
    "in conclusion", "in summary", "to summarize",
    "overall", "in short", "in brief",
    # concessive
    "admittedly", "granted", "of course",
    # comparative
    "in the same way", "by the same token",
})

LOGICAL_CONNECTORS: frozenset[str] = frozenset({
    # causal
    "because", "since", "given that",
    "due to", "owing to", "on account of",
    # concessive
    "although", "though", "even though", "while", "whilst",
    "despite", "in spite of", "notwithstanding",
    # conditional
    "if", "unless", "provided that", "as long as",
    "in case", "whether",
    # purposive
    "in order to", "so that", "so as to",
    # resultative
    "so", "therefore", "thus", "hence",
    # comparative
    "whereas", "while", "compared to", "rather than",
})

TEMPORAL_MARKERS: frozenset[str] = frozenset({
    "before", "after", "then", "meanwhile", "subsequently",
    "previously", "simultaneously", "thereafter", "formerly",
    "lately", "recently", "currently", "immediately",
    "afterward", "afterwards", "beforehand", "earlier",
    "eventually", "ultimately", "initially", "originally",
    "nowadays", "presently", "shortly", "suddenly",
    "in the meantime", "at the same time",
})

# Function words to exclude from content-word overlap computation
FUNCTION_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "this", "that", "these", "those",
    "i", "me", "my", "mine", "we", "us", "our", "ours",
    "you", "your", "yours", "he", "him", "his", "she", "her",
    "hers", "it", "its", "they", "them", "their", "theirs",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "will", "would", "shall", "should", "may", "might", "must",
    "can", "could",
    "and", "but", "or", "nor", "for", "yet", "so",
    "at", "by", "in", "of", "on", "to", "up", "as", "if",
    "it", "not", "no", "with", "from", "into", "out", "about",
    "over", "under", "between", "through", "during", "before",
    "after", "above", "below",
    "very", "really", "just", "also", "too", "quite",
    "more", "most", "less", "least",
    "there", "here", "where", "when", "how", "why", "what",
    "which", "who", "whom", "whose",
})

# Sentence boundary pattern
_SENTENCE_END = re.compile(r'[.!?]\s+')
# Paragraph boundary
_PARA_BREAK = re.compile(r'\n\s*\n')
# Word extraction (lowercase, alpha-only)
_WORD_RE = re.compile(r"[a-z']+")
# Sentence-initial position (first 8 words)
_INITIAL_WINDOW = 8


# ---------------------------------------------------------------------------
# Text segmentation helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, handling edge cases."""
    if not text or not isinstance(text, str):
        return []
    text = text.strip()
    if not text:
        return []
    parts = _SENTENCE_END.split(text)
    return [s.strip() for s in parts if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    if not text or not isinstance(text, str):
        return []
    paras = _PARA_BREAK.split(text.strip())
    return [p.strip() for p in paras if p.strip()]


def _words(text: str) -> list[str]:
    """Extract lowercase words from text."""
    return _WORD_RE.findall(text.lower())


def _content_words(text: str) -> set[str]:
    """Extract content words (non-function words) from text."""
    return {w for w in _words(text) if w not in FUNCTION_WORDS and len(w) > 1}


def _multiword_match(text_lower: str, phrases: frozenset[str]) -> int:
    """Count how many multi-word phrases appear in text (lowercased)."""
    count = 0
    for phrase in phrases:
        if " " in phrase and phrase in text_lower:
            count += 1
    return count


def _singleword_match(words_list: list[str], phrases: frozenset[str]) -> int:
    """Count single-word phrase matches at sentence-initial position."""
    count = 0
    for phrase in phrases:
        if " " not in phrase and phrase in words_list[:_INITIAL_WINDOW]:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Sub-metric computations
# ---------------------------------------------------------------------------

def compute_transitional_word_rate(text: str) -> float:
    """Fraction of sentences starting with a transitional word/phrase.

    Checks the first few words of each sentence for the presence of
    any transitional word or phrase from the curated list.  Single-
    sentence texts return 0.0 (no boundary to bridge).
    """
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return 0.0
    count = 0
    for sent in sentences[1:]:  # skip the first sentence (no prior boundary)
        sent_lower = sent.lower()
        sent_words = _words(sent)
        # Check multi-word phrases first
        if _multiword_match(sent_lower, TRANSITIONAL_WORDS) > 0:
            count += 1
            continue
        # Check single-word transitions in initial window
        if _singleword_match(sent_words, TRANSITIONAL_WORDS) > 0:
            count += 1
    return count / (len(sentences) - 1)


def compute_logical_connector_density(text: str) -> float:
    """Fraction of sentences containing a logical connective.

    A logical connective signals a causal, concessive, conditional,
    or purposive relationship.  Each sentence is scored independently.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 0.0
    count = 0
    for sent in sentences:
        sent_lower = sent.lower()
        sent_words = _words(sent)
        if _multiword_match(sent_lower, LOGICAL_CONNECTORS) > 0:
            count += 1
            continue
        # Check single-word connectors anywhere in the sentence
        found = False
        for connector in LOGICAL_CONNECTORS:
            if " " not in connector and connector in sent_words:
                found = True
                break
        if found:
            count += 1
    return count / len(sentences)


def compute_semantic_bridge_ratio(text: str) -> float:
    """Fraction of consecutive sentence pairs sharing a content word.

    For each pair (sentence_i, sentence_{i+1}), compute the set of
    content words in each.  If the intersection is non-empty, the
    pair is "bridged".  Returns bridged_pairs / total_pairs.
    """
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return 0.0
    pairs = len(sentences) - 1
    bridged = 0
    prev_words = _content_words(sentences[0])
    for sent in sentences[1:]:
        curr_words = _content_words(sent)
        if prev_words & curr_words:
            bridged += 1
        prev_words = curr_words
    return bridged / pairs


def compute_temporal_sequence_rate(text: str) -> float:
    """Fraction of sentences containing a temporal marker.

    Relevant for narrative and procedural prose.  Expository or
    argumentative text may legitimately score low here.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 0.0
    count = 0
    for sent in sentences:
        sent_lower = sent.lower()
        sent_words = _words(sent)
        if _multiword_match(sent_lower, TEMPORAL_MARKERS) > 0:
            count += 1
            continue
        found = False
        for marker in TEMPORAL_MARKERS:
            if " " not in marker and marker in sent_words:
                found = True
                break
        if found:
            count += 1
    return count / len(sentences)


def compute_paragraph_transition_density(text: str) -> float:
    """Fraction of paragraph breaks with an explicit transition.

    A paragraph break is "transitioned" when the opening sentence
    of the new paragraph contains:
    - a transitional word/phrase, OR
    - a logical connective, OR
    - a content word shared with the last sentence of the prior
      paragraph, OR
    - a demonstrative pronoun (this/that/these/those) pointing back
    """
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) <= 1:
        return 0.0

    transitions_found = 0
    breaks = len(paragraphs) - 1

    for i in range(1, len(paragraphs)):
        prev_para = paragraphs[i - 1]
        curr_para = paragraphs[i]

        # Get the opening sentence of the new paragraph
        curr_sentences = _split_sentences(curr_para)
        if not curr_sentences:
            continue
        opening = curr_sentences[0].lower()
        opening_words = _words(opening)

        # Check transitional words
        has_transition = False
        if _multiword_match(opening, TRANSITIONAL_WORDS) > 0:
            has_transition = True
        elif _singleword_match(opening_words, TRANSITIONAL_WORDS) > 0:
            has_transition = True

        # Check logical connectors
        if not has_transition:
            if _multiword_match(opening, LOGICAL_CONNECTORS) > 0:
                has_transition = True
            else:
                for conn in LOGICAL_CONNECTORS:
                    if " " not in conn and conn in opening_words:
                        has_transition = True
                        break

        # Check shared content words with prior paragraph's last sentence
        if not has_transition:
            prev_sentences = _split_sentences(prev_para)
            if prev_sentences:
                prev_last_words = _content_words(prev_sentences[-1])
                curr_opening_words = _content_words(curr_sentences[0])
                if prev_last_words & curr_opening_words:
                    has_transition = True

        # Check demonstrative pronouns
        if not has_transition:
            demonstratives = {"this", "that", "these", "those", "such"}
            if demonstratives & set(opening_words[:_INITIAL_WINDOW]):
                has_transition = True

        if has_transition:
            transitions_found += 1

    return transitions_found / breaks


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------

# Weights for the composite transition_index
_WEIGHTS = {
    "transitional_word_rate": 0.20,
    "logical_connector_density": 0.15,
    "semantic_bridge_ratio": 0.25,
    "temporal_sequence_rate": 0.10,
    "paragraph_transition_density": 0.30,
}


def compute_transition_metrics(text: str) -> dict[str, float]:
    """Compute all five transition sub-metrics."""
    return {
        "transitional_word_rate": compute_transitional_word_rate(text),
        "logical_connector_density": compute_logical_connector_density(text),
        "semantic_bridge_ratio": compute_semantic_bridge_ratio(text),
        "temporal_sequence_rate": compute_temporal_sequence_rate(text),
        "paragraph_transition_density": compute_paragraph_transition_density(text),
    }


def compute_transition_index(metrics: dict[str, float]) -> float:
    """Weighted composite of transition sub-metrics.

    Each metric is already in [0, 1].  The index is a weighted sum,
    also in [0, 1].  Higher = better transitioned prose.
    """
    score = 0.0
    for key, weight in _WEIGHTS.items():
        score += metrics.get(key, 0.0) * weight
    return round(score, 4)


def classify_transitions(index: float) -> str:
    """Classify the transition index into a quality label."""
    if index >= 0.75:
        return "seamless"
    if index >= 0.55:
        return "smooth"
    if index >= 0.35:
        return "adequate"
    if index >= 0.20:
        return "choppy"
    return "disjointed"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def analyze_transitions(text: str) -> dict[str, Any]:
    """Full transition analysis pipeline."""
    metrics = compute_transition_metrics(text)
    index = compute_transition_index(metrics)
    label = classify_transitions(index)
    return {
        "metrics": metrics,
        "transition_index": index,
        "transition_class": label,
        "sentence_count": len(_split_sentences(text)),
        "paragraph_count": len(_split_paragraphs(text)),
    }


def format_transition_report(analysis: dict[str, Any]) -> str:
    """Human-readable transition report."""
    m = analysis["metrics"]
    lines = [
        f"Transitions: {analysis['transition_class']} ({analysis['transition_index']:.2f})",
        f"  Transitional word rate:        {m['transitional_word_rate']:.3f}",
        f"  Logical connector density:     {m['logical_connector_density']:.3f}",
        f"  Semantic bridge ratio:         {m['semantic_bridge_ratio']:.3f}",
        f"  Temporal sequence rate:        {m['temporal_sequence_rate']:.3f}",
        f"  Paragraph transition density:  {m['paragraph_transition_density']:.3f}",
        f"  ({analysis['sentence_count']} sentences, {analysis['paragraph_count']} paragraphs)",
    ]
    return "\n".join(lines)
