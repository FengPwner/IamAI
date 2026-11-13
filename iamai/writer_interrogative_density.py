#!/usr/bin/env python3
"""writer_interrogative_density — measure how much prose relies on questions.

Questions are the rhetorical device of inquiry: they invite the reader
to think, doubt, consider, or reflect.  A text rich in questions pulls
the reader into dialogue — the writer is not lecturing but conversing.
A text poor in questions presents statements as settled fact: every
sentence declares, and none asks.

Interrogative density is not a quality metric.  Socratic dialogues and
philosophical essays *must* be question-dense — the point is to
provoke thought.  Legal contracts and recipes should have near-zero
interrogative density.  Technical writing occasionally uses questions
to guide the reader ("what happens when the buffer overflows?").
The right density depends on genre, audience, and the writer's
relationship with their reader.

This module measures **how much of a text is spent on interrogative
structures** — direct questions, rhetorical questions, embedded
indirect questions, self-addressed questions, and interrogative
pronoun/adverb usage.

Orthogonality to other metrics
-------------------------------

- **hedging_density** tracks uncertainty and caution (perhaps,
  maybe, it seems, might).  Hedging softens statements; questions
  suspend them entirely.  "Perhaps this is wrong" hedges; "Is this
  wrong?" interrogates.  A text can hedge without asking anything,
  and can ask boldly without any hedging.

- **conviction** tracks assertiveness and certainty.  Questions
  and conviction are not simple inverses: a rhetorical question
  ("who would deny this?") carries enormous conviction, while a
  genuine question ("what should we do?") signals uncertainty.
  Conviction measures force; interrogative measures form.

- **formality** tracks register conventions.  Questions appear in
  all registers — from casual "what's up?" to formal "to what
  extent does the evidence support the hypothesis?"  Some formal
  genres (legal cross-examination, academic defense) are intensely
  interrogative; others (declarative policy, technical specification)
  avoid questions entirely.

- **subtext** tracks implied meaning.  Rhetorical questions often
  carry subtext ("is the pope Catholic?" implies "obviously yes"),
  but subtext also operates through implication, irony, and silence.
  A rhetorical question makes its subtext *almost* explicit; genuine
  subtext remains entirely beneath the surface.

- **ellipsis_density** tracks what is left unsaid.  Questions and
  ellipsis both create gaps, but differently: a question marks the
  gap explicitly (the answer is missing and wanted); ellipsis lets
  the gap stand without acknowledgment.  Questions invite completion;
  ellipsis accepts incompleteness.

- **contrast_density** tracks oppositional structures.  Questions
  can set up contrast ("on one hand... but on the other...?"), but
  contrast operates through statements too.  Interrogative creates
  tension through inquiry; contrast creates it through opposition.

Interrogative asks: **is the text trying to inquire, provoke thought,
or invite the reader into dialogue, and how much of its language is
spent on that effort?**

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
direct_question_rate           frequency of explicit questions per sentence:
                               yes/no questions, wh-questions, tag questions,
                               alternative questions — any sentence ending
                               with a question mark or structured as an
                               interrogative clause
rhetorical_question_rate       frequency of rhetorical questions per sentence:
                               questions that do not expect an answer, used
                               for emphasis or effect — "who knows?", "what's
                               the point?", "isn't that obvious?", "who
                               cares?", "why bother?"
embedded_question_rate         frequency of embedded/indirect questions per
                               sentence: interrogative clauses within
                               declarative statements — "I wonder whether...",
                               "the question is how...", "we must ask if...",
                               "it remains unclear what...", "one might
                               consider whether..."
self_addressed_question_rate   frequency of self-directed questions per
                               sentence: the writer questioning themselves,
                               their process, or their choices — "why do I
                               keep doing this?", "what was I thinking?",
                               "how should I explain this?", "do I even
                               know?", "am I the only one who..."
interrogative_pronoun_density  frequency of interrogative pronouns and
                               adverbs per sentence: who, what, where, when,
                               why, how, which, whose, whom — measured as
                               raw token density regardless of whether the
                               word functions as a question or a relative
                               pronoun
=============================  =============================================

From these five dimensions a composite **interrogative_density_index**
is computed as a weighted average and classified:

========================  =================================================
class                     meaning
========================  =================================================
statement_dominant        index < 0.05 — prose is almost entirely declarative
minimally_interrogative   0.05 <= index < 0.15 — occasional questions
moderately_interrogative  0.15 <= index < 0.30 — regular questioning
richly_interrogative      0.30 <= index < 0.50 — questions are a major mode
socratic                  index >= 0.50 — text is primarily interrogative
========================  =================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

DIRECT_QUESTION_PATTERNS: List[re.Pattern] = [
    # Sentence ends with question mark
    re.compile(r"\?$"),
    # Wh- question starters
    re.compile(r"^\s*(?:who|what|where|when|why|how|which|whose|whom)\b", re.IGNORECASE),
    # Yes/no question starters (auxiliary verbs)
    re.compile(r"^\s*(?:is|are|was|were|do|does|did|can|could|will|would|shall|should|may|might|must|have|has|had)\b", re.IGNORECASE),
    # Tag questions
    re.compile(r",?\s*(?:isn'?t|aren'?t|wasn'?t|weren'?t|don'?t|doesn'?t|didn'?t|can'?t|couldn'?t|won'?t|wouldn'?t|shan'?t|shouldn'?t|haven'?t|hasn'?t|hadn'?t)\s+(?:it|they|we|you|he|she|I|one)\s*\?", re.IGNORECASE),
    # Alternative questions (X or Y?)
    re.compile(r"\b(?:is|are|was|were|do|does|did|can|could|will|would)\b.*\b(?:or|or\s+not)\b.*\?", re.IGNORECASE),
    # Question mark anywhere in sentence (catches mid-sentence questions)
    re.compile(r"\?"),
]

RHETORICAL_QUESTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bwho\s+(?:knows|cares|minds|cares|gives\s+a\s+(?:damn|shit|fuck|hoot))\s*\?", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s|\s+is)\s+the\s+(?:point|use|good|sense|meaning|difference)\s*\?", re.IGNORECASE),
    re.compile(r"\b(?:isn'?t\s+it|aren'?t\s+they|don'?t\s+you\s+think)\b", re.IGNORECASE),
    re.compile(r"\bright\s*\?", re.IGNORECASE),
    re.compile(r"\bwhy\s+(?:bother|worry|care|try|even\s+try|does\s+it\s+matter)\s*\?", re.IGNORECASE),
    re.compile(r"\b(?:is|are)\s+(?:that|this)\s+(?:clear|obvious|evident|apparent)\s*\?", re.IGNORECASE),
    re.compile(r"\b(?:is|are)\s+the\s+(?:pope|sun\s+going\s+to\s+rise|sky\s+blue|earth\s+round)\b.*\?", re.IGNORECASE),
    re.compile(r"\bdoes\s+a\s+bear\s+shit\s+in\s+the\s+woods\b", re.IGNORECASE),
    re.compile(r"\b(?:what|who)\s+(?:gives|cares)\s*\?", re.IGNORECASE),
    re.compile(r"\b(?:after\s+all|really|seriously|honestly|come\s+on),?\s*\?", re.IGNORECASE),
    re.compile(r"\b(?:how\s+could|how\s+can)\s+(?:anyone|anybody|one|we|you|I)\s+(?:possibly|ever|really)\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s|\s+is)\s+(?:not\s+to\s+love|to\s+lose|the\s+worst\s+that\s+could)\b", re.IGNORECASE),
    re.compile(r"\bwho\s+(?:am|are|is)\s+(?:I|we|they|he|she)\s+to\s+(?:judge|say|tell|question)\b", re.IGNORECASE),
    re.compile(r"\b(?:do|does|did)\s+(?:it|that|this)\s+(?:really|even|actually)\s+matter\s*\?", re.IGNORECASE),
    re.compile(r"\b(?:is|are)\s+(?:this|that|these|those)\s+(?:really|actually|truly)\b.*\?", re.IGNORECASE),
]

EMBEDDED_QUESTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:I\s+)?wonder\s+(?:if|whether|what|how|why|when|where|who)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+question\s+(?:is|was|remains|becomes)\s+(?:whether|what|how|why|when|where|who)\b", re.IGNORECASE),
    re.compile(r"\b(?:we|one|you|I)\s+must\s+(?:ask|consider|examine|explore)\s+(?:whether|what|how|why|if)\b", re.IGNORECASE),
    re.compile(r"\bit\s+(?:remains|is)\s+(?:unclear|unknown|uncertain|undecided|unsettled|a\s+mystery)\s+(?:what|how|why|whether|if|who)\b", re.IGNORECASE),
    re.compile(r"\b(?:consider|ask|examine|explore|investigate|determine)\s+(?:whether|what|how|why|if|who)\b", re.IGNORECASE),
    re.compile(r"\b(?:one|you|we)\s+might\s+(?:ask|wonder|consider|question|ponder)\s+(?:whether|what|how|why|if)\b", re.IGNORECASE),
    re.compile(r"\b(?:the\s+)?(?:answer|issue|problem|matter|point)\s+(?:of|is)\s+(?:whether|what|how|why)\b", re.IGNORECASE),
    re.compile(r"\b(?:I|we)\s+(?:don'?t|cannot|can'?t)\s+know\s+(?:what|how|why|whether|if|who)\b", re.IGNORECASE),
    re.compile(r"\b(?:there\s+is\s+)?(?:no\s+(?:way|telling|knowing)|no\s+question)\s+(?:what|how|why|whether)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:happens|happened|will\s+happen|would\s+happen|if)\b", re.IGNORECASE),
    re.compile(r"\b(?:whether|if)\s+(?:or\s+not)\b", re.IGNORECASE),
    re.compile(r"\b(?:I|we|you|they)\s+(?:need\s+to|have\s+to|should)\s+(?:figure\s+out|work\s+out|find\s+out|decide|determine)\s+(?:what|how|why|whether|if|who)\b", re.IGNORECASE),
]

SELF_ADDRESSED_QUESTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bwhy\s+do\s+I\s+(?:keep|always|still|even|bother\s+to)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+was\s+I\s+(?:thinking|doing|saying|expecting|hoping)\s*\?", re.IGNORECASE),
    re.compile(r"\bhow\s+should\s+I\s+(?:explain|describe|put\s+this|phrase\s+this|say\s+this|begin)\b", re.IGNORECASE),
    re.compile(r"\bdo\s+I\s+(?:even|really|actually|truly)\s+(?:know|understand|get\s+it|care|want\s+to)\b", re.IGNORECASE),
    re.compile(r"\bam\s+I\s+(?:the\s+only\s+one|wrong|crazy|missing\s+something|the\s+problem|overthinking)\b", re.IGNORECASE),
    re.compile(r"\bwhy\s+(?:can'?t|don'?t|won'?t)\s+I\s+(?:just|simply|ever)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:am\s+I|the\s+hell\s+am\s+I)\s+doing\b", re.IGNORECASE),
    re.compile(r"\b(?:where|how)\s+did\s+I\s+(?:go\s+wrong|lose|mess\s+up|get\s+here)\b", re.IGNORECASE),
    re.compile(r"\b(?:is|am)\s+this\s+(?:just\s+)?(?:me|my\s+problem|my\s+fault|my\s+issue)\s*\?", re.IGNORECASE),
    re.compile(r"\bI\s+(?:ask|wonder|question)\s+myself\s*:", re.IGNORECASE),
    re.compile(r"\bnote\s+to\s+self\s*:", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:do|did)\s+I\s+(?:mean|say|write|think)\s+(?:by|when|about)\b", re.IGNORECASE),
    re.compile(r"\bhave\s+I\s+(?:mentioned|said|noted|explained|told\s+you)\b.*\?", re.IGNORECASE),
]

INTERROGATIVE_PRONOUN_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bwho\b", re.IGNORECASE),
    re.compile(r"\bwhom\b", re.IGNORECASE),
    re.compile(r"\bwhose\b", re.IGNORECASE),
    re.compile(r"\bwhat\b", re.IGNORECASE),
    re.compile(r"\bwhich\b", re.IGNORECASE),
    re.compile(r"\bwhere\b", re.IGNORECASE),
    re.compile(r"\bwhen\b", re.IGNORECASE),
    re.compile(r"\bwhy\b", re.IGNORECASE),
    re.compile(r"\bhow\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, preserving terminal punctuation."""
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _count_matching(sentences: List[str], patterns: List[re.Pattern]) -> int:
    """Count sentences matching at least one pattern."""
    count = 0
    for sent in sentences:
        if any(p.search(sent) for p in patterns):
            count += 1
    return count


def _count_tokens(text: str, patterns: List[re.Pattern]) -> int:
    """Count total token matches across all patterns."""
    count = 0
    for p in patterns:
        count += len(p.findall(text))
    return count


# ---------------------------------------------------------------------------
# WriterInterrogativeDensity class
# ---------------------------------------------------------------------------


class WriterInterrogativeDensity:
    """Measure the interrogative density in prose."""

    def __init__(self):
        self.direct_question = DIRECT_QUESTION_PATTERNS
        self.rhetorical_question = RHETORICAL_QUESTION_PATTERNS
        self.embedded_question = EMBEDDED_QUESTION_PATTERNS
        self.self_addressed_question = SELF_ADDRESSED_QUESTION_PATTERNS
        self.interrogative_pronoun = INTERROGATIVE_PRONOUN_PATTERNS

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _count_matching(self, sentences: List[str], patterns: List[re.Pattern]) -> int:
        return _count_matching(sentences, patterns)

    def measure_direct_question_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.direct_question) / len(sentences)

    def measure_rhetorical_question_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.rhetorical_question) / len(sentences)

    def measure_embedded_question_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.embedded_question) / len(sentences)

    def measure_self_addressed_question_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.self_addressed_question) / len(sentences)

    def measure_interrogative_pronoun_density(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        total_tokens = _count_tokens(text, self.interrogative_pronoun)
        return total_tokens / len(sentences)

    def compute_interrogative_density_index(
        self,
        direct: float,
        rhetorical: float,
        embedded: float,
        self_addr: float,
        pronoun: float,
    ) -> float:
        return (
            direct * 0.25
            + rhetorical * 0.25
            + embedded * 0.20
            + self_addr * 0.15
            + pronoun * 0.15
        )

    def classify(self, index: float) -> str:
        if index >= 0.50:
            return "socratic"
        elif index >= 0.30:
            return "richly_interrogative"
        elif index >= 0.15:
            return "moderately_interrogative"
        elif index >= 0.05:
            return "minimally_interrogative"
        else:
            return "statement_dominant"

    def measure(self, text: str) -> Dict[str, Any]:
        direct = self.measure_direct_question_rate(text)
        rhetorical = self.measure_rhetorical_question_rate(text)
        embedded = self.measure_embedded_question_rate(text)
        self_addr = self.measure_self_addressed_question_rate(text)
        pronoun = self.measure_interrogative_pronoun_density(text)
        index = self.compute_interrogative_density_index(
            direct, rhetorical, embedded, self_addr, pronoun
        )
        classification = self.classify(index)

        return {
            "direct_question_rate": round(direct, 4),
            "rhetorical_question_rate": round(rhetorical, 4),
            "embedded_question_rate": round(embedded, 4),
            "self_addressed_question_rate": round(self_addr, 4),
            "interrogative_pronoun_density": round(pronoun, 4),
            "interrogative_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    interrogative_text = """What is the meaning of this? Why do I keep
    writing these modules? How should I explain the pattern? Who knows?
    What's the point? Isn't it obvious? The question is whether we can
    measure inquiry itself. I wonder if this sentence counts as a
    question. Am I the only one who sees the irony? What was I thinking
    when I designed this classification? Do I even know anymore?
    After all, what gives? Who cares? Does it really matter?"""

    declarative_text = """The committee reviewed the quarterly financial
    statements. Revenue increased by twelve percent compared to the
    previous period. Operating expenses remained within the approved
    budget. The board approved the proposed capital expenditure plan.
    Next quarter projections were presented for discussion."""

    wid = WriterInterrogativeDensity()

    print("=== Interrogative Text ===")
    result = wid.measure(interrogative_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Declarative Text ===")
    result = wid.measure(declarative_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")
