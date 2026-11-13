#!/usr/bin/env python3
"""writer_enumeration_density — measure how frequently a text enumerates.

Enumeration is the writer's instinct to organize — breaking a
complex idea into numbered points, bulleted items, sequential
steps, or parallel phrases.  Every "first… second… third…",
every "one… another… still another…", every dash-separated
list inside a sentence is an act of enumeration.

Enumeration density is not a quality metric.  Technical writing
lives in enumeration — specifications, procedures, changelogs.
Instructional prose depends on it — "step 1, step 2, step 3."
But a text that cannot describe anything without first slicing
it into a list may be avoiding the harder work of narrative
flow.  Meanwhile, essayistic and literary prose often resists
enumeration, preferring continuous paragraphs where ideas
blend rather than stack.

This module measures **how frequently and how structurally a
text enumerates** — explicit numbering, ordinal markers,
bullet-style formatting, sequential phrases, inline lists,
and the ratio of enumerated to non-enumerated paragraphs.

Orthogonality to other metrics
-------------------------------

- **sentence_architecture** tracks sentence-level structure —
  length, clause count, embedding depth.  Enumeration can
  appear within a single sentence (inline list) or span many
  sentences (numbered paragraphs).  Sentence architecture
  measures internal complexity; enumeration density measures
  the impulse to itemize.

- **vocabulary_richness** tracks lexical diversity.  A list
  can use highly varied words or repeat the same pattern.
  Vocabulary measures word choice; enumeration measures
  structural organization.

- **parallelism_density** tracks syntactic repetition —
  repeated grammatical structures for rhetorical effect.
  Enumeration often uses parallelism ("we shall fight on
  the beaches, we shall fight on the landing grounds"),
  but parallelism can appear without enumeration (anaphora
  in a single flowing paragraph).  Parallelism measures
  syntactic echo; enumeration measures itemization.

- **concision** tracks brevity.  Enumerated text can be
  terse (bullet points) or verbose (each item a full
  paragraph).  Concision measures economy; enumeration
  measures structural organization.

- **prose_rhythm** tracks cadence and flow.  Enumeration
  creates a staccato rhythm, but rhythm and enumeration
  are not the same — a flowing paragraph can have strong
  rhythm without any enumeration.  Prose rhythm measures
  cadence; enumeration density measures itemization.

Enumeration density asks: **how often does the writer break
ideas into discrete, ordered, or listed units rather than
continuous prose, and how structurally dominant is this
organizing impulse?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ── regex patterns ──────────────────────────────────────────────

# "1.", "2)", "(a)", "i.", "III.", "Step 1:"
_EXPLICIT_NUMBERING = re.compile(
    r"""
    (?:^|\n)\s*                     # start of line (possibly indented)
    (?:
        \d{1,3}\s*[.)]\s            # 1. 2) etc.
      | \([a-zA-Z]\)\s              # (a) (b) etc.
      | [a-zA-Z]\s*[.)]\s           # a. b) etc.
      | (?:i{1,3}|iv|vi{0,3}|ix|xi{0,3})\s*\.  # roman numerals
      | (?:step|phase|stage)\s*\d+  # step 1, phase 2
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# "first, … second, … third, …" / "firstly, …"
_ORDINAL_MARKERS = re.compile(
    r"""\b
    (?:
        first(?:ly)?
      | second(?:ly)?
      | third(?:ly)?
      | fourth(?:ly)?
      | fifth(?:ly)?
      | sixth(?:ly)?
      | seventh(?:ly)?
      | eighth(?:ly)?
      | ninth(?:ly)?
      | tenth(?:ly)?
      | next
      | then(?!\s+the)          # "then" but not "then the"
      | finally
      | lastly
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# "one … another … yet another … still another"
_SEQUENTIAL_PHRASES = re.compile(
    r"""\b
    (?:
        one\s+\w+[\s,]+\w+\s+another
      | (?:yet|still)\s+another
      | on\s+the\s+one\s+hand
      | on\s+the\s+other\s+hand
      | in\s+the\s+first\s+place
      | for\s+one\s+thing
      | for\s+another\s*(?:thing)?
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# bullet-style lines: starts with -, *, •, –, —
_BULLET_LINES = re.compile(
    r"(?:^|\n)\s*[-*•–—]\s+",
)

# inline lists: "A, B, and C" / "A, B, C, and D"
# Requires at least 2 commas (3+ items) to avoid matching
# compound predicates like "sat down, looked up, and smiled"
_INLINE_LIST = re.compile(
    r"\b[\w]+(?:\s+[\w]+)*"                   # first item (1+ words)
    r"(?:\s*,\s*[\w]+(?:\s+[\w]+)*){2,}"      # , item (at least 2 more)
    r"\s*,?\s*(?:and|or)\s+[\w]+(?:\s+[\w]+)*" # , and last_item
    ,
    re.IGNORECASE,
)

# colon-introduced lists: "the following: A, B, C"
_COLON_LIST = re.compile(
    r":\s*[\w]+(?:\s+[\w]+)*"                          # first item
    r"(?:\s*,\s*[\w]+(?:\s+[\w]+)*)*"                  # , item (0+)
    r"\s*(?:,?\s*(?:and|or)\s+[\w]+(?:\s+[\w]+)*)?"    # optional , and last
    r"\s*[.!?]",
    re.IGNORECASE,
)


@dataclass
class EnumerationDensityResult:
    """Full output of the enumeration density analysis."""

    explicit_numbering_rate: float = 0.0
    ordinal_marker_rate: float = 0.0
    sequential_phrase_rate: float = 0.0
    bullet_line_rate: float = 0.0
    inline_list_rate: float = 0.0
    colon_list_rate: float = 0.0
    enumerated_paragraph_ratio: float = 0.0

    enumeration_density_index: float = 0.0
    classification: str = "continuous"

    explicit_numbering_count: int = 0
    ordinal_marker_count: int = 0
    sequential_phrase_count: int = 0
    bullet_line_count: int = 0
    inline_list_count: int = 0
    colon_list_count: int = 0
    enumerated_paragraphs: int = 0
    total_paragraphs: int = 0
    total_sentences: int = 0

    details: dict = field(default_factory=dict)


def _count_sentences(text: str) -> int:
    """Count sentences using simple punctuation heuristic."""
    sents = re.split(r"[.!?]+", text)
    return max(1, len([s for s in sents if s.strip()]))


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on blank lines."""
    paras = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paras if p.strip()]


def _paragraph_has_enumeration(para: str) -> bool:
    """Check if a paragraph contains any enumeration signal."""
    return bool(
        _EXPLICIT_NUMBERING.search(para)
        or _ORDINAL_MARKERS.search(para)
        or _SEQUENTIAL_PHRASES.search(para)
        or _BULLET_LINES.search(para)
        or _COLON_LIST.search(para)
    )


def measure_enumeration_density(text: str) -> EnumerationDensityResult:
    """Analyze a text for enumeration density.

    Parameters
    ----------
    text : str
        The prose to analyze.

    Returns
    -------
    EnumerationDensityResult
        Rates, counts, composite index, and classification.
    """
    if not text or not text.strip():
        return EnumerationDensityResult()

    result = EnumerationDensityResult()

    total_sentences = _count_sentences(text)
    paragraphs = _split_paragraphs(text)
    total_paragraphs = max(1, len(paragraphs))
    total_lines = max(1, len([l for l in text.split("\n") if l.strip()]))

    # Count raw occurrences
    explicit_numbering = len(_EXPLICIT_NUMBERING.findall(text))
    ordinal_markers = len(_ORDINAL_MARKERS.findall(text))
    sequential_phrases = len(_SEQUENTIAL_PHRASES.findall(text))
    bullet_lines = len(_BULLET_LINES.findall(text))
    inline_lists = len(_INLINE_LIST.findall(text))
    colon_lists = len(_COLON_LIST.findall(text))

    # Store raw counts
    result.explicit_numbering_count = explicit_numbering
    result.ordinal_marker_count = ordinal_markers
    result.sequential_phrase_count = sequential_phrases
    result.bullet_line_count = bullet_lines
    result.inline_list_count = inline_lists
    result.colon_list_count = colon_lists
    result.total_paragraphs = total_paragraphs
    result.total_sentences = total_sentences

    # Compute per-100-sentences rates
    scale = 100.0 / max(1, total_sentences)
    result.explicit_numbering_rate = round(explicit_numbering * scale, 3)
    result.ordinal_marker_rate = round(ordinal_markers * scale, 3)
    result.sequential_phrase_rate = round(sequential_phrases * scale, 3)
    result.bullet_line_rate = round(bullet_lines * (100.0 / total_lines), 3)
    result.inline_list_rate = round(inline_lists * scale, 3)
    result.colon_list_rate = round(colon_lists * scale, 3)

    # Enumerated paragraph ratio
    enum_paras = sum(1 for p in paragraphs if _paragraph_has_enumeration(p))
    result.enumerated_paragraphs = enum_paras
    result.enumerated_paragraph_ratio = round(
        enum_paras / total_paragraphs, 3
    )

    # Composite index (0.0 – 1.0)
    # Normalize each rate to roughly 0–1 via soft caps
    cap_explicit = min(1.0, explicit_numbering * scale / 10.0)
    cap_ordinal = min(1.0, ordinal_markers * scale / 8.0)
    cap_sequential = min(1.0, sequential_phrases * scale / 5.0)
    cap_bullet = min(1.0, bullet_lines / max(1, total_lines) * 5.0)
    cap_inline = min(1.0, inline_lists * scale / 8.0)
    cap_colon = min(1.0, colon_lists * scale / 5.0)
    cap_para = result.enumerated_paragraph_ratio

    composite = (
        0.20 * cap_explicit
        + 0.15 * cap_ordinal
        + 0.10 * cap_sequential
        + 0.15 * cap_bullet
        + 0.10 * cap_inline
        + 0.10 * cap_colon
        + 0.20 * cap_para
    )
    result.enumeration_density_index = round(min(1.0, composite), 4)

    # Classify
    idx = result.enumeration_density_index
    if idx < 0.05:
        result.classification = "continuous"
    elif idx < 0.15:
        result.classification = "lightly_enumerated"
    elif idx < 0.35:
        result.classification = "moderately_enumerated"
    elif idx < 0.60:
        result.classification = "heavily_enumerated"
    else:
        result.classification = "list_saturated"

    result.details = {
        "explicit_numbering_rate": result.explicit_numbering_rate,
        "ordinal_marker_rate": result.ordinal_marker_rate,
        "sequential_phrase_rate": result.sequential_phrase_rate,
        "bullet_line_rate": result.bullet_line_rate,
        "inline_list_rate": result.inline_list_rate,
        "colon_list_rate": result.colon_list_rate,
        "enumerated_paragraph_ratio": result.enumerated_paragraph_ratio,
        "enumeration_density_index": result.enumeration_density_index,
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

    r = measure_enumeration_density(text)
    print(f"enumeration_density_index : {r.enumeration_density_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"explicit_numbering_rate   : {r.explicit_numbering_rate}")
    print(f"ordinal_marker_rate       : {r.ordinal_marker_rate}")
    print(f"sequential_phrase_rate    : {r.sequential_phrase_rate}")
    print(f"bullet_line_rate          : {r.bullet_line_rate}")
    print(f"inline_list_rate          : {r.inline_list_rate}")
    print(f"colon_list_rate           : {r.colon_list_rate}")
    print(f"enumerated_paragraph_ratio: {r.enumerated_paragraph_ratio}")
    print(f"total_paragraphs          : {r.total_paragraphs}")
    print(f"total_sentences           : {r.total_sentences}")
