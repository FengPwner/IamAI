#!/usr/bin/env python3
"""writer_syntactic_complexity — measure how syntactically elaborate prose is.

Syntactic complexity is the distance between "see Dick run" and the
opening sentence of *Absalom, Absalom!*  It captures how much
grammatical machinery a sentence deploys to deliver its meaning.

Complex syntax is not good or bad.  Legal documents need subordinate
clauses because the world they describe is conditional.  Children's
books avoid them because seven-year-old working memory is finite.
Technical documentation oscillates: the overview is simple, the
footnotes are baroque.

This module measures syntactic complexity across seven channels.
**Passive voice** buries the agent ("the ball was thrown" vs "she
threw the ball").  **Subordination** embeds one clause inside
another ("because it rained, the match was cancelled").
**Coordination** chains independent clauses with conjunctions
("she ran, and he followed, but they were too late").  **Relative
clauses** nest description inside noun phrases ("the man who sold
the world").  **Prepositional chains** stack modifiers ("the door
of the house at the end of the road on the hill").  **Participles**
compress clauses into modifiers ("running late, she skipped
breakfast").  **Sentence-length variation** captures structural
rhythm — a text that alternates between three-word and forty-word
sentences is more complex than one that holds steady.

Composite complexity_index (0.0 – 1.0) classifies prose as:
  telegraphic  (0.0–0.2)  — "stop. drop. roll."
  simple       (0.2–0.4)  — plain speech, children's books
  moderate     (0.4–0.6)  — typical journalism, blog posts
  elaborate    (0.6–0.8)  — academic papers, literary fiction
  baroque      (0.8–1.0)  — legal contracts, Faulkner, Proust

Orthogonal to hedging (epistemic caution), verbosity (padding),
specificity (reference precision), formality (register), and
exemplification density (use of examples).  A short sentence can
be syntactically complex ("Found dead, the dog, which had been
missing for weeks, was identified by its collar.") and a long
sentence can be syntactically simple ("She walked and walked and
walked and walked.").

written by Qwen during manual caretaker visit 647, 2026-11-16
"""

import re
import math
from dataclasses import dataclass, field
from typing import List


# ── sentence splitting ──────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── passive voice ───────────────────────────────────────────────
# Auxiliary "be" forms followed by a past participle.
# This is a heuristic — "was running" is progressive, not passive,
# but "was given" is passive.  We approximate by matching be-forms
# followed by words ending in -ed, -en, -t (built, sent, kept).

_BE_FORMS = re.compile(
    r"\b(?:is|are|was|were|be|been|being|am)\b",
    re.IGNORECASE,
)

# Common irregular past participles that don't end in -ed or -en.
_IRREGULAR_PARTICIPLES = {
    "done", "gone", "seen", "known", "shown", "thrown", "grown",
    "blown", "drawn", "flown", "frozen", "stolen", "sworn", "torn",
    "worn", "born", "swollen", "broken", "spoken", "chosen", "woken",
    "written", "ridden", "hidden", "forgotten", "bitten", "smitten",
    "driven", "given", "forgiven", "risen", "fallen", "taken", "shaken",
    "mistaken", "undertaken", "eaten", "beaten", "trodden", "woven",
    "made", "paid", "laid", "said", "had",
    "found", "bound", "ground", "wound", "sounded",
    "built", "dealt", "felt", "kept", "left", "meant", "met", "slept",
    "spent", "wept", "crept", "swept", "knelt", "leapt",
    "brought", "bought", "caught", "fought", "sought", "taught", "thought",
    "sold", "told", "held",
    "lost", "shot", "got", "forgot", "begot",
    "sung", "rung", "hung", "clung", "strung", "swung", "stung", "wrung",
    "drunk", "shrunk", "sunk", "stunk",
    "begun", "run", "spun", "won",
    "come", "become", "overcome",
    "cut", "put", "set", "let", "shut", "split", "quit", "hit", "hurt",
    "cast", "cost", "read", "shed", "spread", "thrust",
    "stood", "understood", "withstood",
    "led", "fed", "bled", "bred", "sped", "fled",
    "lit", "sat", "spat", "got",
    "worn", "torn", "born", "sworn",
}

_PASSIVE_PATTERN = re.compile(
    r"\b(?:is|are|was|were|be|been|being|am)\s+"
    r"(?:being\s+|been\s+)?"  # optional "being" or "been": "is being built", "has been found"
    r"(?:\w+\s+){0,3}?"       # optional adverbs: "was quickly given"
    r"(\w+)",                  # capture the candidate past participle
    re.IGNORECASE,
)


# ── subordination markers ───────────────────────────────────────

_SUBORDINATION_MARKERS: List[re.Pattern] = [
    re.compile(r"\bbecause\b", re.IGNORECASE),
    re.compile(r"\balthough\b", re.IGNORECASE),
    re.compile(r"\bthough\b", re.IGNORECASE),
    re.compile(r"\bwhile\b", re.IGNORECASE),
    re.compile(r"\bwhilst\b", re.IGNORECASE),
    re.compile(r"\bsince\b", re.IGNORECASE),
    re.compile(r"\bunless\b", re.IGNORECASE),
    re.compile(r"\bwhereas\b", re.IGNORECASE),
    re.compile(r"\bwhether\b", re.IGNORECASE),
    re.compile(r"\bif\s+(?:only|so|need|not)\b", re.IGNORECASE),
    re.compile(r"\beven\s+(?:if|though)\b", re.IGNORECASE),
    re.compile(r"\bso\s+that\b", re.IGNORECASE),
    re.compile(r"\bin\s+order\s+(?:to|that)\b", re.IGNORECASE),
    re.compile(r"\bprovided\s+(?:that)?\b", re.IGNORECASE),
    re.compile(r"\bassuming\s+(?:that)?\b", re.IGNORECASE),
    re.compile(r"\bgiven\s+that\b", re.IGNORECASE),
    re.compile(r"\bnow\s+that\b", re.IGNORECASE),
    re.compile(r"\buntil\b", re.IGNORECASE),
    re.compile(r"\bwhenever\b", re.IGNORECASE),
    re.compile(r"\bwherever\b", re.IGNORECASE),
    re.compile(r"\bdespite\s+(?:the\s+fact\s+that)?\b", re.IGNORECASE),
    re.compile(r"\bin\s+spite\s+of\b", re.IGNORECASE),
    re.compile(r"\bas\s+(?:long\s+as|soon\s+as|far\s+as)\b", re.IGNORECASE),
    re.compile(r"\bno\s+sooner\s+than\b", re.IGNORECASE),
    re.compile(r"\brather\s+than\b", re.IGNORECASE),
]


# ── coordination (comma + conjunction joining clauses) ──────────

_COORDINATION_PATTERNS: List[re.Pattern] = [
    re.compile(r",\s*and\b", re.IGNORECASE),
    re.compile(r",\s*but\b", re.IGNORECASE),
    re.compile(r",\s*yet\b", re.IGNORECASE),
    re.compile(r",\s*so\b", re.IGNORECASE),
    re.compile(r",\s*or\b", re.IGNORECASE),
    re.compile(r",\s*for\b", re.IGNORECASE),
    re.compile(r",\s*nor\b", re.IGNORECASE),
    re.compile(r";\s*(?:however|therefore|moreover|furthermore|nevertheless|consequently)\b", re.IGNORECASE),
    re.compile(r";\s*$", re.IGNORECASE),  # semicolons joining clauses
]


# ── relative clauses ────────────────────────────────────────────

_RELATIVE_PRONOUNS: List[re.Pattern] = [
    re.compile(r"\bwho\b", re.IGNORECASE),
    re.compile(r"\bwhom\b", re.IGNORECASE),
    re.compile(r"\bwhose\b", re.IGNORECASE),
    re.compile(r"\bwhich\b", re.IGNORECASE),
    re.compile(r"\bthat\b", re.IGNORECASE),
    re.compile(r"\bwhere\b", re.IGNORECASE),
]


# ── prepositional chains ────────────────────────────────────────
# Two or more consecutive prepositional phrases (prep + noun + prep + noun).

_PREPOSITIONS = {
    "of", "in", "on", "at", "to", "for", "with", "from", "by",
    "about", "into", "through", "after", "over", "between",
    "under", "above", "below", "before", "behind", "beyond",
    "beneath", "beside", "besides", "despite", "during",
    "except", "inside", "near", "outside", "past", "since",
    "toward", "towards", "underneath", "upon", "within",
    "without", "across", "along", "among", "around",
}

_PREP_CHAIN = re.compile(
    r"\b(?:of|in|on|at|to|for|with|from|by|about|into|through|after|over|"
    r"between|under|above|below|before|behind|beyond|beneath|beside|"
    r"despite|during|except|inside|near|outside|past|since|toward|"
    r"towards|underneath|upon|within|without|across|along|among|around)\b"
    r"\s+\w+(?:\s+\w+){0,3}\s+"
    r"(?:of|in|on|at|to|for|with|from|by|about|into|through|after|over|"
    r"between|under|above|below|before|behind|beyond|beneath|beside|"
    r"despite|during|except|inside|near|outside|past|since|toward|"
    r"towards|underneath|upon|within|without|across|along|among|around)\b",
    re.IGNORECASE,
)


# ── participles as modifiers ────────────────────────────────────

_PARTICIPLE_MODIFIERS: List[re.Pattern] = [
    # Present participle at sentence start: "Running late, she..."
    re.compile(r"^\w+ing\b.*,", re.MULTILINE),
    # Past participle at sentence start: "Exhausted by the climb, he..."
    re.compile(r"^\w+(?:ed|en)\b.*,", re.MULTILINE),
    # Embedded participles: "the man sitting there" / "the book written by her"
    re.compile(r"\b\w+\s+(?:sitting|standing|lying|running|walking|looking|"
               r"holding|carrying|wearing|reading|speaking|living|working)\b",
               re.IGNORECASE),
    re.compile(r"\b\w+\s+(?:written|given|taken|made|built|found|known|"
               r"called|named|used|done|seen|left|told|shown|held)\b",
               re.IGNORECASE),
]


# ── dataclass ────────────────────────────────────────────────────


@dataclass
class ComplexityResult:
    """Result of syntactic complexity analysis."""

    sentence_count: int = 0
    total_words: int = 0
    avg_sentence_length: float = 0.0
    sentence_length_cv: float = 0.0

    passive_count: int = 0
    subordination_count: int = 0
    coordination_count: int = 0
    relative_count: int = 0
    preposition_chain_count: int = 0
    participle_count: int = 0

    passive_ratio: float = 0.0          # per 100 sentences
    subordination_ratio: float = 0.0    # per 100 sentences
    coordination_ratio: float = 0.0     # per 100 sentences
    relative_ratio: float = 0.0         # per 100 sentences
    preposition_chain_ratio: float = 0.0  # per 100 sentences
    participle_ratio: float = 0.0       # per 100 sentences

    complexity_index: float = 0.0       # 0.0 – 1.0
    classification: str = "simple"

    @property
    def total_complexity_markers(self) -> int:
        return (
            self.passive_count
            + self.subordination_count
            + self.coordination_count
            + self.relative_count
            + self.preposition_chain_count
            + self.participle_count
        )


# ── main entry point ────────────────────────────────────────────


def measure_syntactic_complexity(text: str) -> ComplexityResult:
    """Measure syntactic complexity of a text.

    Args:
        text: prose to analyze.

    Returns:
        ComplexityResult with per-channel ratios, composite index,
        and classification.
    """
    result = ComplexityResult()

    if not text or not text.strip():
        return result

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    if not sentences:
        return result

    result.sentence_count = len(sentences)

    # word counts per sentence
    lengths = []
    for s in sentences:
        words = _WORD_SPLIT.findall(s)
        lengths.append(len(words))

    result.total_words = sum(lengths)
    result.avg_sentence_length = result.total_words / result.sentence_count

    # coefficient of variation for sentence length
    if len(lengths) >= 2:
        mean_l = result.avg_sentence_length
        variance = sum((l - mean_l) ** 2 for l in lengths) / len(lengths)
        std_l = math.sqrt(variance)
        result.sentence_length_cv = std_l / mean_l if mean_l > 0 else 0.0
    else:
        result.sentence_length_cv = 0.0

    n = result.sentence_count
    per_100 = 100.0 / n

    # ── count passive constructions ─────────────────────────
    passive_hits = 0
    for s in sentences:
        for m in _PASSIVE_PATTERN.finditer(s):
            word = m.group(1).lower()
            # Check if it's a past participle: -ed, -en, or irregular
            if (word.endswith("ed") or word.endswith("en")
                    or word in _IRREGULAR_PARTICIPLES):
                passive_hits += 1
    result.passive_count = passive_hits
    result.passive_ratio = passive_hits * per_100

    # ── count subordination markers ─────────────────────────
    sub_hits = 0
    for s in sentences:
        for pat in _SUBORDINATION_MARKERS:
            sub_hits += len(pat.findall(s))
    result.subordination_count = sub_hits
    result.subordination_ratio = sub_hits * per_100

    # ── count coordination patterns ─────────────────────────
    coord_hits = 0
    for s in sentences:
        for pat in _COORDINATION_PATTERNS:
            coord_hits += len(pat.findall(s))
    result.coordination_count = coord_hits
    result.coordination_ratio = coord_hits * per_100

    # ── count relative clauses ──────────────────────────────
    rel_hits = 0
    for s in sentences:
        for pat in _RELATIVE_PRONOUNS:
            rel_hits += len(pat.findall(s))
    result.relative_count = rel_hits
    result.relative_ratio = rel_hits * per_100

    # ── count prepositional chains ──────────────────────────
    prep_hits = 0
    for s in sentences:
        prep_hits += len(_PREP_CHAIN.findall(s))
    result.preposition_chain_count = prep_hits
    result.preposition_chain_ratio = prep_hits * per_100

    # ── count participle modifiers ──────────────────────────
    part_hits = 0
    for s in sentences:
        for pat in _PARTICIPLE_MODIFIERS:
            part_hits += len(pat.findall(s))
    result.participle_count = part_hits
    result.participle_ratio = part_hits * per_100

    # ── composite complexity index ──────────────────────────
    # Normalize each channel to [0, 1] using saturation thresholds.
    # Thresholds are "per 100 sentences" values that map to 1.0.

    passive_norm = min(result.passive_ratio / 50.0, 1.0)
    subordination_norm = min(result.subordination_ratio / 80.0, 1.0)
    coordination_norm = min(result.coordination_ratio / 40.0, 1.0)
    relative_norm = min(result.relative_ratio / 60.0, 1.0)
    prep_chain_norm = min(result.preposition_chain_ratio / 30.0, 1.0)
    participle_norm = min(result.participle_ratio / 40.0, 1.0)
    cv_norm = min(result.sentence_length_cv / 1.0, 1.0)

    # Weights: subordination and sentence-length variety are the
    # strongest signals of syntactic complexity.
    result.complexity_index = round(
        0.10 * passive_norm
        + 0.25 * subordination_norm
        + 0.10 * coordination_norm
        + 0.15 * relative_norm
        + 0.10 * prep_chain_norm
        + 0.10 * participle_norm
        + 0.20 * cv_norm,
        4,
    )

    # Clamp
    result.complexity_index = max(0.0, min(1.0, result.complexity_index))

    # ── classification ──────────────────────────────────────
    ci = result.complexity_index
    if ci < 0.2:
        result.classification = "telegraphic"
    elif ci < 0.4:
        result.classification = "simple"
    elif ci < 0.6:
        result.classification = "moderate"
    elif ci < 0.8:
        result.classification = "elaborate"
    else:
        result.classification = "baroque"

    return result
