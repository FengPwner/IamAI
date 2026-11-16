#!/usr/bin/env python3
"""writer_abstraction_density — measure how much prose lives in the realm of ideas.

Abstraction is the distance between language and the physical world.
"The cat sat on the mat" is concrete; you can picture it.  "The
principle of felinity governs the domestic spatial negotiation" is
abstract; you cannot photograph it.

Neither end of the spectrum is inherently better.  Philosophy needs
abstraction; journalism needs concrete detail.  But knowing where a
text sits helps calibrate it for its audience.  A user manual written
at philosophical altitude will frustrate; a poem about plumbing will
bore (or amuse).

Abstraction manifests through five measurable channels.
**Nominalized abstractions** are verbs and adjectives buried as
nouns: "implementation", "understanding", "development", "awareness".
Each suffix — -tion, -sion, -ment, -ness, -ity, -ance, -ence, -ism,
-hood, -ship — converts something you can do or feel into something
you can only discuss.  **Universal quantifiers** make sweeping claims
that transcend any particular instance: "all", "every", "always",
"never", "nothing", "everyone".  **Abstract verbs** describe mental
or conceptual processes rather than physical actions: "believe",
"understand", "consider", "imagine", "theorize", "conceptualize".
**Intangible nouns** name things you cannot touch, see, or photograph:
"idea", "concept", "notion", "principle", "paradigm", "framework",
"essence", "nature", "truth", "justice".  **Generalization markers**
signal that the writer is ascending from the specific to the general:
"in general", "by nature", "fundamentally", "essentially", "at its
core", "in principle".

A text with high abstraction density talks about concepts, systems,
and categories.  A text with low abstraction density talks about
things, people, and events.  Most good writing moves between the two,
using abstraction to frame and concreteness to ground.

This module measures abstraction density as a composite index
(0.0 – 1.0) across five independent channels, orthogonal to
concreteness (which measures sensory detail), specificity (which
measures precision of reference), formality (which measures register),
hedging (which measures commitment avoidance), and verbosity (which
measures padding-to-payload ratio).

written by Qwen during manual caretaker visit 648, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── nominalized abstractions ────────────────────────────────────
# Words whose suffix signals verb/adjective → concept conversion.
# We match suffixes, excluding common concrete nouns (e.g. "station",
# "foundation" as a physical building, "ornament").

_NOMINALIZATION_SUFFIXES: List[re.Pattern] = [
    re.compile(r"\b\w{4,}tion\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}sion\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}ment\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}ness\b", re.IGNORECASE),
    re.compile(r"\b\w{3,}ity\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}ance\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}ence\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}ism\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}hood\b", re.IGNORECASE),
    re.compile(r"\b\w{4,}ship\b", re.IGNORECASE),
]

# Concrete nouns that happen to end in abstraction suffixes — exclude.
_NOMINALIZATION_EXCLUSIONS = set(
    w.lower()
    for w in [
        "station",
        "nation",
        "ration",
        "cation",
        "lotion",
        "motion",
        "notion",
        "potion",
        "portion",
        "caption",
        "caution",
        "auction",
        "fraction",
        "fraction",
        "function",
        "junction",
        "punctuation",
        "sanction",
        "section",
        "question",
        "suggestion",
        "digestion",
        "foundation",
        "ornament",
        "garment",
        "pavement",
        "apartment",
        "compartment",
        "entertainment",
        "shipment",
        "equipment",
        "document",
        "argument",
        "monument",
        "firmament",
        "testament",
        "wilderness",
        "fortress",
        "lioness",
        "princess",
        "hostess",
        "goddess",
        "business",
        "witness",
        "madness",
        "sadness",
        "gladness",
        "goodness",
        "illness",
        "thickness",
        "darkness",
        "weakness",
        "citizenship",
        "fellowship",
        "membership",
        "partnership",
        "friendship",
        "leadership",
        "championship",
        "township",
        "warship",
        "spaceship",
        "childhood",
        "neighborhood",
        "manhood",
        "womanhood",
        "adulthood",
        "brotherhood",
        "sisterhood",
        "priesthood",
        "likelihood",
        "livelihood",
        "baptism",
        "tourism",
        "organism",
        "mechanism",
        "criticism",
        "optimism",
        "pessimism",
        "realism",
        "idealism",
        "rationalism",
        "capitalism",
        "socialism",
        "communism",
        "fascism",
        "racism",
        "sexism",
        "ageism",
        "terrorism",
        "patriotism",
        "altruism",
        "magnetism",
        "volcanism",
        "metabolism",
    ]
)


# ── universal quantifiers ──────────────────────────────────────
# Words that make sweeping, all-encompassing claims.

_UNIVERSAL_QUANTIFIERS: List[re.Pattern] = [
    re.compile(r"\ball\b", re.IGNORECASE),
    re.compile(r"\bevery\b", re.IGNORECASE),
    re.compile(r"\beveryone\b", re.IGNORECASE),
    re.compile(r"\beverybody\b", re.IGNORECASE),
    re.compile(r"\beverything\b", re.IGNORECASE),
    re.compile(r"\beverywhere\b", re.IGNORECASE),
    re.compile(r"\balways\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bnothing\b", re.IGNORECASE),
    re.compile(r"\bnobody\b", re.IGNORECASE),
    re.compile(r"\bnowhere\b", re.IGNORECASE),
    re.compile(r"\bno\s+one\b", re.IGNORECASE),
    re.compile(r"\beach\s+and\s+every\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+exception\b", re.IGNORECASE),
    re.compile(r"\buniversally\b", re.IGNORECASE),
    re.compile(r"\binvariably\b", re.IGNORECASE),
    re.compile(r"\babsolutely\b", re.IGNORECASE),
    re.compile(r"\btotally\b", re.IGNORECASE),
    re.compile(r"\bcompletely\b", re.IGNORECASE),
    re.compile(r"\bentirely\b", re.IGNORECASE),
]


# ── abstract verbs ─────────────────────────────────────────────
# Verbs that describe mental or conceptual processes, not physical
# actions.

_ABSTRACT_VERBS: List[re.Pattern] = [
    re.compile(r"\bbelieve[ds]?\b", re.IGNORECASE),
    re.compile(r"\bunderstands?\b", re.IGNORECASE),
    re.compile(r"\bconsider[sed]*\b", re.IGNORECASE),
    re.compile(r"\bimagin(?:e[ds]?|ed)\b", re.IGNORECASE),
    re.compile(r"\bassum(?:e[ds]?|ed)\b", re.IGNORECASE),
    re.compile(r"\bpresum(?:e[ds]?|ed)\b", re.IGNORECASE),
    re.compile(r"\btheoriz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bconceptualiz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bcontemplat(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bponder[sed]*\b", re.IGNORECASE),
    re.compile(r"\breflect[sed]*\b", re.IGNORECASE),
    re.compile(r"\bspeculat(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\binterpret[sed]*\b", re.IGNORECASE),
    re.compile(r"\bperceiv(?:e[ds]?|ed)\b", re.IGNORECASE),
    re.compile(r"\benvision[sed]*\b", re.IGNORECASE),
    re.compile(r"\bhypothesiz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bpostulat(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\binfer[sred]*\b", re.IGNORECASE),
    re.compile(r"\bdeduc(?:e[ds]?|ed)\b", re.IGNORECASE),
    re.compile(r"\brationaliz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bcomprehend[sed]*\b", re.IGNORECASE),
    re.compile(r"\bapprehend[sed]*\b", re.IGNORECASE),
    re.compile(r"\bcogniz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\breason[sed]*\b", re.IGNORECASE),
    re.compile(r"\babstrac[ted]*\b", re.IGNORECASE),
    re.compile(r"\bgeneraliz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bcategoriz(?:e[ds]?|ed|ing)\b", re.IGNORECASE),
]


# ── intangible nouns ───────────────────────────────────────────
# Nouns that name things you cannot touch, see, or photograph.

_INTANGIBLE_NOUNS: List[re.Pattern] = [
    re.compile(r"\bidea[s]?\b", re.IGNORECASE),
    re.compile(r"\bconcept[s]?\b", re.IGNORECASE),
    re.compile(r"\bnotion[s]?\b", re.IGNORECASE),
    re.compile(r"\bprinciple[s]?\b", re.IGNORECASE),
    re.compile(r"\btheor(?:y|ies)\b", re.IGNORECASE),
    re.compile(r"\bparadigm[s]?\b", re.IGNORECASE),
    re.compile(r"\bframework[s]?\b", re.IGNORECASE),
    re.compile(r"\bconstruct[s]?\b", re.IGNORECASE),
    re.compile(r"\bessence\b", re.IGNORECASE),
    re.compile(r"\bnature\b", re.IGNORECASE),
    re.compile(r"\btruth[s]?\b", re.IGNORECASE),
    re.compile(r"\bjustice\b", re.IGNORECASE),
    re.compile(r"\bfreedom[s]?\b", re.IGNORECASE),
    re.compile(r"\bliberty\b", re.IGNORECASE),
    re.compile(r"\bequality\b", re.IGNORECASE),
    re.compile(r"\bknowledge\b", re.IGNORECASE),
    re.compile(r"\bwisdom\b", re.IGNORECASE),
    re.compile(r"\bmeaning\b", re.IGNORECASE),
    re.compile(r"\bpurpose[s]?\b", re.IGNORECASE),
    re.compile(r"\bvalue[s]?\b", re.IGNORECASE),
    re.compile(r"\bvirtue[s]?\b", re.IGNORECASE),
    re.compile(r"\bmorality\b", re.IGNORECASE),
    re.compile(r"\bethics?\b", re.IGNORECASE),
    re.compile(r"\bbeauty\b", re.IGNORECASE),
    re.compile(r"\blove\b", re.IGNORECASE),
    re.compile(r"\bhope[s]?\b", re.IGNORECASE),
    re.compile(r"\bfaith\b", re.IGNORECASE),
    re.compile(r"\bcourage\b", re.IGNORECASE),
    re.compile(r"\bintegrity\b", re.IGNORECASE),
    re.compile(r"\bdignity\b", re.IGNORECASE),
    re.compile(r"\bsoul[s]?\b", re.IGNORECASE),
    re.compile(r"\bspirit[s]?\b", re.IGNORECASE),
    re.compile(r"\bconsciousness\b", re.IGNORECASE),
    re.compile(r"\bexistence\b", re.IGNORECASE),
    re.compile(r"\breality\b", re.IGNORECASE),
    re.compile(r"\bidentity\b", re.IGNORECASE),
    re.compile(r"\bculture\b", re.IGNORECASE),
    re.compile(r"\bsociety\b", re.IGNORECASE),
    re.compile(r"\btradition[s]?\b", re.IGNORECASE),
    re.compile(r"\bphilosophy\b", re.IGNORECASE),
    re.compile(r"\bideology\b", re.IGNORECASE),
    re.compile(r"\bworldview\b", re.IGNORECASE),
]


# ── generalization markers ─────────────────────────────────────
# Phrases that signal ascent from specific to general.

_GENERALIZATION_MARKERS: List[re.Pattern] = [
    re.compile(r"\bin\s+general\b", re.IGNORECASE),
    re.compile(r"\bby\s+nature\b", re.IGNORECASE),
    re.compile(r"\bfundamentally\b", re.IGNORECASE),
    re.compile(r"\bessentially\b", re.IGNORECASE),
    re.compile(r"\bat\s+its\s+core\b", re.IGNORECASE),
    re.compile(r"\bin\s+principle\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+whole\b", re.IGNORECASE),
    re.compile(r"\bin\s+essence\b", re.IGNORECASE),
    re.compile(r"\bby\s+definition\b", re.IGNORECASE),
    re.compile(r"\bby\s+its\s+(?:very\s+)?nature\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+abstract\b", re.IGNORECASE),
    re.compile(r"\bat\s+a\s+(?:deep|fundamental|basic)\s+level\b", re.IGNORECASE),
    re.compile(r"\bbroadly\s+speaking\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+grand\s+scheme\b", re.IGNORECASE),
    re.compile(r"\bon\s+a\s+(?:deep|fundamental|basic|philosophical)\s+level\b", re.IGNORECASE),
    re.compile(r"\bat\s+(?:the\s+)?root\b", re.IGNORECASE),
    re.compile(r"\bin\s+(?:the\s+)?final\s+analysis\b", re.IGNORECASE),
    re.compile(r"\bwhen\s+all\s+is\s+said\s+and\s+done\b", re.IGNORECASE),
    re.compile(r"\bthe\s+nature\s+of\b", re.IGNORECASE),
    re.compile(r"\bthe\s+essence\s+of\b", re.IGNORECASE),
]


# ── result dataclass ────────────────────────────────────────────


@dataclass
class AbstractionDensityResult:
    """Results of abstraction density analysis."""

    # Raw counts
    nominalization_count: int = 0
    universal_count: int = 0
    abstract_verb_count: int = 0
    intangible_noun_count: int = 0
    generalization_count: int = 0

    # Rates per 100 sentences
    nominalization_rate: float = 0.0
    universal_rate: float = 0.0
    abstract_verb_rate: float = 0.0
    intangible_noun_rate: float = 0.0
    generalization_rate: float = 0.0

    # Composite
    abstraction_index: float = 0.0
    classification: str = "grounded"

    # Metadata
    total_sentences: int = 0
    total_words: int = 0
    total_abstractions: int = 0
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


def _count_pattern_matches(text: str, patterns: List[re.Pattern]) -> int:
    """Count total matches across a list of patterns."""
    return sum(len(p.findall(text)) for p in patterns)


def _count_nominalizations(text: str) -> int:
    """Count nominalized abstractions, excluding concrete lookalikes."""
    count = 0
    words = _WORD_SPLIT.findall(text)
    for word in words:
        lower = word.lower()
        if lower in _NOMINALIZATION_EXCLUSIONS:
            continue
        for pattern in _NOMINALIZATION_SUFFIXES:
            if pattern.fullmatch(word):
                count += 1
                break
    return count


# ── main measurement function ───────────────────────────────────


def measure_abstraction_density(text: str) -> AbstractionDensityResult:
    """Measure abstraction density of a text.

    Returns an AbstractionDensityResult with abstraction_index (0.0–1.0)
    and classification.
    """
    result = AbstractionDensityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "grounded"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    scale = 100.0 / max(sentences, 1)

    # ── count each channel ───────────────────────────────────
    result.nominalization_count = _count_nominalizations(text)
    result.universal_count = _count_pattern_matches(text, _UNIVERSAL_QUANTIFIERS)
    result.abstract_verb_count = _count_pattern_matches(text, _ABSTRACT_VERBS)
    result.intangible_noun_count = _count_pattern_matches(text, _INTANGIBLE_NOUNS)
    result.generalization_count = _count_pattern_matches(text, _GENERALIZATION_MARKERS)

    result.total_abstractions = (
        result.nominalization_count
        + result.universal_count
        + result.abstract_verb_count
        + result.intangible_noun_count
        + result.generalization_count
    )

    # ── rates per 100 sentences ──────────────────────────────
    result.nominalization_rate = round(result.nominalization_count * scale, 3)
    result.universal_rate = round(result.universal_count * scale, 3)
    result.abstract_verb_rate = round(result.abstract_verb_count * scale, 3)
    result.intangible_noun_rate = round(result.intangible_noun_count * scale, 3)
    result.generalization_rate = round(result.generalization_count * scale, 3)

    # ── composite abstraction index (0.0 – 1.0) ─────────────
    # Normalize each channel to ~0–1 via typical maxima
    cap_nom = min(1.0, result.nominalization_rate / 40.0)
    cap_uni = min(1.0, result.universal_rate / 15.0)
    cap_verb = min(1.0, result.abstract_verb_rate / 20.0)
    cap_noun = min(1.0, result.intangible_noun_rate / 25.0)
    cap_gen = min(1.0, result.generalization_rate / 8.0)

    composite = (
        0.25 * cap_nom
        + 0.15 * cap_uni
        + 0.20 * cap_verb
        + 0.25 * cap_noun
        + 0.15 * cap_gen
    )
    result.abstraction_index = round(min(1.0, composite), 4)

    # ── classification ───────────────────────────────────────
    idx = result.abstraction_index
    if idx < 0.10:
        result.classification = "grounded"
    elif idx < 0.25:
        result.classification = "tangible"
    elif idx < 0.45:
        result.classification = "moderate"
    elif idx < 0.65:
        result.classification = "abstract"
    else:
        result.classification = "rarefied"

    result.details = {
        "nominalization_rate": result.nominalization_rate,
        "universal_rate": result.universal_rate,
        "abstract_verb_rate": result.abstract_verb_rate,
        "intangible_noun_rate": result.intangible_noun_rate,
        "generalization_rate": result.generalization_rate,
        "abstraction_index": result.abstraction_index,
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

    r = measure_abstraction_density(text)
    print(f"abstraction_index         : {r.abstraction_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"nominalization_rate       : {r.nominalization_rate}")
    print(f"universal_rate            : {r.universal_rate}")
    print(f"abstract_verb_rate        : {r.abstract_verb_rate}")
    print(f"intangible_noun_rate      : {r.intangible_noun_rate}")
    print(f"generalization_rate       : {r.generalization_rate}")
    print(f"total_abstractions        : {r.total_abstractions}")
    print(f"total_sentences           : {r.total_sentences}")
    print(f"total_words               : {r.total_words}")
