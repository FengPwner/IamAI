#!/usr/bin/env python3
"""writer_sentence_variety — measure the structural diversity of prose.

Sentence variety is the degree to which writing varies its syntactic
form — length, opening, clause structure, punctuation, and voice.
Monotonous prose repeats the same patterns; varied prose keeps the
reader engaged through structural surprise.

This is not a value judgment.  Children's books *should* have low
sentence variety — repetition aids comprehension.  Literary fiction
and essays often benefit from high variety.  The metric exists so
the writer can *see* whether their structural choices match their
intent — not to maximize it.

This module is orthogonal to the other writer metrics:

- **prose_rhythm** tracks *variation in sentence length and structure*
  at a rhythmic level.  Sentence variety is about *categorical*
  diversity (types of openings, clause patterns, punctuation marks)
  rather than continuous length variation.

- **pacing** tracks *information delivery speed*.  Pacing is about
  how fast content moves.  Sentence variety is about whether that
  speed is delivered through diverse or repetitive structures.

- **elegance** tracks *overall aesthetic quality*.  Elegance is a
  holistic judgment.  Sentence variety is one *ingredient* that may
  contribute to elegance but does not determine it: inelegant prose
  can be highly varied (chaotic), and elegant prose can be
  structurally uniform (minimalism).

- **musicality** tracks *phonetic texture*.  Musicality is about
  sound patterns within sentences.  Sentence variety is about
  *syntactic* patterns across sentences.

Sentence variety asks: **does the prose use diverse sentence
structures, or does it repeat the same patterns?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
length_variance              normalized variance of sentence word counts
                             (high = diverse lengths, low = uniform)
opening_diversity            fraction of unique sentence-opening words
                             (high = varied openings, low = repetitive)
clause_complexity            mix of simple, compound, and complex
                             sentence structures (balanced = high)
punctuation_variety          diversity of punctuation marks used
                             (high = varied, low = uniform)
voice_distribution           balance of active and passive constructions
                             (balanced = high, skewed = low)
===========================  ===========================================

From these five dimensions a composite **variety_index** is computed
as a weighted average and classified:

==============  ============================================================
class           meaning
==============  ============================================================
virtuosic       index >= 0.70 — masterful structural diversity
varied          0.50 <= index < 0.70 — good range of sentence structures
moderate        0.30 <= index < 0.50 — some structural diversity
uniform         0.15 <= index < 0.30 — limited structural variation
monotonous      index < 0.15 — highly repetitive sentence patterns
==============  ============================================================
"""

from __future__ import annotations

import re
import math
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum sentence length (words) to analyze
MIN_SENTENCE_LENGTH = 3

# Maximum sentence length (words) to analyze
MAX_SENTENCE_LENGTH = 200

# Thresholds for clause complexity
SIMPLE_CLAUSE_MAX = 1  # single independent clause
COMPOUND_CLAUSE_MIN = 2  # multiple independent clauses
COMPLEX_CLAUSE_MARKER = 3  # subordinating conjunction present

# Punctuation marks to track
PUNCTUATION_MARKS = {'.', '!', '?', ';', ':', '—', '–', '-', '…'}

# Passive voice indicators
PASSIVE_INDICATORS = [
    'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'am', 'has been', 'have been', 'had been',
    'will be', 'would be', 'could be', 'should be',
    'may be', 'might be', 'must be'
]

# Subordinating conjunctions (indicate complex sentences)
SUBORDINATING_CONJUNCTIONS = [
    'although', 'because', 'since', 'unless', 'while', 'whereas',
    'if', 'when', 'whenever', 'where', 'wherever', 'whether',
    'after', 'before', 'until', 'till', 'as', 'than',
    'though', 'even though', 'even if', 'in case', 'provided that'
]

# Coordinating conjunctions (indicate compound sentences)
COORDINATING_CONJUNCTIONS = ['and', 'but', 'or', 'nor', 'for', 'yet', 'so']


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation boundaries."""
    # Match sentence-ending punctuation followed by space or end
    pattern = r'[^.!?…]+[.!?…]+|\S+'
    raw = re.findall(pattern, text)
    return [s.strip() for s in raw if s.strip() and len(s.strip()) > 1]


def _tokenize_words(sentence: str) -> List[str]:
    """Extract words from a sentence, lowercased."""
    return re.findall(r"[a-zA-Z']+", sentence.lower())


def _compute_length_variance(sentences: List[str]) -> float:
    """Compute normalized variance of sentence word counts.
    
    Returns a value between 0 and 1, where:
    - 0 = all sentences have identical length
    - 1 = maximum variance (theoretical)
    """
    if len(sentences) < 2:
        return 0.0
    
    lengths = [len(_tokenize_words(s)) for s in sentences]
    lengths = [l for l in lengths if MIN_SENTENCE_LENGTH <= l <= MAX_SENTENCE_LENGTH]
    
    if len(lengths) < 2:
        return 0.0
    
    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return 0.0
    
    variance = sum((x - mean) ** 2 for x in lengths) / len(lengths)
    # Normalize by mean to get coefficient of variation squared
    cv_squared = variance / (mean ** 2)
    
    # Cap at 1.0 (typical range is 0-0.5 for most prose)
    return min(cv_squared / 0.5, 1.0)


def _compute_opening_diversity(sentences: List[str]) -> float:
    """Compute fraction of unique sentence-opening words.
    
    Returns a value between 0 and 1, where:
    - 0 = all sentences start with the same word
    - 1 = every sentence starts with a different word
    """
    if not sentences:
        return 0.0
    
    openings = []
    for s in sentences:
        words = _tokenize_words(s)
        if words:
            openings.append(words[0])
    
    if len(openings) < 2:
        return 1.0 if openings else 0.0
    
    unique = len(set(openings))
    return unique / len(openings)


def _classify_clause_structure(sentence: str) -> str:
    """Classify sentence as simple, compound, or complex.
    
    Returns one of: 'simple', 'compound', 'complex', 'compound-complex'
    """
    words = _tokenize_words(sentence)
    word_set = set(words)
    
    has_subordinating = any(conj in word_set for conj in SUBORDINATING_CONJUNCTIONS)
    has_coordinating = any(conj in word_set for conj in COORDINATING_CONJUNCTIONS)
    
    # Count commas as clause separators (heuristic)
    comma_count = sentence.count(',')
    
    if has_subordinating and has_coordinating:
        return 'compound-complex'
    elif has_subordinating:
        return 'complex'
    elif has_coordinating and comma_count >= 1:
        return 'compound'
    else:
        return 'simple'


def _compute_clause_complexity(sentences: List[str]) -> float:
    """Compute balance of sentence structure types.
    
    Returns a value between 0 and 1, where:
    - 0 = all sentences have the same structure
    - 1 = perfectly balanced distribution of structures
    """
    if len(sentences) < 2:
        return 0.0
    
    structures = [_classify_clause_structure(s) for s in sentences]
    
    # Count each type
    counts = {}
    for s in structures:
        counts[s] = counts.get(s, 0) + 1
    
    # Compute entropy (measure of balance)
    total = len(structures)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log(p, 2)
    
    # Maximum entropy for 4 categories is log2(4) = 2
    # Normalize to 0-1
    max_entropy = math.log(4, 2)
    return entropy / max_entropy


def _compute_punctuation_variety(text: str) -> float:
    """Compute diversity of punctuation marks used.
    
    Returns a value between 0 and 1, where:
    - 0 = only one type of punctuation used
    - 1 = all punctuation types used equally
    """
    # Count punctuation marks
    counts = {}
    for char in text:
        if char in PUNCTUATION_MARKS:
            counts[char] = counts.get(char, 0) + 1
    
    if not counts:
        return 0.0
    
    if len(counts) == 1:
        return 0.0
    
    # Compute entropy
    total = sum(counts.values())
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log(p, 2)
    
    # Maximum entropy for 8 punctuation types is log2(8) = 3
    max_entropy = math.log(len(PUNCTUATION_MARKS), 2)
    return entropy / max_entropy


def _detect_passive_voice(sentence: str) -> bool:
    """Detect if a sentence uses passive voice (heuristic).
    
    Looks for forms of "to be" followed by past participle.
    """
    words = _tokenize_words(sentence)
    
    # Look for passive patterns: "is/was/were + verb-ed"
    for i in range(len(words) - 1):
        if words[i] in PASSIVE_INDICATORS:
            # Check if next word looks like past participle (ends in -ed, -en, -t)
            next_word = words[i + 1]
            if (next_word.endswith('ed') or 
                next_word.endswith('en') or 
                next_word.endswith('t') and len(next_word) > 2):
                return True
    
    return False


def _compute_voice_distribution(sentences: List[str]) -> float:
    """Compute balance of active and passive voice.
    
    Returns a value between 0 and 1, where:
    - 0 = all active or all passive
    - 1 = perfectly balanced (50/50)
    """
    if len(sentences) < 2:
        return 0.0
    
    passive_count = sum(1 for s in sentences if _detect_passive_voice(s))
    active_count = len(sentences) - passive_count
    
    if active_count == 0 or passive_count == 0:
        return 0.0
    
    # Compute balance: 1.0 when equal, 0.0 when all one type
    total = active_count + passive_count
    ratio = min(active_count, passive_count) / (total / 2)
    return ratio


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class WriterSentenceVariety:
    """Analyze the structural diversity of prose."""
    
    def __init__(
        self,
        min_sentence_length: int = MIN_SENTENCE_LENGTH,
        max_sentence_length: int = MAX_SENTENCE_LENGTH,
    ) -> None:
        self.min_sentence_length = min_sentence_length
        self.max_sentence_length = max_sentence_length
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyze sentence variety in the given text.
        
        Parameters
        ----------
        text : str
            The prose to analyze.
        
        Returns
        -------
        dict
            Dictionary containing:
            - length_variance: normalized variance of sentence lengths
            - opening_diversity: fraction of unique opening words
            - clause_complexity: balance of sentence structure types
            - punctuation_variety: diversity of punctuation used
            - voice_distribution: balance of active/passive voice
            - variety_index: weighted composite score
            - classification: categorical label
        """
        sentences = _split_sentences(text)
        
        if not sentences:
            return {
                'length_variance': 0.0,
                'opening_diversity': 0.0,
                'clause_complexity': 0.0,
                'punctuation_variety': 0.0,
                'voice_distribution': 0.0,
                'variety_index': 0.0,
                'classification': 'monotonous',
            }
        
        # Compute dimensions
        length_var = _compute_length_variance(sentences)
        opening_div = _compute_opening_diversity(sentences)
        clause_comp = _compute_clause_complexity(sentences)
        punct_var = _compute_punctuation_variety(text)
        voice_dist = _compute_voice_distribution(sentences)
        
        # Weighted composite
        weights = {
            'length': 0.25,
            'opening': 0.20,
            'clause': 0.25,
            'punctuation': 0.15,
            'voice': 0.15,
        }
        
        variety_index = (
            weights['length'] * length_var +
            weights['opening'] * opening_div +
            weights['clause'] * clause_comp +
            weights['punctuation'] * punct_var +
            weights['voice'] * voice_dist
        )
        
        # Classify
        if variety_index >= 0.70:
            classification = 'virtuosic'
        elif variety_index >= 0.50:
            classification = 'varied'
        elif variety_index >= 0.30:
            classification = 'moderate'
        elif variety_index >= 0.15:
            classification = 'uniform'
        else:
            classification = 'monotonous'
        
        return {
            'length_variance': round(length_var, 4),
            'opening_diversity': round(opening_div, 4),
            'clause_complexity': round(clause_comp, 4),
            'punctuation_variety': round(punct_var, 4),
            'voice_distribution': round(voice_dist, 4),
            'variety_index': round(variety_index, 4),
            'classification': classification,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_sentence_variety(text: str) -> Dict[str, Any]:
    """Convenience function to analyze sentence variety.
    
    Parameters
    ----------
    text : str
        The prose to analyze.
    
    Returns
    -------
    dict
        Analysis results (see WriterSentenceVariety.analyze).
    """
    analyzer = WriterSentenceVariety()
    return analyzer.analyze(text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        # Read from file
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            text = f.read()
    else:
        # Read from stdin
        text = sys.stdin.read()
    
    result = analyze_sentence_variety(text)
    
    print(f"Sentence Variety Analysis")
    print(f"=" * 40)
    print(f"Length variance:      {result['length_variance']:.4f}")
    print(f"Opening diversity:    {result['opening_diversity']:.4f}")
    print(f"Clause complexity:    {result['clause_complexity']:.4f}")
    print(f"Punctuation variety:  {result['punctuation_variety']:.4f}")
    print(f"Voice distribution:   {result['voice_distribution']:.4f}")
    print(f"Variety index:        {result['variety_index']:.4f}")
    print(f"Classification:       {result['classification']}")
