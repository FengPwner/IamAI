#!/usr/bin/env python3
"""writer_lexical_density — analyse lexical density and word-class balance.

*Lexical density* is the proportion of **content words** (nouns,
lexical verbs, adjectives, adverbs) relative to the total word count.
A high density signals information-rich prose (academic writing,
technical documentation); a low density signals more conversational
or grammatically elaborated text.

This module tokenises text, classifies each token as *content* or
*function*, and computes density together with sub-class balance
metrics.

Word classes
------------

=================  ==================================================
class              examples
=================  ==================================================
noun               system, process, idea, water, architecture
verb (lexical)     run, think, build, analyse, consider
adjective          fast, complex, important, lexical, dense
adverb             quickly, often, very, however, well
function           the, a, is, are, was, of, in, to, and, but,
                   it, they, this, that, have, been, will, can
=================  ==================================================

Closed-class function words are stored in a fixed stop-list.
Everything else is treated as a content word.

Metrics
-------

========================  ===========================================
metric                    meaning
========================  ===========================================
total_words               tokens counted (alphabetic only)
content_words             tokens classified as content
function_words            tokens classified as function
lexical_density           content_words / total_words  [0.0–1.0]
noun_ratio                nouns / content_words
verb_ratio                verbs / content_words
adjective_ratio           adjectives / content_words
adverb_ratio              adverbs / content_words
content_diversity         Shannon entropy of the four content
                          sub-classes in [0, log2(4)] ≈ [0, 1.386]
density_label             human-readable classification
========================  ===========================================

Density labels
--------------

================  ===================================================
label             description
================  ===================================================
very_dense        density ≥ 0.65 — heavily information-packed;
                  typical of keyword lists or telegraphic style
dense             0.50 ≤ density < 0.65 — academic or technical
                  writing with little grammatical scaffolding
moderate          0.40 ≤ density < 0.50 — standard expository
                  prose with a healthy mix of content and glue
light             0.30 ≤ density < 0.40 — conversational or
                  narrative with substantial grammatical framing
very_light        density < 0.30 — highly elaborated speech or
                  children's writing
================  ===================================================
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Function-word list (closed class — articles, pronouns, prepositions,
# auxiliaries, conjunctions, determiners, particles)
# ---------------------------------------------------------------------------

_FUNCTION_WORDS: set = {
    # Articles / determiners
    "a", "an", "the", "this", "that", "these", "those",
    "my", "your", "his", "her", "its", "our", "their",
    "some", "any", "no", "every", "each", "all", "both",
    "few", "many", "much", "several", "enough",
    # Personal pronouns
    "i", "me", "we", "us", "you", "he", "him", "she",
    "it", "they", "them", "myself", "yourself", "himself",
    "herself", "itself", "ourselves", "themselves",
    # Relative / interrogative
    "who", "whom", "whose", "which", "what", "whatever",
    "whoever", "whichever",
    # Prepositions
    "in", "on", "at", "to", "for", "with", "by", "from",
    "of", "about", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "over",
    "up", "down", "out", "off", "along", "across", "around",
    "against", "without", "within", "toward", "towards",
    "upon", "among", "upon", "beside", "beyond", "near",
    # Conjunctions
    "and", "or", "but", "nor", "yet", "so", "for",
    "because", "although", "while", "whereas", "since",
    "unless", "until", "if", "whether", "though",
    # Auxiliary / copula verbs
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "do", "does", "did", "doing", "done",
    "will", "would", "shall", "should", "may", "might",
    "can", "could", "must",
    # Particles / misc function words
    "not", "n't", "there", "here", "also", "just",
    "very", "too", "quite", "rather", "more", "most",
    "as", "than", "then",
}

# Common suffixes that suggest word class (very lightweight POS).
_NOUN_SUFFIXES = ("tion", "sion", "ment", "ness", "ity", "ence",
                  "ance", "ship", "dom", "ism", "ist", "er", "or",
                  "ure", "age", "hood", "ling")
_VERB_SUFFIXES = ("ise", "ize", "ify", "ate", "ing", "ed")
_ADJ_SUFFIXES = ("ous", "ive", "able", "ible", "ful", "less",
                 "al", "ial", "ical", "ish", "ary", "ory")
_ADV_SUFFIXES = ("ly", "ward", "wards", "wise")

# Words that are ambiguous — default classification.
_FORCE_CONTENT: set = {
    "run", "think", "build", "make", "take", "give",
    "see", "know", "find", "tell", "ask", "work",
    "call", "try", "need", "feel", "become", "leave",
    "put", "mean", "keep", "let", "begin", "seem",
    "help", "show", "hear", "play", "move", "live",
    "believe", "bring", "happen", "write", "provide",
    "sit", "stand", "lose", "pay", "meet", "include",
    "continue", "set", "learn", "change", "lead",
    "understand", "watch", "follow", "stop", "create",
    "speak", "read", "allow", "add", "spend", "grow",
    "open", "walk", "win", "offer", "remember",
    "consider", "appear", "buy", "wait", "serve",
    "die", "send", "expect", "develop", "carry",
    "analyse", "analyze", "compute", "design",
}

_TOKEN_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Return lowercase alphabetic tokens."""
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _guess_class(token: str) -> str:
    """Classify a single lowercase token.

    Returns one of ``"noun"``, ``"verb"``, ``"adjective"``,
    ``"adverb"``, or ``"function"``.
    """
    if token in _FUNCTION_WORDS:
        return "function"
    if token in _FORCE_CONTENT:
        return "verb"

    # Suffix heuristics (order matters — most specific first).
    for suf in _ADV_SUFFIXES:
        if token.endswith(suf) and len(token) > len(suf) + 1:
            return "adverb"
    for suf in _VERB_SUFFIXES:
        if token.endswith(suf) and len(token) > len(suf) + 1:
            return "verb"
    for suf in _ADJ_SUFFIXES:
        if token.endswith(suf) and len(token) > len(suf) + 1:
            return "adjective"
    for suf in _NOUN_SUFFIXES:
        if token.endswith(suf) and len(token) > len(suf) + 1:
            return "noun"

    # Default: content word (noun is the most common open class).
    return "noun"


def _shannon_entropy(counts: Dict[str, int]) -> float:
    """Shannon entropy of a discrete distribution (natural log)."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log(p)
    return h


def _classify_density(density: float) -> str:
    """Map a density value to a human-readable label."""
    if density >= 0.65:
        return "very_dense"
    if density >= 0.50:
        return "dense"
    if density >= 0.40:
        return "moderate"
    if density >= 0.30:
        return "light"
    return "very_light"


def _empty_result() -> Dict[str, Any]:
    """Zeroed-out result for empty input."""
    return {
        "total_words": 0,
        "content_words": 0,
        "function_words": 0,
        "lexical_density": 0.0,
        "noun_ratio": 0.0,
        "verb_ratio": 0.0,
        "adjective_ratio": 0.0,
        "adverb_ratio": 0.0,
        "content_diversity": 0.0,
        "density_label": "very_light",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_lexical_density(text: str) -> Dict[str, Any]:
    """Analyse lexical density and word-class balance in *text*.

    Returns a dict with all metrics listed in the module docstring.
    """
    tokens = _tokenize(text)
    if not tokens:
        return _empty_result()

    class_counts: Dict[str, int] = {
        "noun": 0, "verb": 0, "adjective": 0, "adverb": 0, "function": 0,
    }
    for tok in tokens:
        cls = _guess_class(tok)
        class_counts[cls] += 1

    total = len(tokens)
    content = total - class_counts["function"]
    density = content / total if total else 0.0

    sub_counts = {k: class_counts[k] for k in ("noun", "verb", "adjective", "adverb")}
    diversity = _shannon_entropy(sub_counts) if content > 0 else 0.0

    return {
        "total_words": total,
        "content_words": content,
        "function_words": class_counts["function"],
        "lexical_density": round(density, 4),
        "noun_ratio": round(sub_counts["noun"] / content, 4) if content else 0.0,
        "verb_ratio": round(sub_counts["verb"] / content, 4) if content else 0.0,
        "adjective_ratio": round(sub_counts["adjective"] / content, 4) if content else 0.0,
        "adverb_ratio": round(sub_counts["adverb"] / content, 4) if content else 0.0,
        "content_diversity": round(diversity, 4),
        "density_label": _classify_density(density),
    }


def lexical_density_report(strokes_path: str = "data/strokes.jsonl") -> Dict[str, Any]:
    """On-disk wrapper: read strokes and analyse concatenated text."""
    path = Path(strokes_path)
    if not path.exists():
        return _empty_result()

    texts: List[str] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            body = rec.get("text", "") or rec.get("body", "") or ""
            if body.strip():
                texts.append(body)

    if not texts:
        return _empty_result()
    return compute_lexical_density("\n\n".join(texts))


def lexical_density_summary(result: Dict[str, Any]) -> str:
    """Human-readable summary of lexical density analysis."""
    lines = [
        f"total words:     {result['total_words']}",
        f"content words:   {result['content_words']}",
        f"function words:  {result['function_words']}",
        f"lexical density: {result['lexical_density']:.4f}",
        f"noun ratio:      {result['noun_ratio']:.4f}",
        f"verb ratio:      {result['verb_ratio']:.4f}",
        f"adjective ratio: {result['adjective_ratio']:.4f}",
        f"adverb ratio:    {result['adverb_ratio']:.4f}",
        f"diversity (H):   {result['content_diversity']:.4f}",
        f"label:           {result['density_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyse lexical density in strokes."
    )
    parser.add_argument(
        "--strokes", default="data/strokes.jsonl",
        help="Path to strokes JSONL (default: data/strokes.jsonl)",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args(argv)

    result = lexical_density_report(args.strokes)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(lexical_density_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
