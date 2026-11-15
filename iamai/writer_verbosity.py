#!/usr/bin/env python3
"""writer_verbosity — measure the ratio of padding to payload in prose.

Verbosity is the art of using ten words where three would do.  It is
the linguistic tax readers pay when writers lack confidence in their
content, pad for perceived thoroughness, or simply haven't edited.

A verbose text isn't wrong — it's inefficient.  The meaning arrives,
but wrapped in bubble wrap: "it is important to note that" instead of
"note that", "in order to" instead of "to", "due to the fact that"
instead of "because".  Each inflation adds a syllable without adding
information.

Verbosity manifests through several measurable channels.  **Function
word density** captures the ratio of grammatical mortar (the, of, in,
is, was, a, an) to content bricks (nouns, verbs, adjectives, adverbs).
**Filler phrases** are stock expressions that add words without
meaning: "in order to", "for the purpose of", "it should be noted
that".  **Nominalizations** bury verbs inside nouns — "utilization"
instead of "use", "implementation" instead of "implement" — inflating
word count while deflating energy.  **Redundancies** pile modifiers
on already-sufficient words: "very unique", "completely finished",
"past history".  **Pleonasms** smuggle unnecessary words into fixed
phrases: "advance planning", "end result", "added bonus".  **Verbosity
hedges** are filler qualifiers that pad assertions without sharpening
them: "basically", "essentially", "actually", "in fact".

Lean prose isn't terse — it's dense.  Hemingway used short sentences
but chose every word; Faulkner used long sentences but also chose every
word.  Verbosity isn't about sentence length; it's about the ratio of
signal words to noise words.  A 40-word sentence with no filler is
leaner than a 15-word sentence stuffed with "it is important to note
that" and "in order to".

This module measures verbosity as a composite index (0.0 – 1.0) across
six independent channels, orthogonal to concision (which measures
compression of ideas), clarity (which measures ambiguity), specificity
(which measures precision of reference), formality (which measures
register), and readability (which measures comprehension difficulty).

written by Qwen during manual caretaker visit 644, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Word tokenizer
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── function words ──────────────────────────────────────────────
# Closed-class words that carry grammatical but not semantic weight.

_FUNCTION_WORDS: Set[str] = {
    # Articles
    "a", "an", "the",
    # Prepositions
    "in", "on", "at", "to", "for", "with", "by", "from", "of",
    "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "under", "over", "upon",
    # Pronouns
    "i", "me", "my", "mine", "myself",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "it", "its", "itself",
    "we", "us", "our", "ours", "ourselves",
    "they", "them", "their", "theirs", "themselves",
    # Conjunctions
    "and", "but", "or", "nor", "yet", "so",
    "because", "although", "while", "if", "when", "where",
    # Auxiliary / copula
    "is", "am", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "must",
    # Determiners / quantifiers
    "this", "that", "these", "those",
    "some", "any", "all", "each", "every", "no", "not",
    "many", "much", "few", "several",
    # Existential / filler subjects
    "there", "here", "it",
}


# ── filler phrases ──────────────────────────────────────────────
# Stock expressions that inflate sentence length without adding meaning.

_FILLER_PHRASES = [
    # Multi-word prepositions (longer forms)
    re.compile(r"\bin order to\b", re.IGNORECASE),
    re.compile(r"\bfor the purpose of\b", re.IGNORECASE),
    re.compile(r"\bdue to the fact that\b", re.IGNORECASE),
    re.compile(r"\bin the event that\b", re.IGNORECASE),
    re.compile(r"\bin spite of the fact that\b", re.IGNORECASE),
    re.compile(r"\bon the grounds that\b", re.IGNORECASE),
    re.compile(r"\bby means of\b", re.IGNORECASE),
    re.compile(r"\bin the process of\b", re.IGNORECASE),
    re.compile(r"\bwith regard to\b", re.IGNORECASE),
    re.compile(r"\bwith respect to\b", re.IGNORECASE),
    re.compile(r"\bin reference to\b", re.IGNORECASE),
    # Throat-clearing openers
    re.compile(r"\bit is important to note that\b", re.IGNORECASE),
    re.compile(r"\bit should be noted that\b", re.IGNORECASE),
    re.compile(r"\bit is worth noting that\b", re.IGNORECASE),
    re.compile(r"\bit goes without saying that\b", re.IGNORECASE),
    re.compile(r"\bit is interesting to note that\b", re.IGNORECASE),
    re.compile(r"\bneedless to say\b", re.IGNORECASE),
    # Verbal padding
    re.compile(r"\bthe fact that\b", re.IGNORECASE),
    re.compile(r"\bin terms of\b", re.IGNORECASE),
    re.compile(r"\bas a matter of fact\b", re.IGNORECASE),
    re.compile(r"\bfor all intents and purposes\b", re.IGNORECASE),
    re.compile(r"\bat this point in time\b", re.IGNORECASE),
    re.compile(r"\bat the present time\b", re.IGNORECASE),
    re.compile(r"\bin the near future\b", re.IGNORECASE),
]


# ── nominalizations ─────────────────────────────────────────────
# Nouns ending in -tion/-sion/-ment/-ness/-ity that bury verbs.
# Only counted when they appear as standalone tokens ≥ 5 chars.

_NOMINALIZATION_SUFFIXES = re.compile(
    r"\b\w{3,}(?:tion|sion|ment|ness|ity|ance|ence)\b", re.IGNORECASE
)


# ── redundancies ────────────────────────────────────────────────
# Intensifier + adjective pairs where the intensifier is superfluous.

_REDUNDANCY_PHRASES = [
    re.compile(r"\bvery unique\b", re.IGNORECASE),
    re.compile(r"\bcompletely finished\b", re.IGNORECASE),
    re.compile(r"\babsolutely essential\b", re.IGNORECASE),
    re.compile(r"\bpast history\b", re.IGNORECASE),
    re.compile(r"\bfuture plans?\b", re.IGNORECASE),
    re.compile(r"\bexact same\b", re.IGNORECASE),
    re.compile(r"\bclose proximity\b", re.IGNORECASE),
    re.compile(r"\bequally as\b", re.IGNORECASE),
    re.compile(r"\bfree gift\b", re.IGNORECASE),
    re.compile(r"\bend result\b", re.IGNORECASE),
    re.compile(r"\bunexpected surprise\b", re.IGNORECASE),
    re.compile(r"\bgeneral consensus\b", re.IGNORECASE),
    re.compile(r"\bcompletely eliminate\b", re.IGNORECASE),
    re.compile(r"\bvery perfect\b", re.IGNORECASE),
    re.compile(r"\btotally destroy\b", re.IGNORECASE),
]


# ── pleonasms ───────────────────────────────────────────────────
# Unnecessary words smuggled into fixed phrases.

_PLEONASM_PHRASES = [
    re.compile(r"\badvance planning\b", re.IGNORECASE),
    re.compile(r"\badded bonus\b", re.IGNORECASE),
    re.compile(r"\bbasic fundamentals?\b", re.IGNORECASE),
    re.compile(r"\bfinal outcome\b", re.IGNORECASE),
    re.compile(r"\bpersonal opinion\b", re.IGNORECASE),
    re.compile(r"\bplan ahead\b", re.IGNORECASE),
    re.compile(r"\brevert back\b", re.IGNORECASE),
    re.compile(r"\breturn back\b", re.IGNORECASE),
    re.compile(r"\btrue fact\b", re.IGNORECASE),
    re.compile(r"\bsum total\b", re.IGNORECASE),
    re.compile(r"\beach and every\b", re.IGNORECASE),
    re.compile(r"\bfirst and foremost\b", re.IGNORECASE),
    re.compile(r"\bnecessary requirement\b", re.IGNORECASE),
]


# ── verbosity hedges ────────────────────────────────────────────
# Filler qualifiers that pad without sharpening.

_VERBOSITY_HEDGES = [
    re.compile(r"\bbasically\b", re.IGNORECASE),
    re.compile(r"\bessentially\b", re.IGNORECASE),
    re.compile(r"\bactually\b", re.IGNORECASE),
    re.compile(r"\bvirtually\b", re.IGNORECASE),
    re.compile(r"\bpractically\b", re.IGNORECASE),
    re.compile(r"\bin fact\b", re.IGNORECASE),
    re.compile(r"\breally\b", re.IGNORECASE),
    re.compile(r"\bquite\b", re.IGNORECASE),
    re.compile(r"\bsimply put\b", re.IGNORECASE),
    re.compile(r"\bin a sense\b", re.IGNORECASE),
    re.compile(r"\bsort of\b", re.IGNORECASE),
    re.compile(r"\bkind of\b", re.IGNORECASE),
    re.compile(r"\ba little bit\b", re.IGNORECASE),
    re.compile(r"\bto some extent\b", re.IGNORECASE),
    re.compile(r"\bto a certain extent\b", re.IGNORECASE),
    re.compile(r"\bin some ways\b", re.IGNORECASE),
]


# ── result dataclass ────────────────────────────────────────────


@dataclass
class VerbosityResult:
    """Results of verbosity analysis."""

    # Raw counts
    function_word_count: int = 0
    filler_phrase_count: int = 0
    nominalization_count: int = 0
    redundancy_count: int = 0
    pleonasm_count: int = 0
    verbosity_hedge_count: int = 0

    # Rates per 100 sentences
    function_word_rate: float = 0.0
    filler_phrase_rate: float = 0.0
    nominalization_rate: float = 0.0
    redundancy_rate: float = 0.0
    pleonasm_rate: float = 0.0
    verbosity_hedge_rate: float = 0.0

    # Word-level metrics
    content_word_count: int = 0
    function_word_ratio: float = 0.0

    # Composite
    verbosity_index: float = 0.0
    classification: str = "lean"

    # Metadata
    total_sentences: int = 0
    total_words: int = 0
    details: dict = field(default_factory=dict)


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_words(text: str) -> int:
    """Count words."""
    return len(_WORD_SPLIT.findall(text))


# ── main measurement function ───────────────────────────────────


def measure_verbosity(text: str) -> VerbosityResult:
    """Measure verbosity of a text.

    Returns a VerbosityResult with verbosity_index (0.0–1.0)
    and classification.
    """
    result = VerbosityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "lean"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    scale = 100.0 / max(sentences, 1)

    # ── count function words ─────────────────────────────────
    tokens = [t.lower() for t in _WORD_SPLIT.findall(text)]
    func_words = sum(1 for t in tokens if t in _FUNCTION_WORDS)
    content_words = len(tokens) - func_words
    result.function_word_count = func_words
    result.content_word_count = max(content_words, 0)
    result.function_word_ratio = round(
        func_words / max(len(tokens), 1), 3
    )

    # ── count filler phrases ─────────────────────────────────
    fillers = sum(len(p.findall(text)) for p in _FILLER_PHRASES)
    result.filler_phrase_count = fillers

    # ── count nominalizations (tokens >= 5 chars) ────────────
    noms = _NOMINALIZATION_SUFFIXES.findall(text)
    result.nominalization_count = sum(
        1 for n in noms if len(n) >= 5
    )

    # ── count redundancies ───────────────────────────────────
    reds = sum(len(p.findall(text)) for p in _REDUNDANCY_PHRASES)
    result.redundancy_count = reds

    # ── count pleonasms ──────────────────────────────────────
    pleos = sum(len(p.findall(text)) for p in _PLEONASM_PHRASES)
    result.pleonasm_count = pleos

    # ── count verbosity hedges ───────────────────────────────
    hedges = sum(len(p.findall(text)) for p in _VERBOSITY_HEDGES)
    result.verbosity_hedge_count = hedges

    # ── rates per 100 sentences ──────────────────────────────
    result.function_word_rate = round(func_words * scale, 3)
    result.filler_phrase_rate = round(fillers * scale, 3)
    result.nominalization_rate = round(
        result.nominalization_count * scale, 3
    )
    result.redundancy_rate = round(reds * scale, 3)
    result.pleonasm_rate = round(pleos * scale, 3)
    result.verbosity_hedge_rate = round(hedges * scale, 3)

    # ── composite verbosity index (0.0 – 1.0) ────────────────
    # Normalize each channel to ~0–1 via typical maxima
    cap_fw = min(1.0, result.function_word_ratio / 0.70)
    cap_fp = min(1.0, result.filler_phrase_rate / 20.0)
    cap_nom = min(1.0, result.nominalization_rate / 30.0)
    cap_red = min(1.0, result.redundancy_rate / 8.0)
    cap_pleo = min(1.0, result.pleonasm_rate / 5.0)
    cap_hedge = min(1.0, result.verbosity_hedge_rate / 15.0)

    composite = (
        0.25 * cap_fw
        + 0.20 * cap_fp
        + 0.15 * cap_nom
        + 0.15 * cap_red
        + 0.10 * cap_pleo
        + 0.15 * cap_hedge
    )
    result.verbosity_index = round(min(1.0, composite), 4)

    # ── classification ───────────────────────────────────────
    idx = result.verbosity_index
    if idx < 0.15:
        result.classification = "lean"
    elif idx < 0.30:
        result.classification = "economical"
    elif idx < 0.50:
        result.classification = "conversational"
    elif idx < 0.70:
        result.classification = "verbose"
    else:
        result.classification = "bloated"

    result.details = {
        "function_word_ratio": result.function_word_ratio,
        "filler_phrase_rate": result.filler_phrase_rate,
        "nominalization_rate": result.nominalization_rate,
        "redundancy_rate": result.redundancy_rate,
        "pleonasm_rate": result.pleonasm_rate,
        "verbosity_hedge_rate": result.verbosity_hedge_rate,
        "verbosity_index": result.verbosity_index,
        "classification": result.classification,
    }

    return result


# ── CLI convenience ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    r = measure_verbosity(text)
    print(f"verbosity_index           : {r.verbosity_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"function_word_ratio       : {r.function_word_ratio}")
    print(f"filler_phrase_rate        : {r.filler_phrase_rate}")
    print(f"nominalization_rate       : {r.nominalization_rate}")
    print(f"redundancy_rate           : {r.redundancy_rate}")
    print(f"pleonasm_rate             : {r.pleonasm_rate}")
    print(f"verbosity_hedge_rate      : {r.verbosity_hedge_rate}")
    print(f"total_sentences           : {r.total_sentences}")
    print(f"total_words               : {r.total_words}")
