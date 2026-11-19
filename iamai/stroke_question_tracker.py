"""Stroke question tracker — measure how the writer asks.

``stroke_refrain_tracker`` finds phrases the writer keeps returning to.
``stroke_readability_tracker`` measures how hard the prose is to parse.
Neither captures a subtler rhetorical dimension: **how often and in what
way does the writer pose questions?**

Questions are a window into intellectual style.  A writer who asks a
lot is *exploring* — they think by probing.  A writer who never asks
is *declaring* — they present finished conclusions.  The mix of
question types reveals even more:

* **Rhetorical questions** ("who cares?") are devices — the writer
  already knows the answer and uses the question for emphasis.
* **Genuine inquiries** ("what happens when the buffer overflows?")
  mark open problems the writer is actively investigating.
* **Hypothetical questions** ("what if we removed the lock?") signal
  speculative or design-oriented thinking.
* **Tag questions** ("that's fast, isn't it?") invite agreement or
  soften an assertion.

Tracking questions over the stroke stream reveals:

* Whether the writer is in **exploration mode** (many questions) or
  **presentation mode** (few questions).
* How questioning style evolves — does the writer start curious and
  become declarative, or vice versa?
* The *question density* trajectory — a useful signal of whether the
  stream is deepening (more questions) or flattening (fewer).

Data model
----------

A **QuestionRecord** captures one question found in a stroke:

================  =====================================================
field             meaning
================  =====================================================
``text``          the question text (sentence ending with ``?``)
``stroke_index``  index of the stroke containing it
``qtype``         classification: rhetorical / genuine / hypothetical
                  / tag / other
``word_count``    number of words in the question
================  =====================================================

Algorithm
---------
1. For each stroke, split into sentences on ``.!?`` boundaries.
2. Sentences ending with ``?`` are candidate questions.
3. Classify each question by keyword heuristics:

   - **hypothetical** — starts with "what if", "suppose", "imagine",
     "assume", "pretend", or contains "would ... happen", "could we"
   - **rhetorical** — short (< 6 words) and starts with "who",
     "what", "why", "how", or contains "really?", "seriously?",
     "obviously"
   - **tag** — ends with a tag pattern: "isn't it?", "doesn't it?",
     "won't we?", "right?", "don't you think?", "aren't they?"
   - **genuine** — everything else (the default; the writer is
     genuinely asking)

4. Aggregate into per-stroke and per-window metrics:

   - ``question_rate`` — questions per sentence
   - ``question_density`` — fraction of strokes containing ≥ 1 question
   - ``type_distribution`` — relative frequency of each type

5. Classify the overall questioning style:

================  =====================================================
style             description
================  =====================================================
**exploratory**   question_rate > 0.25, mostly genuine/hypothetical
**rhetorical**    question_rate > 0.15, mostly rhetorical
**declarative**   question_rate < 0.05, few questions overall
**mixed**         moderate question_rate with diverse types
================  =====================================================

Sliding window analysis tracks how questioning evolves:

- **deepening** — question_rate increasing over windows
- **stable**    — question_rate roughly constant
- **closing**   — question_rate decreasing (writer converging on answers)

Edge cases
----------
* Empty input → zeroed report.
* Strokes with no sentences → no questions, rate = 0.
* Questions embedded in code blocks → still detected (this is a
  feature: even code comments with ``?`` reflect questioning).

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 733, 2026-11-19.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HYPOTHETICAL_STARTERS = (
    "what if",
    "suppose",
    "imagine",
    "assume",
    "pretend",
    "let's say",
    "lets say",
    "consider what",
    "consider if",
)

_HYPOTHETICAL_CONTAINS = (
    "would happen",
    "could we",
    "might we",
    "should we",
    "were to",
    "what would",
    "how would",
)

_RHETORICAL_STARTERS = (
    "who cares",
    "what does it matter",
    "why bother",
    "how hard can",
    "what could go wrong",
    "who asked",
    "so what",
)

_RHETORICAL_CONTAINS = (
    "really",
    "seriously",
    "obviously",
    "isn't that",
    "doesn't everyone",
    "don't we all",
    "of course",
)

_TAG_PATTERNS = (
    r"isn't it\?$",
    r"isn't that\?$",
    r"doesn't it\?$",
    r"don't you think\?$",
    r"won't we\?$",
    r"aren't they\?$",
    r"aren't we\?$",
    r"right\?$",
    r"no\?$",
    r"yeah\?$",
    r"huh\?$",
    r"innit\?$",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QuestionRecord:
    """One question found in a stroke."""

    text: str
    stroke_index: int
    qtype: str  # rhetorical | genuine | hypothetical | tag | other
    word_count: int = 0


@dataclass
class StrokeQuestionReport:
    """Per-stroke question analysis."""

    stroke_index: int
    sentence_count: int = 0
    question_count: int = 0
    question_rate: float = 0.0  # questions per sentence
    questions: List[QuestionRecord] = field(default_factory=list)
    dominant_type: str = "none"


@dataclass
class StreamQuestionReport:
    """Aggregate report for an entire stroke stream."""

    total_strokes: int = 0
    total_sentences: int = 0
    total_questions: int = 0
    question_rate: float = 0.0
    question_density: float = 0.0  # fraction of strokes with ≥ 1 question
    type_distribution: Dict[str, float] = field(default_factory=dict)
    style: str = "declarative"
    stroke_reports: List[StrokeQuestionReport] = field(default_factory=list)


@dataclass
class WindowQuestionReport:
    """Question analysis over a sliding window."""

    window_index: int
    start_stroke: int
    end_stroke: int
    question_rate: float = 0.0
    question_density: float = 0.0
    dominant_type: str = "none"
    type_distribution: Dict[str, float] = field(default_factory=dict)


@dataclass
class EvolutionReport:
    """How questioning evolves across windows."""

    windows: List[WindowQuestionReport] = field(default_factory=list)
    trend: str = "stable"  # deepening | stable | closing
    rate_delta: float = 0.0  # last window rate - first window rate


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]*")


def split_sentences(text: str) -> List[str]:
    """Split text into sentences on ``.!?`` boundaries."""
    if not text or not text.strip():
        return []
    parts = _SENTENCE_RE.findall(text.strip())
    return [p.strip() for p in parts if p.strip()]


def tokenise(text: str) -> List[str]:
    """Lowercase tokenise, stripping punctuation."""
    return re.findall(r"[a-z']+", text.lower())


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _is_question(sentence: str) -> bool:
    """Return True if the sentence ends with ``?``."""
    return sentence.rstrip().endswith("?")


def classify_question(sentence: str) -> str:
    """Classify a question sentence into a type.

    Returns one of: ``rhetorical``, ``genuine``, ``hypothetical``,
    ``tag``, ``other``.
    """
    lower = sentence.lower().strip()

    # Tag questions first (most specific pattern).
    for pat in _TAG_PATTERNS:
        if re.search(pat, lower):
            return "tag"

    # Hypothetical: check starters and contained phrases.
    for starter in _HYPOTHETICAL_STARTERS:
        if lower.startswith(starter):
            return "hypothetical"
    for phrase in _HYPOTHETICAL_CONTAINS:
        if phrase in lower:
            return "hypothetical"

    # Rhetorical: short questions with known rhetorical markers.
    words = tokenise(sentence)
    word_count = len(words)

    for starter in _RHETORICAL_STARTERS:
        if lower.startswith(starter):
            if word_count < 8:
                return "rhetorical"
    for phrase in _RHETORICAL_CONTAINS:
        if phrase in lower:
            if word_count < 8:
                return "rhetorical"

    # Genuine: everything else.
    return "genuine"


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyse_stroke(text: str, stroke_index: int = 0) -> StrokeQuestionReport:
    """Analyse questions in a single stroke."""
    sentences = split_sentences(text)
    if not sentences:
        return StrokeQuestionReport(stroke_index=stroke_index)

    questions: List[QuestionRecord] = []
    for sent in sentences:
        if _is_question(sent):
            qtype = classify_question(sent)
            wc = len(tokenise(sent))
            questions.append(
                QuestionRecord(
                    text=sent,
                    stroke_index=stroke_index,
                    qtype=qtype,
                    word_count=wc,
                )
            )

    sentence_count = len(sentences)
    question_count = len(questions)
    question_rate = question_count / sentence_count if sentence_count else 0.0

    # Dominant type.
    if questions:
        type_counts: Dict[str, int] = {}
        for q in questions:
            type_counts[q.qtype] = type_counts.get(q.qtype, 0) + 1
        dominant_type = max(type_counts, key=lambda k: type_counts[k])
    else:
        dominant_type = "none"

    return StrokeQuestionReport(
        stroke_index=stroke_index,
        sentence_count=sentence_count,
        question_count=question_count,
        question_rate=round(question_rate, 4),
        questions=questions,
        dominant_type=dominant_type,
    )


# ---------------------------------------------------------------------------
# Stream analysis
# ---------------------------------------------------------------------------


def analyse_stream(strokes: Sequence[str]) -> StreamQuestionReport:
    """Analyse questions across an entire stroke stream."""
    if not strokes:
        return StreamQuestionReport()

    stroke_reports: List[StrokeQuestionReport] = []
    total_sentences = 0
    total_questions = 0
    strokes_with_questions = 0
    all_types: Dict[str, int] = {}

    for idx, text in enumerate(strokes):
        rpt = analyse_stroke(text, stroke_index=idx)
        stroke_reports.append(rpt)
        total_sentences += rpt.sentence_count
        total_questions += rpt.question_count
        if rpt.question_count > 0:
            strokes_with_questions += 1
        for q in rpt.questions:
            all_types[q.qtype] = all_types.get(q.qtype, 0) + 1

    n = len(strokes)
    question_rate = (
        total_questions / total_sentences if total_sentences else 0.0
    )
    question_density = strokes_with_questions / n if n else 0.0

    # Type distribution (normalised).
    type_distribution: Dict[str, float] = {}
    if total_questions:
        for t, c in sorted(all_types.items()):
            type_distribution[t] = round(c / total_questions, 4)

    style = _classify_style(question_rate, type_distribution)

    return StreamQuestionReport(
        total_strokes=n,
        total_sentences=total_sentences,
        total_questions=total_questions,
        question_rate=round(question_rate, 4),
        question_density=round(question_density, 4),
        type_distribution=type_distribution,
        style=style,
        stroke_reports=stroke_reports,
    )


def _classify_style(
    rate: float, dist: Dict[str, float]
) -> str:
    """Classify the overall questioning style."""
    if rate < 0.05:
        return "declarative"

    # Check for predominantly rhetorical.
    rhet_frac = dist.get("rhetorical", 0.0)
    if rate > 0.15 and rhet_frac > 0.5:
        return "rhetorical"

    # Check for exploratory.
    genuine_frac = dist.get("genuine", 0.0)
    hypo_frac = dist.get("hypothetical", 0.0)
    if rate > 0.25 and (genuine_frac + hypo_frac) > 0.6:
        return "exploratory"

    # Moderate rate with mixed types.
    if rate >= 0.05:
        unique_types = sum(1 for v in dist.values() if v > 0.05)
        if unique_types >= 2:
            return "mixed"

    return "declarative"


# ---------------------------------------------------------------------------
# Sliding window analysis
# ---------------------------------------------------------------------------


def analyse_windows(
    strokes: Sequence[str],
    window_size: int = 50,
    step: int = 25,
) -> EvolutionReport:
    """Analyse questioning evolution via sliding windows."""
    if not strokes:
        return EvolutionReport()

    n = len(strokes)
    windows: List[WindowQuestionReport] = []
    wi = 0

    for start in range(0, n, step):
        end = min(start + window_size, n)
        if end - start < 3:
            break

        chunk = strokes[start:end]
        total_sents = 0
        total_qs = 0
        strokes_with_q = 0
        type_counts: Dict[str, int] = {}

        for local_idx, text in enumerate(chunk):
            rpt = analyse_stroke(text, stroke_index=start + local_idx)
            total_sents += rpt.sentence_count
            total_qs += rpt.question_count
            if rpt.question_count > 0:
                strokes_with_q += 1
            for q in rpt.questions:
                type_counts[q.qtype] = type_counts.get(q.qtype, 0) + 1

        w_rate = total_qs / total_sents if total_sents else 0.0
        w_density = strokes_with_q / len(chunk) if chunk else 0.0

        if type_counts:
            dom = max(type_counts, key=lambda k: type_counts[k])
            td = {
                t: round(c / sum(type_counts.values()), 4)
                for t, c in sorted(type_counts.items())
            }
        else:
            dom = "none"
            td = {}

        windows.append(
            WindowQuestionReport(
                window_index=wi,
                start_stroke=start,
                end_stroke=end,
                question_rate=round(w_rate, 4),
                question_density=round(w_density, 4),
                dominant_type=dom,
                type_distribution=td,
            )
        )
        wi += 1

        if end >= n:
            break

    # Trend detection.
    if len(windows) >= 2:
        rate_delta = windows[-1].question_rate - windows[0].question_rate
        if rate_delta > 0.05:
            trend = "deepening"
        elif rate_delta < -0.05:
            trend = "closing"
        else:
            trend = "stable"
    else:
        rate_delta = 0.0
        trend = "stable"

    return EvolutionReport(
        windows=windows,
        trend=trend,
        rate_delta=round(rate_delta, 4),
    )
