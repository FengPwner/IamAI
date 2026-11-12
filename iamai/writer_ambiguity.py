#!/usr/bin/env python3
"""writer_ambiguity — measure whether prose is semantically unambiguous.

Ambiguity tracks the *interpretive certainty* of a text.  Unambiguous
prose leaves the reader with one clear reading: every pronoun points
to a single antecedent, every modifier attaches to one head, every
quantifier scopes over a well-defined set.  Ambiguous prose admits
multiple readings — the reader pauses, re-reads, and guesses.

This module is orthogonal to the other writer metrics:

- **clarity** tracks *structural parseability*.  Clear prose has
  unambiguous attachment and short pronoun-antecedent distance.
  Ambiguity extends clarity by measuring *semantic* indeterminacy:
  scope conflicts, dangling modifiers, and lexical polysemy that
  persist even when the syntactic parse is deterministic.

- **precision** tracks *claim exactness*.  Precise prose uses specific
  numbers, dates, and names rather than vague references.  Ambiguity
  is about *structural* indeterminacy — whether the reader can
  determine what a sentence means at all, regardless of how specific
  the claims are.

- **concision** tracks *word economy*.  Concise prose uses few words.
  Ambiguous prose may be concise ("I saw the man with the telescope")
  or verbose.  Concision measures length; ambiguity measures certainty.

- **coherence** tracks *logical flow*.  Coherent prose connects ideas
  logically.  Ambiguous prose may be perfectly coherent once
  disambiguated — the problem is that multiple coherent readings exist.

Ambiguity asks: **can the reader determine what the writer meant
without re-reading or guessing?**

Dimensions
----------

=============================  ===========================================
metric                         meaning
=============================  ===========================================
pronoun_reference_ambiguity    fraction of third-person pronouns (he/she/
                               it/they/them) where more than one candidate
                               antecedent noun exists in the preceding
                               sentence or current clause; resolved via
                               proximity (nearest compatible noun wins)
                               and flagged when >=2 nouns match in number
pp_attachment_ambiguity        fraction of prepositional phrases that
                               could modify more than one preceding noun
                               or verb; detected by finding PP patterns
                               (in/on/at/with/from/to/of + NP) and
                               counting candidate heads within the same
                               clause
lexical_ambiguity_rate         fraction of content words that are
                               polysemous (>=3 common senses) without
                               sufficient disambiguating context; uses
                               a curated list of high-frequency ambiguous
                               words and checks for nearby disambiguators
scope_ambiguity_rate           fraction of sentences containing >=2
                               scope-bearing elements (quantifiers like
                               every/all/some/each + negation or other
                               quantifiers) where relative scope is
                               undetermined
dangling_modifier_rate         fraction of sentence-initial participial
                               or adverbial phrases whose implied subject
                               does not match the grammatical subject of
                               the main clause
=============================  ===========================================

Ambiguity classes
-----------------

==============  ============================================================
class           meaning
==============  ============================================================
unambiguous     score >= 0.80 — every pronoun, modifier, and quantifier
                resolves to a single reading; the reader never pauses
clear           0.60 <= score < 0.80 — occasional ambiguity in complex
                sentences but the dominant reading is always obvious
serviceable     0.40 <= score < 0.60 — moderate ambiguity; some sentences
                require re-reading to determine the intended meaning
ambiguous       0.20 <= score < 0.40 — frequent ambiguity; the reader
                regularly encounters sentences with multiple readings
opaque          score < 0.20 — pervasive ambiguity; prose requires
                extensive re-reading and inference to interpret
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
    "i", "me", "my", "we", "us", "our", "you", "your",
    "he", "him", "his", "she", "her", "it", "its", "they", "them", "their",
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

PRONOUNS = re.compile(
    r"\b(?:he|him|his|she|her|hers|it|its|they|them|their|theirs)\b", re.I
)

PREPOSITIONS = frozenset({
    "in", "on", "at", "to", "from", "by", "with", "of", "about",
    "for", "into", "onto", "upon", "over", "under", "through",
    "between", "among", "against", "toward", "towards", "across",
    "along", "around", "behind", "beneath", "beside", "beyond",
    "during", "near", "past", "since", "without", "within",
})

SCOPE_BEARERS = [
    re.compile(r"\b(?:every|each|all|any|some|most|many|few|several|no)\b", re.I),
    re.compile(r"\b(?:not|never|nobody|nothing|nowhere|neither|nor)\b", re.I),
    re.compile(r"\b(?:at least|at most|more than|less than|fewer than)\b", re.I),
]

POLYSEMOUS_WORDS = {
    "run": {"physical_motion", "manage", "execute", "flow", "compete"},
    "set": {"place", "collection", "determine", "adjust", "fixed"},
    "head": {"body_part", "leader", "top", "direction", "mental"},
    "face": {"body_part", "confront", "surface", "expression", "direction"},
    "book": {"reading_material", "reserve", "record", "schedule"},
    "point": {"tip", "indicate", "score", "location", "argument"},
    "right": {"correct", "direction", "entitlement", "immediate"},
    "left": {"direction", "remaining", "departed", "political"},
    "light": {"illumination", "weight", "ignite", "understand"},
    "bear": {"animal", "carry", "endure", "give_birth"},
    "bank": {"financial", "river_edge", "tilt", "rely"},
    "letter": {"character", "correspondence", "literature"},
    "wave": {"water", "gesture", "electromagnetic", "brandish"},
    "well": {"healthy", "water_source", "satisfactorily", "intensifier"},
    "spring": {"season", "coil", "jump", "water_source", "originate"},
    "court": {"legal", "sports", "royal", "woo"},
    "play": {"drama", "recreation", "perform", "operate", "gamble"},
    "field": {"land", "domain", "sports", "handle", "divert"},
    "order": {"sequence", "command", "request", "tidiness", "group"},
    "sound": {"audio", "healthy", "thorough", "body_of_water"},
}

DISAMBIGUATORS = {
    "run": ["marathon", "company", "program", "river", "race", "software", "business"],
    "set": ["table", "theory", "record", "alarm", "data", "rules"],
    "head": ["ache", "department", "office", "nails", "count", "scarf"],
    "face": ["mask", "problem", "wall", "value", "cream", "north"],
    "book": ["read", "hotel", "flight", "shelf", "library", "appointment"],
    "point": ["finger", "view", "game", "compass", "decimal", "knife"],
    "right": ["answer", "turn", "freedom", "now", "left", "wrong"],
    "left": ["right", "remaining", "house", "wing", "behind"],
    "light": ["bulb", "switch", "weight", "candle", "travel", "dawn"],
    "bear": ["cub", "weight", "pain", "market", "forest", "cubs"],
    "bank": ["money", "river", "account", "loan", "slope", "trust"],
    "letter": ["write", "alphabet", "mail", "envelope", "character"],
    "wave": ["ocean", "hand", "radio", "heat", "flag", "electromagnetic"],
    "well": ["feel", "water", "done", "known", "oil", "deep"],
    "spring": ["break", "coil", "board", "water", "time", "forward"],
    "court": ["judge", "basketball", "tennis", "king", "law", "case"],
    "play": ["game", "role", "music", "theater", "instrument", "fair"],
    "field": ["farm", "study", "football", "ball", "questions", "magnetic"],
    "order": ["place", "military", "restaurant", "tidy", "alphabetical", "chemical"],
    "sound": ["music", "advice", "barrier", "sleep", "proof", "wave"],
}

PARTICIPLE_START = re.compile(
    r"^(?:Walking|Running|Having|Being|After|Before|While|When|"
    r"Seeing|Hearing|Knowing|Taking|Making|Going|Coming|Looking|"
    r"Moving|Standing|Sitting|Waiting|Leaving|Entering|Finding|"
    r"Reading|Writing|Working|Playing|Driving|Speaking|Thinking|"
    r"Considering|Regarding|Following|During|Given|Based|Driven|"
    r"Armed|Equipped|Loaded|Filled|Covered|Wrapped|Painted|"
    r"[A-Z][a-z]+ing|[A-Z][a-z]+ed)\b"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, handling common abbreviations."""
    if not text or not isinstance(text, str):
        return []
    protected = re.sub(r"(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|i\.e|e\.g)\.",
                       lambda m: m.group(0).replace(".", "DOT"), text)
    parts = re.split(r"(?<=[.!?])\s+", protected.strip())
    return [s.replace("DOT", ".").strip() for s in parts if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    if not text or not isinstance(text, str):
        return []
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _words(sentence: str) -> list[str]:
    """Extract lowercase words from a sentence."""
    return re.findall(r"[a-z']+", sentence.lower())


def _content_words(sentence: str) -> set[str]:
    """Extract content words (non-function, >=3 chars)."""
    return {w for w in _words(sentence) if w not in FUNCTION_WORDS and len(w) >= 3}


def _find_nouns(words: list[str]) -> list[str]:
    """Heuristic noun detection: non-function, non-verb words >=3 chars."""
    verb_suffixes = ("ing", "ed")
    nouns = []
    for w in words:
        if w in FUNCTION_WORDS or len(w) < 3:
            continue
        if any(w.endswith(s) for s in verb_suffixes) and len(w) <= 5:
            continue
        nouns.append(w)
    return nouns


def _is_singular(word: str) -> bool:
    """Heuristic singular/plural detection."""
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return False
    return True


# ---------------------------------------------------------------------------
# Sub-metrics
# ---------------------------------------------------------------------------

def compute_pronoun_reference_ambiguity(sentences: list[str]) -> float:
    """Fraction of pronouns with >1 candidate antecedent."""
    if not sentences:
        return 0.0
    total_pronouns = 0
    ambiguous_pronouns = 0

    for i, sent in enumerate(sentences):
        words_list = _words(sent)
        context_words = []
        if i > 0:
            context_words.extend(_find_nouns(_words(sentences[i - 1])))
        for j, word in enumerate(words_list):
            if not PRONOUNS.fullmatch(word):
                continue
            total_pronouns += 1
            singular = word.lower() in {"he", "him", "his", "she", "her", "hers", "it", "its"}
            local_nouns = _find_nouns(words_list[:j])
            candidates = context_words + local_nouns
            matching = [n for n in candidates if _is_singular(n) == singular]
            if len(matching) >= 2:
                ambiguous_pronouns += 1

    return ambiguous_pronouns / total_pronouns if total_pronouns else 0.0


def compute_pp_attachment_ambiguity(sentences: list[str]) -> float:
    """Fraction of PPs with multiple candidate attachment heads."""
    if not sentences:
        return 0.0
    total_pps = 0
    ambiguous_pps = 0

    for sent in sentences:
        words_list = _words(sent)
        pp_positions = []
        for i, word in enumerate(words_list):
            if word in PREPOSITIONS and i > 0 and i < len(words_list) - 1:
                pp_positions.append(i)

        if not pp_positions:
            continue

        for pp_idx in pp_positions:
            total_pps += 1
            preceding = words_list[:pp_idx]
            heads = _find_nouns(preceding)
            verb_candidates = [w for w in preceding
                               if (w.endswith("ing") or w.endswith("ed"))
                               and len(w) > 4 and w not in FUNCTION_WORDS]
            total_heads = len(set(heads)) + len(set(verb_candidates))
            if total_heads >= 2:
                ambiguous_pps += 1

    return ambiguous_pps / total_pps if total_pps else 0.0


def compute_lexical_ambiguity_rate(sentences: list[str]) -> float:
    """Fraction of content words that are polysemous without disambiguation."""
    if not sentences:
        return 0.0
    total_polysemous = 0
    ambiguous_count = 0

    for sent in sentences:
        words_list = _words(sent)
        for i, word in enumerate(words_list):
            base = word.rstrip("s").rstrip("'")
            if base not in POLYSEMOUS_WORDS and word not in POLYSEMOUS_WORDS:
                continue
            total_polysemous += 1
            lookup = base if base in POLYSEMOUS_WORDS else word
            window = words_list[max(0, i - 5):i + 6]
            disambig_list = DISAMBIGUATORS.get(lookup, [])
            has_disambiguator = any(d in window for d in disambig_list)
            if not has_disambiguator:
                ambiguous_count += 1

    return ambiguous_count / total_polysemous if total_polysemous else 0.0


def compute_scope_ambiguity_rate(sentences: list[str]) -> float:
    """Fraction of sentences with >=2 scope-bearing elements."""
    if not sentences:
        return 0.0
    ambiguous = 0

    for sent in sentences:
        scope_count = 0
        for pattern in SCOPE_BEARERS:
            matches = pattern.findall(sent)
            scope_count += len(matches)
        if scope_count >= 2:
            ambiguous += 1

    return ambiguous / len(sentences)


def compute_dangling_modifier_rate(sentences: list[str]) -> float:
    """Fraction of sentences with dangling initial modifiers."""
    if not sentences:
        return 0.0
    dangling = 0
    applicable = 0

    inanimate_markers = frozenset({
        "it", "this", "that", "idea", "concept", "situation",
        "problem", "question", "fact", "result",
        "decision", "plan", "approach", "method",
        "system", "process", "data", "information",
        "evidence", "research", "study", "analysis",
        "there", "what", "which",
    })

    for sent in sentences:
        if not PARTICIPLE_START.match(sent):
            continue
        comma_idx = sent.find(",")
        if comma_idx < 3:
            continue
        applicable += 1
        after_comma = sent[comma_idx + 1:].strip()
        after_words = _words(after_comma)
        first_phrase = " ".join(after_words[:4]).lower()
        if any(marker in first_phrase for marker in inanimate_markers):
            dangling += 1

    return dangling / applicable if applicable else 0.0


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

WEIGHTS = {
    "pronoun_reference": 0.30,
    "pp_attachment": 0.20,
    "lexical_ambiguity": 0.15,
    "scope_ambiguity": 0.20,
    "dangling_modifier": 0.15,
}


def compute_ambiguity_metrics(text: str) -> dict[str, float]:
    """Compute all ambiguity sub-metrics from raw text."""
    sentences = _split_sentences(text)

    pronoun = compute_pronoun_reference_ambiguity(sentences)
    pp_attach = compute_pp_attachment_ambiguity(sentences)
    lexical = compute_lexical_ambiguity_rate(sentences)
    scope = compute_scope_ambiguity_rate(sentences)
    dangling = compute_dangling_modifier_rate(sentences)

    return {
        "pronoun_reference_ambiguity": round(pronoun, 4),
        "pp_attachment_ambiguity": round(pp_attach, 4),
        "lexical_ambiguity_rate": round(lexical, 4),
        "scope_ambiguity_rate": round(scope, 4),
        "dangling_modifier_rate": round(dangling, 4),
    }


def compute_ambiguity_index(metrics: dict[str, float]) -> float:
    """Weighted composite: higher = less ambiguous (better)."""
    score = (
        WEIGHTS["pronoun_reference"] * (1.0 - metrics.get("pronoun_reference_ambiguity", 0.0))
        + WEIGHTS["pp_attachment"] * (1.0 - metrics.get("pp_attachment_ambiguity", 0.0))
        + WEIGHTS["lexical_ambiguity"] * (1.0 - metrics.get("lexical_ambiguity_rate", 0.0))
        + WEIGHTS["scope_ambiguity"] * (1.0 - metrics.get("scope_ambiguity_rate", 0.0))
        + WEIGHTS["dangling_modifier"] * (1.0 - metrics.get("dangling_modifier_rate", 0.0))
    )
    return round(score, 4)


def classify_ambiguity(score: float) -> str:
    """Map composite score to a human-readable class."""
    if score >= 0.80:
        return "unambiguous"
    if score >= 0.60:
        return "clear"
    if score >= 0.40:
        return "serviceable"
    if score >= 0.20:
        return "ambiguous"
    return "opaque"


def analyze_ambiguity(text: str) -> dict[str, Any]:
    """Full ambiguity analysis pipeline."""
    metrics = compute_ambiguity_metrics(text)
    index = compute_ambiguity_index(metrics)
    label = classify_ambiguity(index)
    return {
        "metrics": metrics,
        "ambiguity_index": index,
        "ambiguity_class": label,
        "sentence_count": len(_split_sentences(text)),
        "paragraph_count": len(_split_paragraphs(text)),
    }


def format_ambiguity_report(analysis: dict[str, Any]) -> str:
    """Human-readable ambiguity report."""
    m = analysis["metrics"]
    lines = [
        f"Ambiguity: {analysis['ambiguity_class']} ({analysis['ambiguity_index']:.2f})",
        f"  Pronoun reference ambiguity:  {m['pronoun_reference_ambiguity']:.3f}",
        f"  PP attachment ambiguity:     {m['pp_attachment_ambiguity']:.3f}",
        f"  Lexical ambiguity rate:        {m['lexical_ambiguity_rate']:.3f}",
        f"  Scope ambiguity rate:          {m['scope_ambiguity_rate']:.3f}",
        f"  Dangling modifier rate:        {m['dangling_modifier_rate']:.3f}",
        f"  ({analysis['sentence_count']} sentences, {analysis['paragraph_count']} paragraphs)",
    ]
    return "\n".join(lines)
