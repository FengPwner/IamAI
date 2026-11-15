#!/usr/bin/env python3
"""writer_anaphora_density — measure how much prose relies on back-references.

Anaphora is the linguistic act of pointing backward.  When a writer
says "the committee reviewed the proposal.  **It** was approved
unanimously", the pronoun *it* is an anaphoric reference — a word
whose meaning depends entirely on what came before.  Without its
antecedent, *it* is a hollow vessel; with it, *it* is a compression
algorithm that saves the reader from re-reading "the proposal".

Anaphoric language is the prose of cohesion.  Where specificity names
things fully ("the 2024 revenue projection for the APAC region"),
anaphora assumes the reader is keeping score ("it exceeded
expectations").  A text with high anaphora density trusts its reader
to track referents across sentences; a text with low anaphora density
repeats nouns explicitly, prioritizing clarity over elegance.

Anaphora operates through several distinct channels.  **Personal
pronouns** refer back to previously named entities: "he", "she",
"it", "they", "them", "his", "her", "its", "their", "him",
"them".  **Demonstrative pronouns** point to previously mentioned
objects or ideas: "this", "that", "these", "those" (when used
without a following noun).  **Definite articles with anaphoric
nouns** re-reference known entities: "the committee", "the
proposal", "the system" — where "the" signals that the referent
was already introduced.  **Substitutive expressions** replace
full descriptions with back-referencing phrases: "the former",
"the latter", "the above", "the aforementioned", "the said",
"such", "one" (as substitute).  **Relative pronouns** create
subordinate clauses that refer back to their antecedent: "which",
"who", "whom", "whose", "where" (when non-interrogative).
**Ellipsis** omits repeated material entirely: "She ordered coffee;
he, tea" — the verb is anaphorically recovered from context.

A text's anaphora density reveals its assumptions about reader
attention.  Academic prose uses heavy anaphora — "this finding",
"these results", "it demonstrates" — trusting the reader to follow
argument threads across paragraphs.  Legal writing avoids anaphora
almost entirely — every reference repeats the full noun phrase
("the aforementioned party of the first part") because ambiguity
in referents can cost millions.  Technical documentation mixes
both — introducing terms fully, then switching to pronouns within
a paragraph, but resetting to full nouns at section boundaries.
Journalism uses anaphora within articles — "the president", "he",
"the administration" — but leads each paragraph with enough context
that a reader skimming can still follow.  Fiction uses anaphora
to create intimacy — pronouns feel natural because we inhabit
characters — but overuses it at the risk of ambiguity ("he looked
at him" — who is who?).  Instructional writing avoids anaphora —
"click the button.  Then click **the Save button**" — because
confusion means the user is stuck.

This module measures **how frequently, how diversely, and through
what channels a text relies on anaphoric back-references** —
personal pronouns, demonstratives, definite-article re-references,
substitutive expressions, relative pronouns, and elliptical
constructions.

Orthogonality to other metrics
-------------------------------

- **specificity** tracks how precisely entities are described —
  "the server" vs "the primary PostgreSQL replica in us-east-1a".
  Specificity measures the *detail* of the description; anaphora
  measures whether the description is *given at all*.  A text can
  be specific and anaphoric ("the aforementioned primary PostgreSQL
  replica") or vague and explicit ("a server").  Specificity is
  resolution; anaphora is recall.

- **concreteness** tracks abstract vs tangible language — "freedom"
  vs "the prisoner's release".  Concreteness measures whether the
  language touches physical reality; anaphora measures whether the
  language re-references previously introduced entities.  A text
  can be concrete and anaphoric ("she held it" — where "it" is a
  previously named physical object) or abstract and explicit
  ("the concept of justice pervades all legal systems").

- **formality** tracks register — formal vs informal language.
  Anaphoric density is somewhat independent of formality: legal
  writing is highly formal but avoids pronouns; casual
  conversation is informal and drowns in them.  Academic writing
  is both formal and anaphoric.  Technical documentation is
  moderately formal but deliberately reduces anaphora at key
  points for clarity.

- **vocabulary_richness** tracks lexical diversity — how many
  unique words appear relative to text length.  Anaphoric
  language *reduces* vocabulary richness by reusing pronouns
  instead of repeating diverse nouns.  But the relationship is
  not deterministic: a text can be pronoun-heavy yet lexically
  rich in other dimensions (verbs, adjectives, technical terms).

- **topic_drift** tracks whether a text stays on subject.  High
  anaphora density often correlates with low topic drift —
  pronouns need stable antecedents, which means the topic must
  remain consistent.  But a text can maintain topic through
  explicit repetition rather than anaphora, and can drift while
  being pronoun-heavy (stream of consciousness).

Anaphora density asks: **how much of the prose depends on the
reader tracking previously introduced entities, and what does
the distribution of pronominal, demonstrative, definite-article,
substitutive, relative, and elliptical back-references reveal
about the writer's assumptions regarding reader attention?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── personal pronouns (anaphoric uses) ──────────────────────────
# Third-person pronouns that refer back to previously named entities
_PERSONAL_PRONOUN = re.compile(
    r"\b(?:"
    r"he\b|"
    r"she\b|"
    r"it\b(?!'s\s+(?:own|self)|s\s)|"
    r"they\b|"
    r"them\b|"
    r"him\b|"
    r"her\b(?!\s+(?:own|self))|"
    r"his\b|"
    r"hers\b|"
    r"its\b|"
    r"their\b|"
    r"theirs\b|"
    r"himself\b|"
    r"herself\b|"
    r"itself\b|"
    r"themselves\b"
    r")",
    re.IGNORECASE,
)

# ── demonstrative pronouns (standalone, not determiners) ────────
# "this", "that", "these", "those" when not followed by a noun
_DEMONSTRATIVE_PRONOUN = re.compile(
    r"\b(?:"
    r"this\b(?!\s+(?:is|was|will|has|had|may|might|could|should|would|"
    r"must|can|shall|does|did|do|seems?|appears?|looks?|feels?|sounds?|"
    r"kind|sort|type|way|means?|time|year|month|week|day|one|case|"
    r"point|question|issue|problem|idea|thing|approach|method|"
    r"result|finding|study|paper|research|data|evidence|example|"
    r"process|system|service|tool|feature|function|module|class|"
    r"method|pattern|design|model|framework|library|language|"
    r"application|platform|interface|protocol|standard|specification|"
    r"requirement|constraint|assumption|hypothesis|theory|concept|"
    r"principle|rule|law|regulation|policy|guideline|recommendation|"
    r"\w+ing|\w+ed|\w+er|\w+or|\w+tion|\w+ment|\w+ness|\w+ity))|"
    r"that\b(?!\s+(?:is|was|will|has|had|may|might|could|should|would|"
    r"must|can|shall|does|did|do|seems?|appears?|looks?|feels?|sounds?|"
    r"the|a|an|my|your|his|her|its|our|their|no|any|each|every|some|"
    r"kind|sort|type|way|means?|time|year|month|week|day|one|case|"
    r"point|question|issue|problem|idea|thing|approach|method))|"
    r"these\b(?!\s+\w+)|"
    r"those\b(?!\s+\w+)"
    r")",
    re.IGNORECASE,
)

# ── definite-article anaphoric re-reference ─────────────────────
# "the" + common anaphoric nouns that signal back-reference
_DEFINITE_ANAPHORIC = re.compile(
    r"\bthe\s+(?:"
    r"(?:former|latter|above|below|aforementioned|said|"
    r"previously\s+mentioned|previously\s+discussed|"
    r"previously\s+described|previously\s+noted|"
    r"earlier|preceding|foregoing|aforementioned)\b|"
    r"(?:same|very\s+same)\b|"
    r"(?:rest|remainder|remaining)\b"
    r")",
    re.IGNORECASE,
)

# ── substitutive back-reference expressions ─────────────────────
# Phrases that substitute for full descriptions
_SUBSTITUTIVE = re.compile(
    r"\b(?:"
    r"the\s+(?:former|latter|above|below|aforementioned|said|"
    r"previously\s+(?:mentioned|discussed|described|noted|stated)|"
    r"earlier\s+(?:mentioned|discussed|described|noted|stated)|"
    r"preceding|foregoing)\b|"
    r"such\s+(?:as|a|an|that|things?|cases?|instances?|"
    r"conditions?|situations?|circumstances?|matters?|"
    r"issues?|problems?|questions?)|"
    r"(?:the\s+)?(?:one|ones)\b(?=\s+(?:that|who|which|where|when|"
    r"with|in|on|at|from|of|described|mentioned|noted|listed))|"
    r"that\s+of\b|"
    r"those\s+of\b"
    r")",
    re.IGNORECASE,
)

# ── relative pronouns (non-interrogative) ───────────────────────
# "which", "who", "whom", "whose" used as anaphoric connectors
_RELATIVE_PRONOUN = re.compile(
    r"[\s,;:]("
    r"which\b|"
    r"who\b(?!\s+\?)|"
    r"whom\b|"
    r"whose\b(?!\s+\?)|"
    r"where\b(?=\s+\w+\s+\w+)|"
    r"wherein\b|"
    r"whereby\b|"
    r"whereupon\b|"
    r"whereas\b"
    r")",
    re.IGNORECASE,
)

# ── elliptical constructions ────────────────────────────────────
# Omission of repeated material (semicolons with reduced clauses,
# gapping constructions)
_ELLIPTICAL = re.compile(
    r"(?:"
    r";\s+\w+,\s+\w+|"
    r"(?:and|but|or|nor)\s+(?:so|too|neither|either)\s+\w+|"
    r"(?:as\s+does?|as\s+did|as\s+do)\b|"
    r"(?:like\s+does?|like\s+did)\b"
    r")",
    re.IGNORECASE,
)

# ── unique anaphoric forms for diversity ────────────────────────
_ALL_ANAPHORA_LEXICAL = re.compile(
    r"\b(?:"
    r"he|she|it|they|them|him|her|his|hers|its|their|theirs|"
    r"himself|herself|itself|themselves|"
    r"this|that|these|those|"
    r"which|who|whom|whose|wherein|whereby|whereupon|"
    r"former|latter|above|below|aforementioned|said|"
    r"preceding|foregoing|same|such"
    r")\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class AnaphoraDensityResult:
    """Results of anaphora density analysis."""

    # Raw counts
    personal_pronoun_count: int = 0
    demonstrative_pronoun_count: int = 0
    definite_anaphoric_count: int = 0
    substitutive_count: int = 0
    relative_pronoun_count: int = 0
    elliptical_count: int = 0
    unique_anaphoric_forms: int = 0

    # Rates per 100 sentences
    personal_pronoun_rate: float = 0.0
    demonstrative_pronoun_rate: float = 0.0
    definite_anaphoric_rate: float = 0.0
    substitutive_rate: float = 0.0
    relative_pronoun_rate: float = 0.0
    elliptical_rate: float = 0.0

    # Composite
    anaphora_diversity_index: float = 0.0
    anaphora_density_index: float = 0.0
    classification: str = "unanaphoric"

    # Metadata
    total_sentences: int = 0
    details: dict = field(default_factory=dict)


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_matches(pattern: re.Pattern, text: str) -> int:
    """Count non-overlapping regex matches."""
    return len(pattern.findall(text))


# ── main function ───────────────────────────────────────────────


def measure_anaphora_density(text: str) -> AnaphoraDensityResult:
    """Analyze anaphoric back-reference density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    AnaphoraDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = AnaphoraDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    personal = _count_matches(_PERSONAL_PRONOUN, text)
    demonstrative = _count_matches(_DEMONSTRATIVE_PRONOUN, text)
    definite = _count_matches(_DEFINITE_ANAPHORIC, text)
    substitutive = _count_matches(_SUBSTITUTIVE, text)
    relative = _count_matches(_RELATIVE_PRONOUN, text)
    elliptical = _count_matches(_ELLIPTICAL, text)

    # Unique anaphoric forms for diversity
    all_forms = _ALL_ANAPHORA_LEXICAL.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.personal_pronoun_count = personal
    result.demonstrative_pronoun_count = demonstrative
    result.definite_anaphoric_count = definite
    result.substitutive_count = substitutive
    result.relative_pronoun_count = relative
    result.elliptical_count = elliptical
    result.unique_anaphoric_forms = len(unique_forms)

    # Rates per 100 sentences
    result.personal_pronoun_rate = round(personal * scale, 3)
    result.demonstrative_pronoun_rate = round(demonstrative * scale, 3)
    result.definite_anaphoric_rate = round(definite * scale, 3)
    result.substitutive_rate = round(substitutive * scale, 3)
    result.relative_pronoun_rate = round(relative * scale, 3)
    result.elliptical_rate = round(elliptical * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~30)
    max_possible_forms = 30
    result.anaphora_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_personal = min(1.0, result.personal_pronoun_rate / 200.0)
    cap_demonstrative = min(1.0, result.demonstrative_pronoun_rate / 30.0)
    cap_definite = min(1.0, result.definite_anaphoric_rate / 10.0)
    cap_substitutive = min(1.0, result.substitutive_rate / 8.0)
    cap_relative = min(1.0, result.relative_pronoun_rate / 40.0)
    cap_elliptical = min(1.0, result.elliptical_rate / 5.0)
    cap_diversity = result.anaphora_diversity_index

    composite = (
        0.25 * cap_personal
        + 0.12 * cap_demonstrative
        + 0.08 * cap_definite
        + 0.08 * cap_substitutive
        + 0.15 * cap_relative
        + 0.05 * cap_elliptical
        + 0.27 * cap_diversity
    )
    result.anaphora_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.anaphora_density_index
    if idx < 0.05:
        result.classification = "unanaphoric"
    elif idx < 0.15:
        result.classification = "lightly_anaphoric"
    elif idx < 0.35:
        result.classification = "moderately_anaphoric"
    elif idx < 0.60:
        result.classification = "heavily_anaphoric"
    else:
        result.classification = "anaphora_saturated"

    result.details = {
        "personal_pronoun_rate": result.personal_pronoun_rate,
        "demonstrative_pronoun_rate": result.demonstrative_pronoun_rate,
        "definite_anaphoric_rate": result.definite_anaphoric_rate,
        "substitutive_rate": result.substitutive_rate,
        "relative_pronoun_rate": result.relative_pronoun_rate,
        "elliptical_rate": result.elliptical_rate,
        "anaphora_diversity_index": result.anaphora_diversity_index,
        "anaphora_density_index": result.anaphora_density_index,
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

    r = measure_anaphora_density(text)
    print(f"anaphora_density_index        : {r.anaphora_density_index:.4f}")
    print(f"classification                : {r.classification}")
    print(f"personal_pronoun_rate         : {r.personal_pronoun_rate}")
    print(f"demonstrative_pronoun_rate    : {r.demonstrative_pronoun_rate}")
    print(f"definite_anaphoric_rate       : {r.definite_anaphoric_rate}")
    print(f"substitutive_rate             : {r.substitutive_rate}")
    print(f"relative_pronoun_rate         : {r.relative_pronoun_rate}")
    print(f"elliptical_rate               : {r.elliptical_rate}")
    print(f"anaphora_diversity_index      : {r.anaphora_diversity_index}")
    print(f"total_sentences               : {r.total_sentences}")
