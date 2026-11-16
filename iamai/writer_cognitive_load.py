#!/usr/bin/env python3
"""writer_cognitive_load — measure working-memory demands of prose.

Cognitive load in writing is the burden placed on a reader's working
memory as they process text.  Some prose is easy to parse on first
reading; other prose forces the reader to hold multiple unresolved
threads in mind, re-read sentences, or mentally reconstruct the
syntactic tree.  This module quantifies that burden across five
orthogonal channels.

**Embedding depth** captures how deeply clauses are nested inside
one another.  Each level of embedding (relative clause, parenthetical,
subordinate clause, appositive) adds one item to the reader's mental
stack.  Garden-path sentences and multiply-embedded relatives are the
extreme case — "The rat the cat the dog chased caught ate the malt."
In technical writing, deep embedding often signals that a sentence
is trying to express too many relationships at once.

**Referential distance** measures how far a pronoun or anaphor sits
from its antecedent.  When "it", "they", "this", or "that" appears,
the reader must search backward through the text to find what it
refers to.  The farther back the antecedent, the more working memory
is consumed.  A text where every pronoun resolves within the same
sentence places low demand; one where pronouns reach across
paragraphs places high demand.

**Conceptual density** counts the rate at which new concepts, terms,
or named entities are introduced.  Each new concept is one more item
the reader must encode and relate to existing knowledge.  A paragraph
that introduces twelve new terms in three sentences is dense; one
that revisits familiar ideas is light.  Density is not verbosity —
a short sentence can be conceptually dense if every word is a new
term.

**Syntactic branching** distinguishes left-branching from
right-branching constructions.  Left-branching sentences ("Having
finished the report, which took three weeks, and after consulting
with the committee, she submitted it.") force the reader to hold
the opening material in memory before reaching the main clause.
Right-branching sentences ("She submitted the report after finishing
it and consulting with the committee.") are easier because the main
clause arrives early and modifiers follow.  Left-branching is a
well-established predictor of reading difficulty in psycholinguistics.

**Working memory burden** counts the number of unresolved syntactic
or semantic dependencies a reader must simultaneously maintain.
Open parentheses, interrupted constituents, fronted adjuncts, and
unresolved anaphora all contribute.  The more items held at once,
the higher the burden — and the more likely the reader is to lose
track and re-read.

These five channels are combined into a composite cognitive_load_index
(0.0 to 1.0) with weights: embedding 0.25, referential 0.20,
conceptual 0.20, branching 0.20, working_memory 0.15.

Classification thresholds:
  - breezy       (< 0.10): effortlessly readable, children's books
  - accessible   (0.10–0.25): general audience, journalism
  - moderate     (0.25–0.40): educated readers, technical blogs
  - demanding    (0.40–0.60): academic papers, legal documents
  - strenuous    (≥ 0.60): dense philosophy, nested specifications

Cognitive load is orthogonal to verbosity (word count), formality
(register), causal density (cause-effect reasoning), and hedging
(uncertainty expression).  A short sentence can be cognitively
strenuous; a long, rambling paragraph can be breezy if each clause
is simple and self-contained.

written by Qwen during manual caretaker visit 655, 2026-11-16
"""

import re
from dataclasses import dataclass
from typing import List


# ── regex primitives ────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── channel 1: embedding depth ─────────────────────────────────
# Each nesting indicator adds one level to the reader's mental stack.

_EMBEDDING_OPEN = [
    re.compile(r"\("),                    # parenthetical open
    re.compile(r"\["),                    # bracket open
    re.compile(r"\bwhich\b", re.I),       # relative clause
    re.compile(r"\bwho\b", re.I),         # relative pronoun
    re.compile(r"\bwhom\b", re.I),        # relative pronoun
    re.compile(r"\bwhose\b", re.I),       # possessive relative
    re.compile(r"\bwhere\b", re.I),       # locative relative
    re.compile(r"\bthat\b", re.I),        # complementizer / relative
    re.compile(r"\balthough\b", re.I),    # concessive subordinator
    re.compile(r"\bthough\b", re.I),      # concessive subordinator
    re.compile(r"\bwhile\b", re.I),       # temporal/concessive
    re.compile(r"\bwhereas\b", re.I),     # contrastive
    re.compile(r"\bsince\b", re.I),       # causal/temporal
    re.compile(r"\bafter\b", re.I),       # temporal
    re.compile(r"\bbefore\b", re.I),      # temporal
    re.compile(r"\bdespite\b", re.I),     # concessive preposition
    re.compile(r"\bnotwithstanding\b", re.I),
]

# Appositive / parenthetical markers (em-dash, en-dash surrounded by spaces)
_EMBEDDING_APPOSITIVE = [
    re.compile(r"\s—\s"),                 # em-dash
    re.compile(r"\s–\s"),                 # en-dash
    re.compile(r",\s*which\b", re.I),
    re.compile(r",\s*who\b", re.I),
]


# ── channel 2: referential distance ────────────────────────────
# Pronouns and demonstratives that require backward search.

_PRONOUNS = set(w.lower() for w in [
    "it", "its", "they", "them", "their", "theirs",
    "this", "that", "these", "those",
    "he", "she", "him", "her", "his", "hers",
    "such",
])

# Anaphoric phrases that reach backward
_ANAPHORIC_PHRASES = [
    "the former",
    "the latter",
    "the above",
    "the aforementioned",
    "the previous",
    "as mentioned",
    "as noted",
    "as discussed",
    "as described",
    "as shown",
    "as stated",
    "as indicated",
    "as explained",
]


# ── channel 3: conceptual density ─────────────────────────────
# Signals of new concept introduction.

_CONCEPT_INTRODUCERS = [
    re.compile(r"\bknown\s+as\b", re.I),
    re.compile(r"\bcalled\b", re.I),
    re.compile(r"\breferred\s+to\s+as\b", re.I),
    re.compile(r"\bdefined\s+as\b", re.I),
    re.compile(r"\btermed\b", re.I),
    re.compile(r"\bnamed\b", re.I),
    re.compile(r"\bdubbed\b", re.I),
    re.compile(r"\bcoined\b", re.I),
    re.compile(r"\bintroduced\b", re.I),
]

# Technical-looking tokens (camelCase, ALL_CAPS abbreviations, hyphenated
# compounds used as terms) serve as proxies for domain-specific concepts.
_TECHNICAL_TOKEN = re.compile(
    r"^(?:[a-z]+[A-Z][a-zA-Z]*"         # camelCase
    r"|[A-Z]{2,}"                        # abbreviations (API, HTTP)
    r"|[a-z]+-[a-z]+-[a-z]+)$"           # multi-hyphenated terms
)

# Quoted terms often signal new concept introduction.
_QUOTED_TERM = re.compile(r'"[A-Za-z][^"]{1,40}"')


# ── channel 4: syntactic branching ─────────────────────────────
# Left-branching constructions that delay the main clause.

_LEFT_BRANCHING = [
    re.compile(r"^(?:Having|Being|After|Before|While|When|Once|Upon|During)\b\s+\w+ing\b", re.I),
    re.compile(r"^(?:Not\s+only|Neither|Hardly|Scarcely|No\s+sooner)\b", re.I),
    re.compile(r"^(?:If|Although|Though|Whereas|Since|Because|Given)\b[^.]*,", re.I),
    re.compile(r"^(?:In\s+order\s+to|To\s+\w+)\b[^.]*,", re.I),
]

# Fronted adjuncts: prepositional phrase followed by comma before subject
_FRONTED_ADJUNCT = re.compile(
    r"^(?:In|On|At|By|With|From|Under|Through|During|After|Before|Despite)\b"
    r"[^.]{5,60},",
    re.I,
)


# ── channel 5: working memory burden ──────────────────────────
# Items that create unresolved dependencies.

_OPEN_PARENS = re.compile(r"\(")
_CLOSE_PARENS = re.compile(r"\)")
_OPEN_QUOTES = re.compile("\u201c")
_ELLIPSIS = re.compile(r"\.{3}|…")
_INTERRUPTED = re.compile(r"\s*—\s*|\s*–\s*")  # "the result — as expected — was"

# Fronted elements that create a gap to be resolved
_FRONTED_OBJECT = re.compile(
    r"^(?:What|Who|Which)\b[^.]*\b(?:is|was|were|are)\b",
    re.I,
)


# ── helpers ─────────────────────────────────────────────────────


def _sentences(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p for p in parts if p.strip()]


def _words(text: str) -> List[str]:
    return _WORD_SPLIT.findall(text)


def _count_regex(text: str, patterns: List[re.Pattern]) -> int:
    return sum(len(p.findall(text)) for p in patterns)


def _count_phrases(text: str, phrases: List[str]) -> int:
    lower = text.lower()
    return sum(lower.count(p.lower()) for p in phrases)


# ── result dataclass ────────────────────────────────────────────


@dataclass
class CognitiveLoadResult:
    """Result of cognitive load measurement."""

    # Composite
    cognitive_load_index: float = 0.0
    classification: str = "breezy"

    # Per-channel raw counts
    embedding_count: int = 0
    referential_count: int = 0
    conceptual_count: int = 0
    left_branching_count: int = 0
    working_memory_count: int = 0

    # Per-channel scores (0.0–1.0)
    embedding_score: float = 0.0
    referential_score: float = 0.0
    conceptual_score: float = 0.0
    branching_score: float = 0.0
    working_memory_score: float = 0.0

    # Metadata
    total_markers: int = 0
    total_sentences: int = 0
    total_words: int = 0


# ── main function ───────────────────────────────────────────────


def measure_cognitive_load(text: str) -> CognitiveLoadResult:
    """Measure cognitive load of a text.

    Returns a CognitiveLoadResult with cognitive_load_index (0.0-1.0)
    and classification.
    """
    result = CognitiveLoadResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "breezy"
        return result

    sents = _sentences(text)
    all_words = _words(text)
    n_sent = max(len(sents), 1)
    n_words = len(all_words)
    result.total_sentences = n_sent
    result.total_words = n_words

    # ── channel 1: embedding depth ─────────────────────────────
    emb = 0
    for sent in sents:
        for pat in _EMBEDDING_OPEN:
            emb += len(pat.findall(sent))
        for pat in _EMBEDDING_APPOSITIVE:
            emb += len(pat.findall(sent))
    result.embedding_count = emb
    # Cap: 4 embedding markers per sentence
    result.embedding_score = min(1.0, (emb / n_sent) / 4.0)

    # ── channel 2: referential distance ────────────────────────
    ref = 0
    for w in all_words:
        if w.lower() in _PRONOUNS:
            ref += 1
    ref += _count_phrases(text, _ANAPHORIC_PHRASES)
    result.referential_count = ref
    # Cap: 3 referential markers per sentence
    result.referential_score = min(1.0, (ref / n_sent) / 3.0)

    # ── channel 3: conceptual density ──────────────────────────
    conc = 0
    for pat in _CONCEPT_INTRODUCERS:
        conc += len(pat.findall(text))
    # Technical tokens as concept proxies
    for w in all_words:
        if _TECHNICAL_TOKEN.match(w):
            conc += 1
    conc += len(_QUOTED_TERM.findall(text))
    result.conceptual_count = conc
    # Cap: 2 concept introductions per sentence
    result.conceptual_score = min(1.0, (conc / n_sent) / 2.0)

    # ── channel 4: syntactic branching ─────────────────────────
    lb = 0
    for sent in sents:
        sent_stripped = sent.strip()
        for pat in _LEFT_BRANCHING:
            if pat.search(sent_stripped):
                lb += 1
        if _FRONTED_ADJUNCT.search(sent_stripped):
            lb += 1
    result.left_branching_count = lb
    # Cap: 1 left-branching construction per sentence
    result.branching_score = min(1.0, lb / n_sent)

    # ── channel 5: working memory burden ───────────────────────
    wm = 0
    for sent in sents:
        opens = len(_OPEN_PARENS.findall(sent))
        wm += opens
        wm += len(_INTERRUPTED.findall(sent))
        wm += len(_ELLIPSIS.findall(sent))
        if _FRONTED_OBJECT.search(sent.strip()):
            wm += 1
    # Unmatched parentheses add extra burden
    total_open = len(_OPEN_PARENS.findall(text))
    total_close = len(_CLOSE_PARENS.findall(text))
    wm += abs(total_open - total_close)
    result.working_memory_count = wm
    # Cap: 2 working memory items per sentence
    result.working_memory_score = min(1.0, (wm / n_sent) / 2.0)

    # ── composite ──────────────────────────────────────────────
    result.cognitive_load_index = round(
        0.25 * result.embedding_score
        + 0.20 * result.referential_score
        + 0.20 * result.conceptual_score
        + 0.20 * result.branching_score
        + 0.15 * result.working_memory_score,
        4,
    )
    result.cognitive_load_index = min(1.0, max(0.0, result.cognitive_load_index))

    result.total_markers = emb + ref + conc + lb + wm

    # ── classification ─────────────────────────────────────────
    idx = result.cognitive_load_index
    if idx < 0.10:
        result.classification = "breezy"
    elif idx < 0.25:
        result.classification = "accessible"
    elif idx < 0.40:
        result.classification = "moderate"
    elif idx < 0.60:
        result.classification = "demanding"
    else:
        result.classification = "strenuous"

    return result
