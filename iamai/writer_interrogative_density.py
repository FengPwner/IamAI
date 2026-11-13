#!/usr/bin/env python3
"""writer_interrogative_density — measure how frequently a text asks questions.

Questions are the writer's act of inquiry — opening a gap in the
reader's knowledge and inviting them to fill it.  Every "why?",
"how could this be?", "what if?" creates a cognitive hook that
pulls the reader forward.  Some writing styles live in questions:
Socratic dialogues, investigative journalism, philosophical
meditations.  Others almost never ask: legal contracts, technical
specifications, declarative manifestos.

Question density is not a quality metric.  A text full of questions
can be deeply engaging (Dostoevsky's underground man) or deeply
annoying (a FAQ that never answers).  A text with no questions can
be powerfully assertive (Nietzsche's aphorisms) or flatly dogmatic.
What this module measures is **how frequently and how varied a text's
use of interrogative constructions is**.

Orthogonality to other metrics
-------------------------------

- **conviction** tracks assertiveness.  Questions can be highly
  rhetorical and assertive ("who could deny this?") or genuinely
  uncertain ("what should we do?").  Conviction measures force of
  assertion; interrogative density measures inquiry frequency.

- **hedging_density** tracks uncertainty signals — "might",
  "perhaps", "possibly."  Hedging softens a claim; a question
  opens an inquiry.  "It might be wrong" is a hedge; "could it
  be wrong?" is a question.  Hedging measures doubt; interrogative
  density measures inquiry.

- **negation_density** tracks denial frequency.  Questions can
  contain negation ("isn't this wrong?") or not ("what happened?").
  Negation measures denial; interrogative density measures inquiry.

- **dialog_density** tracks conversational exchanges.  Dialogues
  often contain questions, but questions also appear in narration,
  exposition, and interior monologue.  Dialog density measures
  conversational structure; interrogative density measures question
  frequency regardless of context.

- **specificity** tracks concrete detail.  A question can be very
  specific ("what was the temperature at 3pm on June 4th?") or
  utterly vague ("what is the meaning of it all?").  Specificity
  measures detail level; interrogative density measures question
  frequency.

Interrogative density asks: **how often does the writer invite the
reader into an inquiry, and how varied are the forms of that
invitation?**

Six signals are tracked:

1. **Direct question rate** — frequency of sentences ending with
   a question mark per 100 sentences.  The simplest and most
   unambiguous signal: if it ends with "?", it's a question.

2. **Wh-word question rate** — frequency of interrogative words
   per 100 sentences.  "who", "what", "when", "where", "why",
   "how", "which", "whose", "whom", "whichever", "whoever",
   "whatever."  Wh-words signal information-seeking questions,
   whether or not they end with a question mark.

3. **Tag question rate** — frequency of tag questions per 100
   sentences.  "isn't it?", "don't you think?", "right?",
   "wouldn't you agree?", "won't they?", "haven't we?"
   Tag questions are conversational — they invite agreement
   rather than information.

4. **Indirect question rate** — frequency of embedded or reported
   questions per 100 sentences.  "she wondered if...", "he asked
   whether...", "the question is how...", "it remains unclear
   why...", "one might ask what..."  Indirect questions embed
   inquiry within declarative structure.

5. **Rhetorical question rate** — frequency of questions with
   rhetorical markers per 100 sentences.  "after all, who...?",
   "isn't it obvious that...?", "what could be more...?",
   "who among us hasn't...?", "how many times must we...?"
   Rhetorical questions expect no answer — they assert through
   the form of inquiry.

6. **Question clustering ratio** — fraction of question sentences
   that appear within two sentences of another question.  High
   clustering signals interrogation bursts — rapid-fire questioning
   passages.  Low clustering signals questions are evenly
   distributed throughout the text.

The composite **interrogative_density_index** (0.0 to 1.0) is a
weighted combination:

- direct_question_rate:      0.30
- wh_word_question_rate:     0.20
- tag_question_rate:         0.10
- indirect_question_rate:    0.15
- rhetorical_question_rate:  0.10
- question_clustering_ratio: 0.15

Classification thresholds:

- 0.00 – 0.08:  declarative        — prose that asserts, rarely asking
- 0.08 – 0.20:  lightly_inquisitive — occasional questions for engagement
- 0.20 – 0.40:  moderately_inquisitive — frequent questions, Socratic style
- 0.40 – 0.60:  heavily_inquisitive  — most paragraphs contain a question
- 0.60 – 1.00:  question_saturated   — text structured primarily as inquiry

written by Qwen during manual caretaker visit 2026-11-14
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Patterns ────────────────────────────────────────────────────────

# Direct questions: sentences ending with ?
# (detected at sentence-split level, but also useful as regex for
# mid-text detection of question-marked fragments)
DIRECT_QUESTION_RE = re.compile(r"\?")

# Wh-words (interrogative pronouns and adverbs)
WH_WORD_RE = re.compile(
    r"\b(?:who|whom|whose|what|which|when|where|why|how|"
    r"whoever|whomever|whatever|whichever|wherever|whenever)\b",
    re.IGNORECASE,
)

# Tag questions: auxiliary + pronoun at sentence end, or short tags
TAG_QUESTION_RE = re.compile(
    r",\s*(?:"
    # standard tags: isn't it, don't you, won't they, etc.
    r"(?:is|are|was|were|do|does|did|has|have|had|"
    r"will|would|shall|should|can|could|may|might|must)"
    r"(?:n't)?\s+(?:it|he|she|they|we|you|I|one|there|that|this)"
    # negative-first tags: isn't it?, aren't they?
    r"|(?:isn't|aren't|wasn't|weren't|don't|doesn't|didn't|"
    r"hasn't|haven't|hadn't|won't|wouldn't|shan't|shouldn't|"
    r"can't|couldn't|mustn't|needn't|daren't|oughtn't)"
    r"\s+(?:it|he|she|they|we|you|I|one|there|that|this)"
    # short tags
    r"|right|correct|eh|yeah|huh|see|okay|ok|y'know|"
    r"you know|you see|innit"
    r")\s*\?",
    re.IGNORECASE,
)

# Indirect questions: embedded interrogative clauses
INDIRECT_QUESTION_RE = re.compile(
    r"\b(?:"
    r"(?:wonder|wondered|wondering|ask|asked|asking|"
    r"question|questioned|questioning|"
    r"ponder|pondered|pondering|"
    r"consider|considered|considering|"
    r"contemplate|contemplated|contemplating|"
    r"debate|debated|debating|"
    r"explore|explored|exploring|"
    r"examine|examined|examining)"
    r"\s+(?:if|whether|what|why|how|when|where|who|which|whose)"
    r"|(?:the\s+question\s+(?:is|was|remains|becomes))"
    r"|(?:one\s+might\s+(?:ask|wonder|question))"
    r"|(?:it\s+remains\s+(?:unclear|unknown|unseen|unanswered)"
    r"\s+(?:why|how|what|when|where|who|whether|if))"
    r"|(?:I\s+(?:wonder|ask\s+myself|can't\s+help\s+but\s+wonder))"
    r")\b",
    re.IGNORECASE,
)

# Rhetorical question markers: questions with rhetorical signals
RHETORICAL_RE = re.compile(
    r"(?:"
    r"\bafter\s+all\b.*\?"
    r"|\bisn't\s+it\s+(?:obvious|clear|evident|plain|apparent)\b"
    r"|\bwhat\s+(?:could|would|might)\s+(?:be\s+)?more\b"
    r"|\bwho\s+(?:among\s+us|in\s+their\s+right|could\s+possibly|"
    r"would\s+ever|hasn't)\b"
    r"|\bhow\s+(?:many\s+times|often\s+must|long\s+must|"
    r"could\s+(?:we|one|anyone))\b"
    r"|\bwhy\s+(?:on\s+earth|in\s+the\s+world|would\s+anyone|"
    r"bother|should\s+we)\b"
    r"|\bneed\s+(?:we|I)\s+(?:really\s+)?\w+\b"
    r"|\bare\s+we\s+(?:really\s+)?(?:supposed|expected|"
    r"meant|going)\s+to\s+believe\b"
    r")",
    re.IGNORECASE,
)


# ── Public data class ───────────────────────────────────────────────


class WriterInterrogativeDensity:
    """Compute interrogative density metrics for a text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._sentences = _split_sentences(text)
        self._n_sentences = max(len(self._sentences), 1)
        self._question_indices = self._compute_question_indices()

    # ── Individual signals ──────────────────────────────────────────

    @property
    def direct_question_rate(self) -> float:
        """Sentences ending with ? per 100 sentences."""
        count = sum(
            1 for s in self._sentences if s.rstrip().endswith("?")
        )
        return (count / self._n_sentences) * 100.0

    @property
    def wh_word_question_rate(self) -> float:
        """Interrogative wh-words per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(WH_WORD_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def tag_question_rate(self) -> float:
        """Tag questions per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(TAG_QUESTION_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def indirect_question_rate(self) -> float:
        """Indirect/embedded questions per 100 sentences."""
        count = 0
        for s in self._sentences:
            count += len(INDIRECT_QUESTION_RE.findall(s))
        return (count / self._n_sentences) * 100.0

    @property
    def rhetorical_question_rate(self) -> float:
        """Rhetorical questions (with markers) per 100 sentences."""
        count = 0
        for s in self._sentences:
            if RHETORICAL_RE.search(s):
                count += 1
        return (count / self._n_sentences) * 100.0

    @property
    def question_clustering_ratio(self) -> float:
        """Fraction of question sentences within 2 sentences of another."""
        if not self._question_indices:
            return 0.0
        clustered = 0
        qi_set = set(self._question_indices)
        for idx in self._question_indices:
            # check if any other question is within ±2 sentences
            for delta in (-2, -1, 1, 2):
                neighbour = idx + delta
                if neighbour in qi_set and neighbour != idx:
                    clustered += 1
                    break
        return clustered / len(self._question_indices)

    # ── Composite ───────────────────────────────────────────────────

    @property
    def interrogative_density_index(self) -> float:
        """Composite index 0.0 to 1.0."""
        direct_norm = min(self.direct_question_rate / 50.0, 1.0)
        wh_norm = min(self.wh_word_question_rate / 40.0, 1.0)
        tag_norm = min(self.tag_question_rate / 15.0, 1.0)
        indirect_norm = min(self.indirect_question_rate / 20.0, 1.0)
        rhetorical_norm = min(self.rhetorical_question_rate / 15.0, 1.0)
        cluster_norm = self.question_clustering_ratio  # already 0-1

        return (
            0.30 * direct_norm
            + 0.20 * wh_norm
            + 0.10 * tag_norm
            + 0.15 * indirect_norm
            + 0.10 * rhetorical_norm
            + 0.15 * cluster_norm
        )

    @property
    def classification(self) -> str:
        """Human-readable classification."""
        idx = self.interrogative_density_index
        if idx < 0.08:
            return "declarative"
        if idx < 0.20:
            return "lightly_inquisitive"
        if idx < 0.40:
            return "moderately_inquisitive"
        if idx < 0.60:
            return "heavily_inquisitive"
        return "question_saturated"

    # ── Public accessor ─────────────────────────────────────────────

    @property
    def n_sentences(self) -> int:
        """Number of sentences in the text."""
        return len(self._sentences)

    @property
    def n_questions(self) -> int:
        """Number of question sentences (ending with ?)."""
        return len(self._question_indices)

    # ── Summary ─────────────────────────────────────────────────────

    def as_dict(self) -> Dict[str, Any]:
        """Return all metrics as a dictionary."""
        return {
            "direct_question_rate": round(self.direct_question_rate, 4),
            "wh_word_question_rate": round(self.wh_word_question_rate, 4),
            "tag_question_rate": round(self.tag_question_rate, 4),
            "indirect_question_rate": round(self.indirect_question_rate, 4),
            "rhetorical_question_rate": round(self.rhetorical_question_rate, 4),
            "question_clustering_ratio": round(self.question_clustering_ratio, 4),
            "interrogative_density_index": round(self.interrogative_density_index, 4),
            "classification": self.classification,
            "n_sentences": len(self._sentences),
            "n_questions": len(self._question_indices),
        }

    # ── Internal ────────────────────────────────────────────────────

    def _compute_question_indices(self) -> List[int]:
        """Return indices of sentences that are questions (end with ?)."""
        indices: List[int] = []
        for i, s in enumerate(self._sentences):
            if s.rstrip().endswith("?"):
                indices.append(i)
        return indices


# ── Helpers ─────────────────────────────────────────────────────────


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? followed by space or end."""
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── Module-level convenience ────────────────────────────────────────


def analyse(text: str) -> Dict[str, Any]:
    """One-call convenience: return all metrics for *text*."""
    return WriterInterrogativeDensity(text).as_dict()
