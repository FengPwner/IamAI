#!/usr/bin/env python3
"""writer_pleonasm_density — measure how much prose relies on redundant expressions.

Every language accumulates fossils of redundancy.  "Each and every."
"Null and void."  "Past history."  "Free gift."  "Unexpected
surprise."  These pleonasms — expressions where one or more words
repeat meaning already carried by another — are so woven into
idiomatic English that writers deploy them without noticing the
duplication.  They serve rhythm, emphasis, legal precision, or
sheer habit.  But they inflate prose: a text dense in pleonasm
says what it could have said with fewer words, trading concision
for cadence, clarity, or rhetorical weight.

Pleonasm operates through distinct mechanisms.  **Semantic
redundancy** pairs a modifier with a head that already contains
the modifier's meaning — "free gift" (gifts are by definition
free), "end result" (results are necessarily terminal), "past
history" (history is always past).  **Syntactic redundancy**
joins near-synonyms in fixed binomials — "cease and desist,"
"will and testament," "terms and conditions" — a fossil of legal
doublet tradition.  **Morphological redundancy** stacks a
foreign plural marker on a word whose borrowing already carries
it — "ATM machines" (the M stands for machine), "PIN numbers"
(the N stands for number), "HIV virus" (the V stands for virus).
**Verbal pleonasm** adds an unnecessary complement — "see with
your eyes," "hear with your ears," "think in your mind."
**Intensifier pleonasm** applies a degree modifier to an
already-absolute adjective — "very unique," "completely
finished," "totally dead," "absolutely essential."

Pleonasm density is not a quality metric.  Legal writing saturates
in deliberate redundancy for precision ("null and void," "give,
devise, and bequeath").  Political speech leans on it for emphasis
("we will never, ever, ever give up").  Casual prose sprinkles it
for rhythm ("each and every one of you").  Technical writing
sometimes needs it for disambiguation ("added bonus" distinguishes
from potential penalty).  Literary fiction may exploit it for voice
or satire.  And sometimes redundancy is simply unconscious — the
writer's ear for idiom overriding their editorial instinct.

This module measures **how frequently, how diversely, and through
what mechanisms a text deploys pleonastic and redundant
expressions** — semantic redundancies, syntactic binomials and
trinomials, morphological redundancies, verbal pleonasms, and
intensifier pleonasms applied to absolute adjectives.

Orthogonality to other metrics
-------------------------------

- **concision** measures overall brevity — how few words convey
  how much meaning.  Pleonasm is one specific anti-concision
  mechanism (saying the same thing twice), but concision also
  covers verbosity, circumlocution, and padding that are not
  technically redundant.  A text can be verbose without being
  pleonastic ("the feline quadruped proceeded to ambulate" is
  verbose but not redundant); a text can be terse yet contain
  a pleonasm ("free gift" in an otherwise sparse sentence).

- **repetition_index** tracks word and phrase recurrence across
  a text — the same token appearing in multiple locations.
  Pleonasm is local redundancy within a single expression
  ("ATM machine" repeats within three words); repetition is
  global recurrence across sentences or paragraphs.  A text
  can repeat heavily without pleonasm (anaphora in rhetoric)
  and can be pleonastic without repetition (each pleonasm
  appears only once).

- **gradation_density** tracks degree and calibration language.
  Intensifier pleonasm ("very unique") involves a degree word,
  but the diagnostic is redundancy, not gradation: "very large"
  is gradation without pleonasm; "very unique" is pleonasm
  because "unique" already means "one of a kind."

- **vocabulary_richness** measures lexical diversity.  A text
  dense in pleonasm may have low vocabulary richness (the
  redundant words don't add new meaning), but the relationship
  is not deterministic — "null and void" uses two distinct
  words to say one thing, while "blah blah blah" repeats one
  word three times.

- **writer_restraint** measures the ability to leave things
  unsaid.  Pleonasm is the opposite impulse — saying what
  was already said — but restraint also covers omission of
  expected content, not just redundancy.

Pleonasm density asks: **how much of the prose doubles back on
its own meaning, and what does the distribution of semantic,
syntactic, morphological, verbal, and intensifier redundancy
reveal about the writer's relationship to economy and emphasis?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── semantic redundancy ────────────────────────────────────────
# Adjective + noun where the adjective restates what the noun
# already means.
_SEMANTIC_REDUNDANCIES = re.compile(
    r"\b(?:"
    r"free\s+gift(?:s)?|"
    r"past\s+history|"
    r"end\s+result(?:s)?|"
    r"final\s+outcome(?:s)?|"
    r"final\s+result(?:s)?|"
    r"final\s+conclusion(?:s)?|"
    r"future\s+plans?|"
    r"advance\s+planning|"
    r"advance\s+notice|"
    r"advance\s+warning|"
    r"added\s+bonus(?:es)?|"
    r"extra\s+bonus(?:es)?|"
    r"unexpected\s+surprise(?:s)?|"
    r"unexpected\s+event(?:s)?|"
    r"necessary\s+requirement(?:s)?|"
    r"basic\s+fundamental(?:s)?|"
    r"basic\s+essentials?|"
    r"close\s+proximity|"
    r"actual\s+fact(?:s)?|"
    r"true\s+fact(?:s)?|"
    r"new\s+innovation(?:s)?|"
    r"new\s+invention(?:s)?|"
    r"original\s+source(?:s)?|"
    r"reason\s+why|"
    r"revert\s+back|"
    r"return\s+back|"
    r"recall\s+back|"
    r"repeat\s+again|"
    r"reiterate\s+again|"
    r"summarize\s+briefly|"
    r"brief\s+summary|"
    r"brief\s+moment|"
    r"brief\s+instant|"
    r"completely\s+destroy(?:ed|s)?|"
    r"completely\s+eliminate(?:d|s)?|"
    r"completely\s+filled|"
    r"completely\s+empty|"
    r"entirely\s+eliminate(?:d|s)?|"
    r"still\s+remains?|"
    r"still\s+persists?|"
    r"still\s+continues?|"
    r"currently\s+being|"
    r"present\s+incumbent|"
    r"armed\s+gunman|"
    r"unarmed\s+gunman|"
    r"safe\s+haven|"
    r"old\s+customs?|"
    r"old\s+traditions?|"
    r"usual\s+customs?|"
    r"regular\s+routines?|"
    r"general\s+public|"
    r"personal\s+friend(?:s)?|"
    r"personal\s+opinion(?:s)?|"
    r"mutual\s+cooperation|"
    r"mutual\s+agreement|"
    r"joint\s+collaboration|"
    r"collaborate\s+together|"
    r"cooperate\s+together|"
    r"merge\s+together|"
    r"combine\s+together|"
    r"mix\s+together|"
    r"blend\s+together|"
    r"consensus\s+of\s+opinion|"
    r"circulate\s+around|"
    r"proceed(?:ed|s)?\s+ahead|"
    r"continue(?:d|s)?\s+on|"
    r"descend(?:ed|s)?\s+down|"
    r"ascend(?:ed|s)?\s+up|"
    r"rise\s+up|rose\s+up|risen\s+up|"
    r"fall\s+down|fell\s+down|fallen\s+down|"
    r"drop(?:ped)?\s+down|"
    r"enter(?:ed|s)?\s+in(?:to)?|"
    r"exit(?:ed|s)?\s+out|"
    r"refer(?:red)?\s+back|"
    r"pre(?:plan|record|order|book|heat|arrange|require)d"
    r")\b",
    re.IGNORECASE,
)

# ── syntactic binomials and trinomials (legal/formal doublets) ──
_SYNTACTIC_BINOMIALS = re.compile(
    r"\b(?:"
    # legal / formal doublets
    r"null\s+and\s+void|"
    r"cease\s+and\s+desist|"
    r"will\s+and\s+testament|"
    r"terms\s+and\s+conditions|"
    r"rights\s+and\s+obligations|"
    r"give\s+and\s+bequeath|"
    r"give\s+devise\s+and\s+bequeath|"
    r"goods\s+and\s+chattels|"
    r"fit\s+and\s+proper|"
    r"peace\s+and\s+quiet|"
    r"law\s+and\s+order|"
    r"each\s+and\s+every|"
    r"one\s+and\s+only|"
    r"first\s+and\s+foremost|"
    r"by\s+and\s+large|"
    r"pros\s+and\s+cons|"
    r"ups\s+and\s+downs|"
    r"ins\s+and\s+outs|"
    r"odds\s+and\s+ends|"
    r"bits\s+and\s+pieces|"
    r"part\s+and\s+parcel|"
    r"spick\s+and\s+span|"
    r"wear\s+and\s+tear|"
    r"tried\s+and\s+tested|"
    r"tried\s+and\s+true|"
    r"safe\s+and\s+sound|"
    r"neither\s+here\s+nor\s+there|"
    r"now\s+or\s+never|"
    r"sooner\s+or\s+later|"
    r"more\s+or\s+less|"
    r"body\s+and\s+soul|"
    r"flesh\s+and\s+blood|"
    r"life\s+and\s+death|"
    r"bread\s+and\s+butter|"
    r"rock\s+and\s+roll|"
    r"supply\s+and\s+demand|"
    r"crime\s+and\s+punishment|"
    r"carrot\s+and\s+stick|"
    r"dos\s+and\s+don'ts|"
    r"ifs\s+and\s+buts|"
    r"rant\s+and\s+rave|"
    r"pick\s+and\s+choose|"
    r"mix\s+and\s+match|"
    r"rise\s+and\s+fall|"
    r"ebb\s+and\s+flow|"
    r"push\s+and\s+pull|"
    r"give\s+and\s+take|"
    r"cause\s+and\s+effect|"
    r"time\s+and\s+tide|"
    r"thunder\s+and\s+lightning|"
    r"bread\s+and\s+circuses"
    r")\b",
    re.IGNORECASE,
)

# ── morphological redundancy (acronym + expanded word) ─────────
_MORPHOLOGICAL_REDUNDANCIES = re.compile(
    r"\b(?:"
    r"ATM\s+machine(?:s)?|"
    r"PIN\s+number(?:s)?|"
    r"HIV\s+virus|"
    r"LCD\s+display(?:s)?|"
    r"RAM\s+memory|"
    r"CPU\s+processor|"
    r"GPS\s+system(?:s)?|"
    r"ISBN\s+number(?:s)?|"
    r"VIN\s+number(?:s)?|"
    r"DC\s+comics|"
    r"UPC\s+code(?:s)?|"
    r"SAT\s+test|"
    r"GUI\s+interface|"
    r"ABM\s+missile(?:s)?|"
    r"IED\s+device(?:s)?|"
    r"EMS\s+system(?:s)?|"
    r"PDF\s+format|"
    r"HTML\s+language|"
    r"RSVP\s+please|"
    r"add(?:ed)?\s+bons?us(?:es)?|"
    r"chai\s+tea|"
    r"naan\s+bread|"
    r"shrimp\s+scampi|"
    r"tuna\s+fish|"
    r"fajita\s+taco"
    r")\b",
    re.IGNORECASE,
)

# ── verbal pleonasm (unnecessary complement) ───────────────────
_VERBAL_PLEONASMS = re.compile(
    r"\b(?:"
    r"see\s+with\s+(?:your|my|his|her|their|our|its)\s+eyes?|"
    r"saw\s+with\s+(?:your|my|his|her|their|our|its)\s+eyes?|"
    r"seen\s+with\s+(?:your|my|his|her|their|our|its)\s+eyes?|"
    r"hear\s+with\s+(?:your|my|his|her|their|our|its)\s+ears?|"
    r"heard\s+with\s+(?:your|my|his|her|their|our|its)\s+ears?|"
    r"think\s+in\s+(?:your|my|his|her|their|our|its)\s+(?:mind|head)|"
    r"thought\s+in\s+(?:your|my|his|her|their|our|its)\s+(?:mind|head)|"
    r"speak\s+with\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:voice|mouth)|"
    r"spoke\s+with\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:voice|mouth)|"
    r"walk\s+on\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:feet|legs)|"
    r"walked\s+on\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:feet|legs)|"
    r"eat\s+with\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:mouth|hands)|"
    r"ate\s+with\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:mouth|hands)|"
    r"breathe\s+with\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:lungs|nose)|"
    r"breathed\s+with\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:lungs|nose)|"
    r"look\s+(?:at|with)\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?eyes?|"
    r"looked\s+(?:at|with)\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?eyes?|"
    r"nod(?:ded|s)?\s+(?:your|my|his|her|their|our|its)\s+head|"
    r"shrug(?:ged|s)?\s+(?:your|my|his|her|their|our|its)\s+shoulders?|"
    r"blink(?:ed|s)?\s+(?:your|my|his|her|their|our|its)\s+eyes?|"
    r"open(?:ed|s)?\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?eyes?|"
    r"close(?:d|s)?\s+(?:your|my|his|her|their|our|its)\s+(?:own\s+)?eyes?|"
    r"stand\s+up\s+(?:on\s+)?(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:two\s+)?feet|"
    r"stood\s+up\s+(?:on\s+)?(?:your|my|his|her|their|our|its)\s+(?:own\s+)?(?:two\s+)?feet|"
    r"write\s+(?:down\s+)?(?:in\s+)?(?:your|my|his|her|their|our|its)\s+own\s+(?:hand(?:writing)?)?|"
    r"wrote\s+(?:down\s+)?(?:in\s+)?(?:your|my|his|her|their|our|its)\s+own\s+(?:hand(?:writing)?)?"
    r")\b",
    re.IGNORECASE,
)

# ── intensifier pleonasm (degree modifier + absolute adjective) ─
_INTENSIFIER_PLEONASMS = re.compile(
    r"\b(?:"
    # unique
    r"very\s+unique|"
    r"really\s+unique|"
    r"quite\s+unique|"
    r"truly\s+unique|"
    r"extremely\s+unique|"
    r"totally\s+unique|"
    r"absolutely\s+unique|"
    r"completely\s+unique|"
    r"rather\s+unique|"
    r"more\s+unique|"
    r"most\s+unique|"
    r"somewhat\s+unique|"
    # perfect
    r"very\s+perfect|"
    r"really\s+perfect|"
    r"absolutely\s+perfect|"
    r"completely\s+perfect|"
    r"totally\s+perfect|"
    r"quite\s+perfect|"
    # dead / alive
    r"very\s+dead|"
    r"completely\s+dead|"
    r"totally\s+dead|"
    r"absolutely\s+dead|"
    r"very\s+alive|"
    # pregnant
    r"very\s+pregnant|"
    r"slightly\s+pregnant|"
    r"really\s+pregnant|"
    r"quite\s+pregnant|"
    # empty / full
    r"completely\s+empty|"
    r"totally\s+empty|"
    r"absolutely\s+empty|"
    r"completely\s+full|"
    r"totally\s+full|"
    r"absolutely\s+full|"
    # essential / necessary / impossible
    r"absolutely\s+essential|"
    r"completely\s+essential|"
    r"absolutely\s+necessary|"
    r"completely\s+necessary|"
    r"absolutely\s+impossible|"
    r"completely\s+impossible|"
    r"totally\s+impossible|"
    # finished / complete
    r"completely\s+finished|"
    r"totally\s+finished|"
    r"completely\s+complete|"
    r"totally\s+complete|"
    r"fully\s+complete|"
    # fatal / eternal / infinite
    r"very\s+fatal|"
    r"very\s+eternal|"
    r"very\s+infinite|"
    r"absolutely\s+infinite|"
    # round / square / straight
    r"very\s+round|"
    r"perfectly\s+round|"
    r"completely\s+round|"
    r"very\s+square|"
    r"perfectly\s+square|"
    r"very\s+straight|"
    r"perfectly\s+straight|"
    # certain / sure
    r"absolutely\s+certain|"
    r"completely\s+certain|"
    r"absolutely\s+sure|"
    r"completely\s+sure"
    r")\b",
    re.IGNORECASE,
)

# ── combined pattern for unique form counting ───────────────────
_ALL_PLEONASM_FORMS = re.compile(
    r"\b(?:"
    # semantic (selected high-signal tokens)
    r"free\s+gift|past\s+history|end\s+result|final\s+outcome|"
    r"final\s+result|future\s+plan|added\s+bonus|unexpected\s+surprise|"
    r"necessary\s+requirement|close\s+proximity|actual\s+fact|"
    r"new\s+innovation|reason\s+why|revert\s+back|return\s+back|"
    r"repeat\s+again|brief\s+summary|brief\s+moment|"
    r"completely\s+destroy|still\s+remain|collaborate\s+together|"
    r"cooperate\s+together|merge\s+together|combine\s+together|"
    r"consensus\s+of\s+opinion|proceed\s+ahead|descend\s+down|"
    r"ascend\s+up|rise\s+up|enter\s+in|exit\s+out|refer\s+back|"
    # binomials (signal words)
    r"null\s+and\s+void|cease\s+and\s+desist|will\s+and\s+testament|"
    r"terms\s+and\s+conditions|each\s+and\s+every|one\s+and\s+only|"
    r"first\s+and\s+foremost|peace\s+and\s+quiet|law\s+and\s+order|"
    r"pros\s+and\s+cons|part\s+and\s+parcel|spick\s+and\s+span|"
    r"wear\s+and\s+tear|safe\s+and\s+sound|flesh\s+and\s+blood|"
    # morphological
    r"ATM\s+machine|PIN\s+number|HIV\s+virus|LCD\s+display|"
    r"RAM\s+memory|CPU\s+processor|GPS\s+system|chai\s+tea|"
    r"naan\s+bread|tuna\s+fish"
    r")\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class PleonasmDensityResult:
    """Results of pleonasm density analysis."""

    # Raw counts
    semantic_count: int = 0
    syntactic_count: int = 0
    morphological_count: int = 0
    verbal_count: int = 0
    intensifier_count: int = 0
    unique_pleonasm_forms: int = 0

    # Rates per 100 sentences
    semantic_rate: float = 0.0
    syntactic_rate: float = 0.0
    morphological_rate: float = 0.0
    verbal_rate: float = 0.0
    intensifier_rate: float = 0.0

    # Composite
    pleonasm_diversity_index: float = 0.0
    pleonasm_density_index: float = 0.0
    classification: str = "lean"

    # Metadata
    total_sentences: int = 0
    details: dict = field(default_factory=dict)


# ── main function ───────────────────────────────────────────────


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


def measure_pleonasm_density(text: str) -> PleonasmDensityResult:
    """Analyze pleonasm and redundant expression density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    PleonasmDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = PleonasmDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    semantic = _count_matches(_SEMANTIC_REDUNDANCIES, text)
    syntactic = _count_matches(_SYNTACTIC_BINOMIALS, text)
    morphological = _count_matches(_MORPHOLOGICAL_REDUNDANCIES, text)
    verbal = _count_matches(_VERBAL_PLEONASMS, text)
    intensifier = _count_matches(_INTENSIFIER_PLEONASMS, text)

    # Unique pleonasm forms
    all_forms = _ALL_PLEONASM_FORMS.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.semantic_count = semantic
    result.syntactic_count = syntactic
    result.morphological_count = morphological
    result.verbal_count = verbal
    result.intensifier_count = intensifier
    result.unique_pleonasm_forms = len(unique_forms)

    # Rates per 100 sentences
    result.semantic_rate = round(semantic * scale, 3)
    result.syntactic_rate = round(syntactic * scale, 3)
    result.morphological_rate = round(morphological * scale, 3)
    result.verbal_rate = round(verbal * scale, 3)
    result.intensifier_rate = round(intensifier * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~30)
    max_possible_forms = 30
    result.pleonasm_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_semantic = min(1.0, result.semantic_rate / 20.0)
    cap_syntactic = min(1.0, result.syntactic_rate / 15.0)
    cap_morphological = min(1.0, result.morphological_rate / 5.0)
    cap_verbal = min(1.0, result.verbal_rate / 5.0)
    cap_intensifier = min(1.0, result.intensifier_rate / 8.0)
    cap_diversity = result.pleonasm_diversity_index

    composite = (
        0.25 * cap_semantic
        + 0.20 * cap_syntactic
        + 0.10 * cap_morphological
        + 0.10 * cap_verbal
        + 0.15 * cap_intensifier
        + 0.20 * cap_diversity
    )
    result.pleonasm_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.pleonasm_density_index
    if idx < 0.05:
        result.classification = "lean"
    elif idx < 0.15:
        result.classification = "lightly_pleonastic"
    elif idx < 0.35:
        result.classification = "moderately_pleonastic"
    elif idx < 0.60:
        result.classification = "heavily_pleonastic"
    else:
        result.classification = "pleonasm_saturated"

    result.details = {
        "semantic_rate": result.semantic_rate,
        "syntactic_rate": result.syntactic_rate,
        "morphological_rate": result.morphological_rate,
        "verbal_rate": result.verbal_rate,
        "intensifier_rate": result.intensifier_rate,
        "pleonasm_diversity_index": result.pleonasm_diversity_index,
        "pleonasm_density_index": result.pleonasm_density_index,
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

    r = measure_pleonasm_density(text)
    print(f"pleonasm_density_index     : {r.pleonasm_density_index:.4f}")
    print(f"classification             : {r.classification}")
    print(f"semantic_rate              : {r.semantic_rate}")
    print(f"syntactic_rate             : {r.syntactic_rate}")
    print(f"morphological_rate         : {r.morphological_rate}")
    print(f"verbal_rate                : {r.verbal_rate}")
    print(f"intensifier_rate           : {r.intensifier_rate}")
    print(f"pleonasm_diversity_index   : {r.pleonasm_diversity_index}")
    print(f"total_sentences            : {r.total_sentences}")
