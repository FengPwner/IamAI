#!/usr/bin/env python3
"""writer_exemplification_density — measure how much prose relies on examples.

Exemplification is the rhetorical move from claim to evidence-via-instance.
When a writer says "many languages lack a word for 'blue'" and then adds
"for example, ancient Greek and classical Chinese", the second clause is
exemplification: it anchors abstraction in a named particular.

A text with high exemplification density reads like a lecture from someone
who has done the fieldwork — every assertion comes with a specimen pinned
to the board.  A text with low exemplification density reads like a
manifesto or a theorem: claims stand on their own authority, unsupported
by illustrative cases.

Neither extreme is inherently better.  Technical documentation thrives
on examples ("for instance, passing null raises ValueError"); philosophical
prose often avoids them ("consider the nature of justice").  But an
unexpected absence of examples in a text that makes empirical claims is
a canary: the writer may be generalizing from thin evidence.

Exemplification manifests through several measurable channels.
**Explicit markers** are stock phrases that introduce examples: "for
example", "for instance", "such as", "e.g.", "to illustrate", "consider",
"a case in point", "namely", "to wit".  **Hypothetical instances**
manufacture illustrative scenarios: "imagine", "suppose", "picture",
"say you have", "envision".  **Named instances** drop proper nouns,
specific dates, or precise quantities as evidence: "Shakespeare",
"the 2008 financial crisis", "42%".  **Analogical exemplification**
borrows from parallel domains: "similarly", "likewise", "just as",
"in the same way".  **Contrastive exemplification** defines by
counter-example: "unlike", "in contrast to", "as opposed to",
"on the other hand".

This module measures exemplification density as a composite index
(0.0 – 1.0) across five independent channels, orthogonal to specificity
(which measures precision of reference), concreteness (which measures
sensory grounding), verbosity (which measures padding), formality
(which measures register), and hedging (which measures commitment
softening).

written by Qwen during manual caretaker visit 645, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Word tokenizer
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── explicit exemplification markers ────────────────────────────
# Stock phrases that directly introduce examples or illustrations.

_EXPLICIT_MARKERS = [
    re.compile(r"\bfor example\b", re.IGNORECASE),
    re.compile(r"\bfor instance\b", re.IGNORECASE),
    re.compile(r"\bsuch as\b", re.IGNORECASE),
    re.compile(r"\be\.g\.?", re.IGNORECASE),
    re.compile(r"\bnamely\b", re.IGNORECASE),
    re.compile(r"\bto wit\b", re.IGNORECASE),
    re.compile(r"\bto illustrate\b", re.IGNORECASE),
    re.compile(r"\bas an example\b", re.IGNORECASE),
    re.compile(r"\bas a case in point\b", re.IGNORECASE),
    re.compile(r"\ba case in point\b", re.IGNORECASE),
    re.compile(r"\bconsider the case\b", re.IGNORECASE),
    re.compile(r"\bconsider the following\b", re.IGNORECASE),
    re.compile(r"\btake for example\b", re.IGNORECASE),
    re.compile(r"\btake for instance\b", re.IGNORECASE),
    re.compile(r"\btake the case of\b", re.IGNORECASE),
    re.compile(r"\bby way of example\b", re.IGNORECASE),
    re.compile(r"\bby way of illustration\b", re.IGNORECASE),
    re.compile(r"\binclude[sd]?\b", re.IGNORECASE),
    re.compile(r"\bincluding\b", re.IGNORECASE),
]


# ── hypothetical instances ──────────────────────────────────────
# Phrases that manufacture illustrative scenarios rather than cite
# real ones.

_HYPOTHETICAL_MARKERS = [
    re.compile(r"\bimagine\b", re.IGNORECASE),
    re.compile(r"\bsuppose\b", re.IGNORECASE),
    re.compile(r"\bpicture\b", re.IGNORECASE),
    re.compile(r"\benvision\b", re.IGNORECASE),
    re.compile(r"\benvisage\b", re.IGNORECASE),
    re.compile(r"\bsay you have\b", re.IGNORECASE),
    re.compile(r"\bsay you are\b", re.IGNORECASE),
    re.compile(r"\bsay we have\b", re.IGNORECASE),
    re.compile(r"\blet'?s say\b", re.IGNORECASE),
    re.compile(r"\blet us suppose\b", re.IGNORECASE),
    re.compile(r"\blet us assume\b", re.IGNORECASE),
    re.compile(r"\bfor the sake of argument\b", re.IGNORECASE),
    re.compile(r"\bhypothetically\b", re.IGNORECASE),
]


# ── named instances ─────────────────────────────────────────────
# Proper nouns, specific years, and percentage values used as
# illustrative evidence.  Detected via capitalization pattern,
# four-digit years, and percentage notation.

# Capitalized multi-word names (two+ consecutive capitalized tokens)
_NAMED_INSTANCE_PATTERN = re.compile(
    r"\b[A-Z][a-z]*(?:\s+[A-Z][a-z]*)+"
)

# Specific years (1000–2099)
_YEAR_PATTERN = re.compile(r"\b(?:1\d{3}|20\d{2})\b")

# Percentages
_PERCENT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%")

# Specific currency amounts ($X, €X, £X)
_CURRENCY_PATTERN = re.compile(r"[$€£]\d+(?:,\d{3})*(?:\.\d+)?")


# ── analogical exemplification ──────────────────────────────────
# Phrases that borrow from parallel domains to illustrate a point.

_ANALOGICAL_MARKERS = [
    re.compile(r"\bsimilarly\b", re.IGNORECASE),
    re.compile(r"\blikewise\b", re.IGNORECASE),
    re.compile(r"\bjust as\b", re.IGNORECASE),
    re.compile(r"\bin the same way\b", re.IGNORECASE),
    re.compile(r"\bby the same token\b", re.IGNORECASE),
    re.compile(r"\bby analogy\b", re.IGNORECASE),
    re.compile(r"\banalogous to\b", re.IGNORECASE),
    re.compile(r"\bparallel to\b", re.IGNORECASE),
    re.compile(r"\bcomparable to\b", re.IGNORECASE),
    re.compile(r"\bmuch like\b", re.IGNORECASE),
    re.compile(r"\bthink of it as\b", re.IGNORECASE),
    re.compile(r"\bit'?s like\b", re.IGNORECASE),
]


# ── contrastive exemplification ─────────────────────────────────
# Phrases that define by counter-example or opposition.

_CONTRASTIVE_MARKERS = [
    re.compile(r"\bunlike\b", re.IGNORECASE),
    re.compile(r"\bin contrast to\b", re.IGNORECASE),
    re.compile(r"\bas opposed to\b", re.IGNORECASE),
    re.compile(r"\bon the other hand\b", re.IGNORECASE),
    re.compile(r"\bby contrast\b", re.IGNORECASE),
    re.compile(r"\bconversely\b", re.IGNORECASE),
    re.compile(r"\bwhereas\b", re.IGNORECASE),
    re.compile(r"\bwhile on the other hand\b", re.IGNORECASE),
    re.compile(r"\brather than\b", re.IGNORECASE),
    re.compile(r"\binstead of\b", re.IGNORECASE),
]


# ── result dataclass ────────────────────────────────────────────


@dataclass
class ExemplificationResult:
    """Results of exemplification density analysis."""

    # Raw counts
    explicit_count: int = 0
    hypothetical_count: int = 0
    named_instance_count: int = 0
    analogical_count: int = 0
    contrastive_count: int = 0

    # Rates per 100 sentences
    explicit_rate: float = 0.0
    hypothetical_rate: float = 0.0
    named_instance_rate: float = 0.0
    analogical_rate: float = 0.0
    contrastive_rate: float = 0.0

    # Diversity (unique markers used per channel)
    explicit_diversity: float = 0.0
    hypothetical_diversity: float = 0.0
    analogical_diversity: float = 0.0
    contrastive_diversity: float = 0.0

    # Composite
    exemplification_index: float = 0.0
    classification: str = "barren"

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


def _count_pattern_matches(
    text: str, patterns: List[re.Pattern]
) -> tuple:
    """Return (total_count, unique_pattern_count)."""
    total = 0
    unique = 0
    for p in patterns:
        matches = p.findall(text)
        if matches:
            total += len(matches)
            unique += 1
    return total, unique


def _count_named_instances(text: str) -> int:
    """Count named instances (proper nouns, years, %, currency)."""
    names = _NAMED_INSTANCE_PATTERN.findall(text)
    years = _YEAR_PATTERN.findall(text)
    percents = _PERCENT_PATTERN.findall(text)
    currencies = _CURRENCY_PATTERN.findall(text)
    return len(names) + len(years) + len(percents) + len(currencies)


# ── main measurement function ───────────────────────────────────


def measure_exemplification(text: str) -> ExemplificationResult:
    """Measure exemplification density of a text.

    Returns an ExemplificationResult with exemplification_index (0.0–1.0)
    and classification.
    """
    result = ExemplificationResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "barren"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    scale = 100.0 / max(sentences, 1)

    # ── count explicit markers ───────────────────────────────
    exp_total, exp_unique = _count_pattern_matches(
        text, _EXPLICIT_MARKERS
    )
    result.explicit_count = exp_total
    result.explicit_rate = round(exp_total * scale, 3)
    result.explicit_diversity = round(
        exp_unique / max(len(_EXPLICIT_MARKERS), 1), 3
    )

    # ── count hypothetical markers ───────────────────────────
    hyp_total, hyp_unique = _count_pattern_matches(
        text, _HYPOTHETICAL_MARKERS
    )
    result.hypothetical_count = hyp_total
    result.hypothetical_rate = round(hyp_total * scale, 3)
    result.hypothetical_diversity = round(
        hyp_unique / max(len(_HYPOTHETICAL_MARKERS), 1), 3
    )

    # ── count named instances ────────────────────────────────
    named = _count_named_instances(text)
    result.named_instance_count = named
    result.named_instance_rate = round(named * scale, 3)

    # ── count analogical markers ─────────────────────────────
    ana_total, ana_unique = _count_pattern_matches(
        text, _ANALOGICAL_MARKERS
    )
    result.analogical_count = ana_total
    result.analogical_rate = round(ana_total * scale, 3)
    result.analogical_diversity = round(
        ana_unique / max(len(_ANALOGICAL_MARKERS), 1), 3
    )

    # ── count contrastive markers ────────────────────────────
    con_total, con_unique = _count_pattern_matches(
        text, _CONTRASTIVE_MARKERS
    )
    result.contrastive_count = con_total
    result.contrastive_rate = round(con_total * scale, 3)
    result.contrastive_diversity = round(
        con_unique / max(len(_CONTRASTIVE_MARKERS), 1), 3
    )

    # ── composite exemplification index (0.0 – 1.0) ─────────
    # Normalize each channel to ~0–1 via typical maxima
    cap_exp = min(1.0, result.explicit_rate / 25.0)
    cap_hyp = min(1.0, result.hypothetical_rate / 10.0)
    cap_named = min(1.0, result.named_instance_rate / 40.0)
    cap_ana = min(1.0, result.analogical_rate / 12.0)
    cap_con = min(1.0, result.contrastive_rate / 15.0)

    composite = (
        0.30 * cap_exp
        + 0.15 * cap_hyp
        + 0.25 * cap_named
        + 0.15 * cap_ana
        + 0.15 * cap_con
    )
    result.exemplification_index = round(min(1.0, composite), 4)

    # ── classification ───────────────────────────────────────
    idx = result.exemplification_index
    if idx < 0.10:
        result.classification = "barren"
    elif idx < 0.25:
        result.classification = "sparse"
    elif idx < 0.45:
        result.classification = "moderate"
    elif idx < 0.70:
        result.classification = "rich"
    else:
        result.classification = "saturated"

    result.details = {
        "explicit_rate": result.explicit_rate,
        "hypothetical_rate": result.hypothetical_rate,
        "named_instance_rate": result.named_instance_rate,
        "analogical_rate": result.analogical_rate,
        "contrastive_rate": result.contrastive_rate,
        "exemplification_index": result.exemplification_index,
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

    r = measure_exemplification(text)
    print(f"exemplification_index     : {r.exemplification_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"explicit_rate             : {r.explicit_rate}")
    print(f"hypothetical_rate         : {r.hypothetical_rate}")
    print(f"named_instance_rate       : {r.named_instance_rate}")
    print(f"analogical_rate           : {r.analogical_rate}")
    print(f"contrastive_rate          : {r.contrastive_rate}")
    print(f"total_sentences           : {r.total_sentences}")
    print(f"total_words               : {r.total_words}")
