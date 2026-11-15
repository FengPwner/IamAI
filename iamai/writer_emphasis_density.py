#!/usr/bin/env python3
"""writer_emphasis_density — measure how much prose signals spotlight.

Every text has a foreground and a background.  Most sentences deliver
information at a roughly even volume; a few reach out and grab the
reader by the collar.  "This is **the** critical flaw."  "ABOVE ALL,
do not skip testing."  "It bears emphasizing that this assumption
is wrong."  These are not just louder claims — they are *pointing
gestures*, deliberate signals that say: look here, this matters more
than what surrounds it.

Emphasis is the writer's attention-direction mechanism.  Where
gradation calibrates degree ("somewhat important" vs "very important"),
emphasis *spotlights* — it marks certain elements as worthy of extra
attention regardless of their position on any scale.  A quiet
sentence can carry emphasis ("One thing.  Just one.") while a loud
sentence may not.

Emphasis operates through several distinct channels.  **Lexical
emphasis** uses words whose function is to spotlight: "crucial",
"critical", "essential", "key", "above all", "most importantly".
**Syntactic emphasis** rearranges grammar to foreground an element:
cleft sentences ("It was the architecture that failed, not the
code"), do-support ("I *do* believe this matters"), fronting ("This
we cannot accept").  **Typographic emphasis** marks text visually:
bold, italic, ALL CAPS, exclamation marks, underlines.  **Rhetorical
emphasis** uses discourse-level moves: direct imperatives ("Note
this carefully"), explicit markers ("it bears emphasizing"),
repetition for highlight ("never, never, never"), anaphora.

A text's emphasis density reveals its relationship to the reader's
attention.  Academic prose distributes emphasis sparingly and
structurally — "the central finding" gets spotlighted through
position rather than volume.  Marketing saturates in emphasis —
everything is "critical", "essential", "the key to", diluting the
signal.  Technical writing uses emphasis surgically — warnings,
prerequisites, gotchas.  Casual writing barely emphasizes at all,
relying on the reader's natural attention.  Legal writing avoids
explicit emphasis because every clause carries equal weight by
design.  Journalism front-loads emphasis — the lead paragraph is
the spotlight, everything else recedes.

This module measures **how frequently, how diversely, and through
what channels a text uses emphasis techniques** — lexical
spotlighting, syntactic foregrounding, typographic marking, and
rhetorical highlighting.

Orthogonality to other metrics
-------------------------------

- **conviction** tracks assertiveness and confidence — "this is
  correct" vs "this might be correct".  Conviction is about
  commitment to a claim; emphasis is about directing attention
  to a claim.  "I am certain this is routine" is convicted but
  not emphasized; "the *critical* detail" is emphasized regardless
  of how confidently it is stated.  Conviction is commitment;
  emphasis is spotlight.

- **gradation_density** tracks degree calibration — comparatives,
  superlatives, intensifiers.  "Very important" uses gradation
  to adjust intensity; "the **important** point" uses emphasis
  to direct attention.  Gradation answers "how much"; emphasis
  answers "look here".  A sentence can be both gradated and
  emphasized ("the most crucial factor") or neither ("the factor").
  Gradation scales; emphasis points.

- **concision** tracks economy of expression.  Emphasis techniques
  often add words ("it is important to note that" vs just stating
  the thing).  But concision measures whether words are wasted;
  emphasis measures whether attention is directed.  A concise
  sentence can carry strong emphasis ("**Stop.**") and a verbose
  sentence may carry none ("the process continues as before").
  Concision is about length; emphasis is about salience.

- **formality** tracks register — formal vs informal.  Typographic
  emphasis (**bold**, ALL CAPS) tends informal; lexical emphasis
  ("paramount", "pivotal") tends formal.  Formality measures the
  register; emphasis measures the spotlighting regardless of how
  it is achieved.  A formal text can be heavily emphasized
  ("it is imperative that") and an informal text can be flat.

- **repetition_index** tracks recurring words and phrases.
  Repetition can serve emphasis ("never, never, never give up")
  but emphasis can be achieved without repetition (a single
  "crucial" suffices).  Repetition measures recurrence; emphasis
  measures spotlighting.  A text with high repetition may be
  emphasizing or may simply be redundant.  Repetition recurs;
  emphasis highlights.

- **clarity** tracks how unambiguous and comprehensible text is.
  Emphasis can aid clarity by directing attention to key points,
  or harm it by over-marking everything as important (diluting
  the signal).  Clarity measures understanding; emphasis measures
  attention-direction.  A clear text may have minimal emphasis;
  an emphasized text may still be unclear.

Emphasis density asks: **how much of the prose is built on
attention-direction scaffolding, and what does the distribution
of lexical, syntactic, typographic, and rhetorical emphasis
reveal about the writer's relationship to the reader's focus?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── lexical emphasis ────────────────────────────────────────────
# Words whose primary function is to spotlight or flag importance
_LEXICAL_EMPHASIS = re.compile(
    r"\b(?:"
    # importance markers
    r"crucial|critical|essential|vital|paramount|"
    r"pivotal|fundamental|central|key\s+(?:point|factor|issue|element|insight|takeaway)|"
    r"significant|notable|noteworthy|remarkable|"
    r"striking|salient|conspicuous|prominent|"
    # urgency markers
    r"imperative|urgent|pressing|compelling|"
    r"indispensable|non-negotiable|mandatory|"
    # explicit spotlights
    r"above\s+all|most\s+importantly|"
    r"(?:first|foremost)\s+and\s+foremost|"
    r"in\s+particular|notably|especially|"
    r"importantly|critically|crucially|"
    r"essentially|fundamentally|"
    r"at\s+(?:the\s+)?heart\s+of|"
    r"the\s+(?:key|main|core|central|critical)\s+(?:point|issue|factor|idea|insight|message|takeaway)|"
    r"what\s+matters\s+most|"
    r"the\s+bottom\s+line|"
    r"at\s+the\s+end\s+of\s+the\s+day"
    r")\b",
    re.IGNORECASE,
)

# ── syntactic emphasis ──────────────────────────────────────────
# Grammatical constructions that foreground an element
_SYNTACTIC_EMPHASIS = re.compile(
    r"\b(?:"
    # it-cleft: "it is/was X that/who"
    r"it\s+(?:is|was|has\s+been|had\s+been)\s+"
    r"(?:precisely|exactly|specifically|only|not|this|that|the)\s+"
    r"\w+(?:\s+\w+)?\s+(?:that|who|which)\b|"
    # what-cleft: "what X is Y"
    r"what\s+(?:makes|we\s+need|this\s+means|is\s+(?:important|crucial|key|essential))|"
    # do-support emphasis: "I do believe/think/want"
    r"\bdo(?:es|n't|)\s+(?:believe|think|want|need|hope|expect|"
    r"insist|maintain|argue|claim|assert|emphasize|"
    r"understand|appreciate|recognize|acknowledge)\b|"
    # fronted negative: "not only... but also", "never have I"
    r"not\s+only\b.*\bbut\s+(?:also|even)|"
    r"never\s+(?:have|had|has|will|would|could|should|did|do|does)\b|"
    r"rarely\s+(?:have|had|has|will|would|could|should|did|do|does)\b|"
    r"seldom\s+(?:have|had|has|will|would|could|should|did|do|does)\b|"
    r"no\s+sooner\b|"
    # negative emphasis: "under no circumstances", "in no way"
    r"under\s+no\s+circumstances|"
    r"in\s+no\s+(?:way|sense|manner|respect)|"
    r"at\s+no\s+(?:point|time|stage)|"
    r"by\s+no\s+means|"
    # inverted conditional emphasis
    r"were\s+it\s+not\s+for|"
    r"had\s+it\s+not\s+been\s+for|"
    # intensifying syntactic moves
    r"the\s+(?:very|one\s+and\s+only|sole|single)\s+\w+\b|"
    r"(?:none|nothing|no\s+one)\s+other\s+than|"
    r"if\s+(?:there\s+is|there\s+was|anything|one\s+thing)"
    r")\b",
    re.IGNORECASE,
)

# ── typographic emphasis ────────────────────────────────────────
# Visual/textual markers that highlight text
# Note: markdown patterns work on raw text; for plain text these are absent
_TYPOGRAPHIC_EMPHASIS = re.compile(
    r"(?:"
    # markdown bold: **text** or __text__
    r"\*\*[^*]+\*\*|"
    r"__[^_]+__|"
    # markdown italic: *text* or _text_ (but not inside bold)
    r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)|"
    r"(?<!_)_(?!_)[^_]+_(?!_)|"
    # ALL CAPS words (3+ letters)
    r"\b[A-Z]{3,}\b|"
    # exclamation marks
    r"!+"
    r")"
)

# Common acronyms and abbreviations that are NOT emphasis
_ACRONYM_EXCLUSIONS = frozenset({
    "INC", "LTD", "LLC", "JR", "SR", "MD", "PHD", "USA", "UK", "EU",
    "UN", "CEO", "CTO", "CFO", "COO", "CIO", "API", "URL", "HTML",
    "CSS", "JSON", "XML", "SQL", "SSH", "HTTP", "HTTPS", "FTP", "DNS",
    "RAM", "ROM", "CPU", "GPU", "OS", "AI", "ML", "NLP", "TTS", "OCR",
    "AWS", "GCP", "IBM", "HP", "AMD", "ARM", "IBM", "UTC", "GMT",
    "EST", "PST", "CST", "IST", "RGB", "CMYK", "PNG", "JPG", "JPEG",
    "SVG", "GIF", "PDF", "CSV", "TSV", "YAML", "TOML", "INI",
    "TCP", "UDP", "TLS", "SSL", "JWT", "OAUTH", "REST", "GraphQL",
    "SDK", "CLI", "GUI", "IDE", "VCS", "CI", "CD", "QA", "UX", "UI",
    "MIT", "BSD", "GPL", "LGPL", "RFC", "ISO", "IEEE", "ANSI",
    "ASCII", "UTF", "GNU", "POSIX", "UNIX", "LINUX",
    "README", "TODO", "FIXME", "XXX", "NOTE", "WARNING", "IMPORTANT",
    "THE", "AND", "FOR", "NOT", "ALL", "BUT", "HAS", "HAD", "HER",
    "HIS", "ITS", "OUR", "OUT", "SHE", "WAS", "WHO", "HIM", "HOW",
    "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "DAY", "DID", "SAY",
})

# ── rhetorical emphasis ─────────────────────────────────────────
# Discourse-level moves that direct attention
_RHETORICAL_EMPHASIS = re.compile(
    r"\b(?:"
    # explicit attention markers
    r"(?:note|notice|observe)\s+that\b|"
    r"(?:note|notice)\s+(?:this|carefully|well)\b|"
    r"pay\s+(?:close\s+)?attention\s+(?:to|here)\b|"
    r"bear\s+in\s+mind\b|"
    r"keep\s+in\s+mind\b|"
    r"it\s+bears\s+(?:emphasizing|repeating|stressing|noting)\b|"
    r"(?:worth|deserves?)\s+(?:noting|mentioning|emphasizing|highlighting|stressing)\b|"
    r"(?:let\s+me|allow\s+me\s+to)\s+(?:emphasize|stress|highlight|underline)\b|"
    # direct imperatives for emphasis
    r"remember\s+that\b|"
    r"do\s+not\s+forget\b|"
    r"make\s+no\s+mistake\b|"
    r"let\s+(?:me\s+be|this\s+be)\s+clear\b|"
    r"(?:mark|heed)\s+my\s+words\b|"
    # repetition patterns (triple)
    r"(\w+)\s+\1\s+\1|"
    # explicit contrast for emphasis
    r"the\s+difference\s+is\s+(?:stark|enormous|critical|crucial|vast)\b|"
    r"this\s+is\s+(?:not|no)\s+(?:small|trivial|minor|ordinary|simple)\s+(?:matter|thing|issue|point|task)\b|"
    # spotlight phrases
    r"the\s+point\s+is\b|"
    r"here'?s?\s+the\s+(?:thing|point|key|catch|issue)\b|"
    r"(?:what|the\s+thing)\s+to\s+remember\b|"
    r"if\s+you\s+take\s+(?:away|from)\s+(?:one|anything)\b"
    r")\b",
    re.IGNORECASE,
)

# ── combined unique emphasis forms ──────────────────────────────
_ALL_EMPHASIS_LEXICAL = re.compile(
    r"\b(?:"
    r"crucial|critical|essential|vital|paramount|"
    r"pivotal|fundamental|central|significant|"
    r"notable|noteworthy|remarkable|striking|salient|"
    r"imperative|urgent|pressing|compelling|indispensable|"
    r"importantly|critically|crucially|essentially|"
    r"notably|especially|particularly"
    r")\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class EmphasisDensityResult:
    """Results of emphasis density analysis."""

    # Raw counts
    lexical_count: int = 0
    syntactic_count: int = 0
    typographic_count: int = 0
    rhetorical_count: int = 0
    unique_emphasis_forms: int = 0

    # Rates per 100 sentences
    lexical_rate: float = 0.0
    syntactic_rate: float = 0.0
    typographic_rate: float = 0.0
    rhetorical_rate: float = 0.0

    # Composite
    emphasis_diversity_index: float = 0.0
    emphasis_density_index: float = 0.0
    classification: str = "unemphasized"

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


# ── ALL CAPS emphasis (excluding common acronyms) ──────────────
_ALL_CAPS_WORD = re.compile(r"\b([A-Z]{3,})\b")


def _count_allcaps_emphasis(text: str) -> int:
    """Count ALL CAPS words that are not common acronyms."""
    count = 0
    for match in _ALL_CAPS_WORD.finditer(text):
        word = match.group(1).upper()
        if word not in _ACRONYM_EXCLUSIONS:
            count += 1
    return count


def _count_typographic_emphasis(text: str) -> int:
    """Count typographic emphasis, filtering acronym false positives."""
    # Count markdown and exclamation marks via regex
    # Then add filtered ALL CAPS count
    md_bold = len(re.findall(r"\*\*[^*]+\*\*", text))
    md_underscore = len(re.findall(r"__[^_]+__", text))
    md_italic_star = len(re.findall(r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)", text))
    md_italic_under = len(re.findall(r"(?<!_)_(?!_)[^_]+_(?!_)", text))
    exclamations = len(re.findall(r"!+", text))
    allcaps = _count_allcaps_emphasis(text)
    return md_bold + md_underscore + md_italic_star + md_italic_under + exclamations + allcaps


def measure_emphasis_density(text: str) -> EmphasisDensityResult:
    """Analyze emphasis technique density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    EmphasisDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = EmphasisDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    lexical = _count_matches(_LEXICAL_EMPHASIS, text)
    syntactic = _count_matches(_SYNTACTIC_EMPHASIS, text)
    typographic = _count_typographic_emphasis(text)
    rhetorical = _count_matches(_RHETORICAL_EMPHASIS, text)

    # Unique emphasis forms (lexical only for diversity)
    all_forms = _ALL_EMPHASIS_LEXICAL.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.lexical_count = lexical
    result.syntactic_count = syntactic
    result.typographic_count = typographic
    result.rhetorical_count = rhetorical
    result.unique_emphasis_forms = len(unique_forms)

    # Rates per 100 sentences
    result.lexical_rate = round(lexical * scale, 3)
    result.syntactic_rate = round(syntactic * scale, 3)
    result.typographic_rate = round(typographic * scale, 3)
    result.rhetorical_rate = round(rhetorical * scale, 3)

    # Diversity: ratio of unique lexical forms to maximum possible (~25)
    max_possible_forms = 25
    result.emphasis_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_lexical = min(1.0, result.lexical_rate / 20.0)
    cap_syntactic = min(1.0, result.syntactic_rate / 8.0)
    cap_typographic = min(1.0, result.typographic_rate / 15.0)
    cap_rhetorical = min(1.0, result.rhetorical_rate / 10.0)
    cap_diversity = result.emphasis_diversity_index

    composite = (
        0.30 * cap_lexical
        + 0.15 * cap_syntactic
        + 0.15 * cap_typographic
        + 0.20 * cap_rhetorical
        + 0.20 * cap_diversity
    )
    result.emphasis_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.emphasis_density_index
    if idx < 0.05:
        result.classification = "unemphasized"
    elif idx < 0.15:
        result.classification = "lightly_emphasized"
    elif idx < 0.35:
        result.classification = "moderately_emphasized"
    elif idx < 0.60:
        result.classification = "heavily_emphasized"
    else:
        result.classification = "emphasis_saturated"

    result.details = {
        "lexical_rate": result.lexical_rate,
        "syntactic_rate": result.syntactic_rate,
        "typographic_rate": result.typographic_rate,
        "rhetorical_rate": result.rhetorical_rate,
        "emphasis_diversity_index": result.emphasis_diversity_index,
        "emphasis_density_index": result.emphasis_density_index,
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

    r = measure_emphasis_density(text)
    print(f"emphasis_density_index     : {r.emphasis_density_index:.4f}")
    print(f"classification             : {r.classification}")
    print(f"lexical_rate               : {r.lexical_rate}")
    print(f"syntactic_rate             : {r.syntactic_rate}")
    print(f"typographic_rate           : {r.typographic_rate}")
    print(f"rhetorical_rate            : {r.rhetorical_rate}")
    print(f"emphasis_diversity_index   : {r.emphasis_diversity_index}")
    print(f"total_sentences            : {r.total_sentences}")
