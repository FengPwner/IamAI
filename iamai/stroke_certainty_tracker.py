"""Stroke certainty tracker — measure how definite the writer sounds.

``stroke_question_tracker`` captures how the writer *asks*.
``stroke_transition_tracker`` captures how ideas *connect*.
Neither captures a subtler epistemic dimension: **how certain does the
writer sound about what they're saying?**

Certainty is not truth — a confident sentence can be wrong and a
hedged one can be right.  But tracking certainty reveals the writer's
*relationship to their own claims*:

* **Definitive** language ("clearly", "this proves", "the answer is")
  signals finished thinking — the writer has reached a conclusion.
* **Tentative** language ("perhaps", "it seems", "might be") signals
  active uncertainty — the writer is still working it out.
* **Exploratory** language ("let's see", "consider", "suppose") signals
  deliberate investigation — the writer is probing possibilities.
* **Revising** language ("actually", "wait", "no —", "rather") signals
  self-correction — the writer is changing their mind in real time.

Tracking certainty over the stroke stream reveals:

* Whether the writer is in **conclusion mode** (high certainty) or
  **thinking mode** (low certainty, high exploration).
* How certainty evolves — does the stream start tentative and converge
  to conclusions, or start confident and unravel?
* The *epistemic rhythm* — alternating between exploration and
  resolution is a sign of healthy intellectual process.

Data model
----------

A **CertaintyMarker** records one linguistic signal:

================  =====================================================
field             meaning
================  =====================================================
``text``          the marker word or phrase found
``kind``          definitive / tentative / exploratory / revising
``position``      character offset within the sentence
``stroke_index``  index of the containing stroke
================  =====================================================

Algorithm
---------
1. For each stroke, split into sentences on ``.!?`` boundaries.
2. Scan each sentence for certainty markers — words and phrases from
   four predefined lexicons.
3. Classify each sentence's **dominant stance** by counting markers:

   - The stance with the most markers wins.
   - Ties break in priority order: revising > exploratory > tentative >
     definitive (revision and exploration are rarer and more signal-rich).
   - Sentences with zero markers are classified as **neutral**.

4. Aggregate into per-stroke and per-stream metrics:

   - ``certainty_score`` — (definitive − tentative) / total markers,
     range [−1, +1].  Positive = confident, negative = uncertain.
   - ``stance_distribution`` — fraction of sentences in each stance.
   - ``marker_density`` — total markers per sentence.

5. Classify the overall writing posture:

================  =====================================================
posture           description
================  =====================================================
**authoritative** certainty_score > 0.4, mostly definitive
**deliberative**  certainty_score in [−0.2, 0.2], mixed stances
**speculative**   certainty_score < −0.2, mostly tentative/exploratory
**self-correcting** revising fraction > 0.15, active revision
================  =====================================================

Sliding window analysis tracks how certainty evolves:

* **converging** — certainty increasing over time (thinking → conclusions)
* **diverging** — certainty decreasing (confidence → doubt)
* **oscillating** — alternating between exploration and resolution
* **flat** — certainty roughly constant

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 735, 2026-11-20.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Marker lexicons
# ---------------------------------------------------------------------------

_DEFINITIVE_MARKERS = frozenset({
    "clearly", "obviously", "certainly", "definitely", "undoubtedly",
    "without doubt", "of course", "the fact is", "it is clear",
    "it is obvious", "this proves", "this shows", "the answer is",
    "there is no", "unquestionably", "indisputable", "inevitable",
    "precisely", "exactly", "absolutely", "categorically",
    "fundamentally", "in fact", "in reality", "the truth is",
    "it follows that", "necessarily", "conclusively", "unequivocal",
    "manifestly", "patently", "incontrovertibly", "decidedly",
})

_TENTATIVE_MARKERS = frozenset({
    "perhaps", "maybe", "possibly", "probably", "might", "may",
    "could be", "it seems", "it appears", "apparently", "somewhat",
    "rather", "quite", "fairly", "to some extent", "in a way",
    "it is likely", "it is possible", "one might", "arguably",
    "presumably", "seemingly", "supposedly", "ostensibly",
    "not entirely", "not quite", "not exactly", "hardly",
    "barely", "scarcely", "sort of", "kind of", "a bit",
    "to a degree", "in some sense", "loosely",
})

_EXPLORATORY_MARKERS = frozenset({
    "let us see", "let's see", "consider", "suppose", "imagine",
    "what if", "assume", "pretend", "hypothesise", "hypothesize",
    "for the sake of argument", "as a thought experiment",
    "exploring the idea", "to explore", "to investigate",
    "let us try", "let's try", "we could try", "one approach",
    "an alternative", "another possibility", "what happens when",
    "what would happen", "could we", "might we", "shall we",
    "wonder if", "curious whether", "open question",
})

_REVISING_MARKERS = frozenset({
    "actually", "wait", "no —", "on second thought",
    "on reflection", "rather", "instead", "correction",
    "i was wrong", "not quite right", "scratch that",
    "forget that", "strike that", "to be precise",
    "or rather", "more accurately", "better yet",
    "in other words", "put differently", "that is",
    "to clarify", "let me rephrase", "what i mean is",
    "not that", "i take it back", "revision",
    "rethinking", "revised", "updated view",
})

# Compile all markers into a single regex for efficient scanning.
# Sort longest-first so multi-word markers match before substrings.
_ALL_MARKERS: List[Tuple[str, str]] = []
for _m in _DEFINITIVE_MARKERS:
    _ALL_MARKERS.append((_m, "definitive"))
for _m in _TENTATIVE_MARKERS:
    _ALL_MARKERS.append((_m, "tentative"))
for _m in _EXPLORATORY_MARKERS:
    _ALL_MARKERS.append((_m, "exploratory"))
for _m in _REVISING_MARKERS:
    _ALL_MARKERS.append((_m, "revising"))

_ALL_MARKERS.sort(key=lambda x: -len(x[0]))

_MARKER_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m, _ in _ALL_MARKERS) + r")\b",
    re.IGNORECASE,
)

_MARKER_LOOKUP: Dict[str, str] = {m: k for m, k in _ALL_MARKERS}

# Default window size for sliding analysis.
_DEFAULT_WINDOW_SIZE = 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CertaintyMarker:
    """One linguistic signal found in the text."""

    text: str
    kind: str  # definitive / tentative / exploratory / revising
    position: int = 0
    stroke_index: int = 0


@dataclass
class SentenceStance:
    """Classification of one sentence's argumentative stance."""

    text: str
    stance: str  # definitive / tentative / exploratory / revising / neutral
    markers: List[CertaintyMarker] = field(default_factory=list)
    stroke_index: int = 0


@dataclass
class StrokeCertaintyReport:
    """Certainty analysis for a single stroke."""

    stroke_index: int = 0
    total_sentences: int = 0
    stance_counts: Dict[str, int] = field(default_factory=dict)
    dominant_stance: str = "neutral"
    certainty_score: float = 0.0
    marker_density: float = 0.0
    sentences: List[SentenceStance] = field(default_factory=list)


@dataclass
class WindowCertaintyReport:
    """Certainty analysis for one sliding window."""

    window_index: int = 0
    start_stroke: int = 0
    end_stroke: int = 0
    certainty_score: float = 0.0
    marker_density: float = 0.0
    dominant_stance: str = "neutral"
    stance_distribution: Dict[str, float] = field(default_factory=dict)


@dataclass
class EvolutionReport:
    """How certainty evolves across the stroke stream."""

    windows: List[WindowCertaintyReport] = field(default_factory=list)
    trend: str = "flat"  # converging / diverging / oscillating / flat
    score_delta: float = 0.0


@dataclass
class StreamCertaintyReport:
    """Overall certainty analysis for the entire stroke stream."""

    total_strokes: int = 0
    total_sentences: int = 0
    total_markers: int = 0
    certainty_score: float = 0.0
    marker_density: float = 0.0
    posture: str = "deliberative"
    stance_distribution: Dict[str, float] = field(default_factory=dict)
    dominant_stance: str = "neutral"
    evolution: EvolutionReport = field(default_factory=EvolutionReport)


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences on ``.!?`` boundaries.

    Consecutive whitespace is collapsed.  Empty fragments are dropped.
    """
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Tokenisation helper
# ---------------------------------------------------------------------------


def tokenise(text: str) -> List[str]:
    """Lowercase tokenise, stripping punctuation."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text.split()


# ---------------------------------------------------------------------------
# Marker detection
# ---------------------------------------------------------------------------


def find_markers(
    text: str,
    stroke_index: int = 0,
) -> List[CertaintyMarker]:
    """Find all certainty markers in *text*."""
    markers: List[CertaintyMarker] = []
    lower = text.lower()
    for match in _MARKER_PATTERN.finditer(lower):
        raw = match.group()
        kind = _MARKER_LOOKUP.get(raw, "definitive")
        markers.append(
            CertaintyMarker(
                text=raw,
                kind=kind,
                position=match.start(),
                stroke_index=stroke_index,
            )
        )
    return markers


# ---------------------------------------------------------------------------
# Sentence-level classification
# ---------------------------------------------------------------------------


_STANCE_PRIORITY = {
    "revising": 4,
    "exploratory": 3,
    "tentative": 2,
    "definitive": 1,
    "neutral": 0,
}


def classify_sentence(
    text: str,
    stroke_index: int = 0,
) -> SentenceStance:
    """Classify one sentence's argumentative stance."""
    markers = find_markers(text, stroke_index=stroke_index)

    if not markers:
        return SentenceStance(
            text=text,
            stance="neutral",
            markers=[],
            stroke_index=stroke_index,
        )

    counts: Dict[str, int] = {}
    for m in markers:
        counts[m.kind] = counts.get(m.kind, 0) + 1

    max_count = max(counts.values())
    tied = [k for k, v in counts.items() if v == max_count]

    if len(tied) == 1:
        stance = tied[0]
    else:
        stance = max(tied, key=lambda k: _STANCE_PRIORITY.get(k, 0))

    return SentenceStance(
        text=text,
        stance=stance,
        markers=markers,
        stroke_index=stroke_index,
    )


# ---------------------------------------------------------------------------
# Stroke-level analysis
# ---------------------------------------------------------------------------


def analyse_stroke(
    text: str,
    stroke_index: int = 0,
) -> StrokeCertaintyReport:
    """Analyse certainty for a single stroke."""
    sentences = split_sentences(text)
    if not sentences:
        return StrokeCertaintyReport(stroke_index=stroke_index)

    stances: List[SentenceStance] = []
    for sent in sentences:
        stances.append(classify_sentence(sent, stroke_index=stroke_index))

    stance_counts: Dict[str, int] = {}
    total_markers = 0
    for s in stances:
        stance_counts[s.stance] = stance_counts.get(s.stance, 0) + 1
        total_markers += len(s.markers)

    # Dominant stance (excluding neutral for dominance if possible).
    non_neutral = {k: v for k, v in stance_counts.items() if k != "neutral"}
    if non_neutral:
        dominant = max(non_neutral, key=lambda k: non_neutral[k])
    else:
        dominant = "neutral"

    # Certainty score: (definitive - tentative) / total_markers.
    def_count = stance_counts.get("definitive", 0)
    tent_count = stance_counts.get("tentative", 0)
    if total_markers > 0:
        score = (def_count - tent_count) / total_markers
    else:
        score = 0.0

    density = total_markers / len(sentences) if sentences else 0.0

    return StrokeCertaintyReport(
        stroke_index=stroke_index,
        total_sentences=len(sentences),
        stance_counts=stance_counts,
        dominant_stance=dominant,
        certainty_score=round(score, 4),
        marker_density=round(density, 4),
        sentences=stances,
    )


# ---------------------------------------------------------------------------
# Stream-level analysis
# ---------------------------------------------------------------------------


def _classify_posture(
    score: float,
    dist: Dict[str, float],
) -> str:
    """Classify overall writing posture from score and distribution."""
    revising_frac = dist.get("revising", 0.0)
    if revising_frac > 0.15:
        return "self-correcting"
    if score > 0.4:
        return "authoritative"
    if score < -0.2:
        return "speculative"
    return "deliberative"


def analyse_stream(
    strokes: Sequence[str],
    window_size: int = _DEFAULT_WINDOW_SIZE,
    step: int = 25,
) -> StreamCertaintyReport:
    """Analyse certainty across the entire stroke stream."""
    if not strokes:
        return StreamCertaintyReport()

    total_sentences = 0
    total_markers = 0
    all_stance_counts: Dict[str, int] = {}

    for idx, text in enumerate(strokes):
        rpt = analyse_stroke(text, stroke_index=idx)
        total_sentences += rpt.total_sentences
        total_markers += sum(len(s.markers) for s in rpt.sentences)
        for stance, count in rpt.stance_counts.items():
            all_stance_counts[stance] = all_stance_counts.get(stance, 0) + count

    # Distribution.
    total_classified = sum(all_stance_counts.values())
    dist: Dict[str, float] = {}
    if total_classified:
        for stance in sorted(all_stance_counts):
            dist[stance] = round(all_stance_counts[stance] / total_classified, 4)

    # Dominant stance.
    non_neutral = {k: v for k, v in all_stance_counts.items() if k != "neutral"}
    if non_neutral:
        dominant = max(non_neutral, key=lambda k: non_neutral[k])
    else:
        dominant = "neutral"

    # Certainty score.
    def_count = all_stance_counts.get("definitive", 0)
    tent_count = all_stance_counts.get("tentative", 0)
    if total_markers > 0:
        score = (def_count - tent_count) / total_markers
    else:
        score = 0.0

    density = total_markers / total_sentences if total_sentences else 0.0
    posture = _classify_posture(score, dist)
    evo = analyse_windows(strokes, window_size=window_size, step=step)

    return StreamCertaintyReport(
        total_strokes=len(strokes),
        total_sentences=total_sentences,
        total_markers=total_markers,
        certainty_score=round(score, 4),
        marker_density=round(density, 4),
        posture=posture,
        stance_distribution=dist,
        dominant_stance=dominant,
        evolution=evo,
    )


# ---------------------------------------------------------------------------
# Sliding window analysis
# ---------------------------------------------------------------------------


def analyse_windows(
    strokes: Sequence[str],
    window_size: int = _DEFAULT_WINDOW_SIZE,
    step: int = 25,
) -> EvolutionReport:
    """Analyse certainty evolution via sliding windows."""
    if not strokes:
        return EvolutionReport()

    n = len(strokes)
    windows: List[WindowCertaintyReport] = []
    wi = 0

    for start in range(0, n, step):
        end = min(start + window_size, n)
        if end - start < 3:
            break

        chunk = strokes[start:end]
        w_total_sentences = 0
        w_total_markers = 0
        w_stance_counts: Dict[str, int] = {}

        for local_idx, text in enumerate(chunk):
            rpt = analyse_stroke(text, stroke_index=start + local_idx)
            w_total_sentences += rpt.total_sentences
            w_total_markers += sum(len(s.markers) for s in rpt.sentences)
            for stance, count in rpt.stance_counts.items():
                w_stance_counts[stance] = w_stance_counts.get(stance, 0) + count

        # Window score.
        w_def = w_stance_counts.get("definitive", 0)
        w_tent = w_stance_counts.get("tentative", 0)
        if w_total_markers > 0:
            w_score = (w_def - w_tent) / w_total_markers
        else:
            w_score = 0.0

        w_density = w_total_markers / w_total_sentences if w_total_sentences else 0.0

        # Window distribution.
        w_total_classified = sum(w_stance_counts.values())
        w_dist: Dict[str, float] = {}
        if w_total_classified:
            for stance in sorted(w_stance_counts):
                w_dist[stance] = round(
                    w_stance_counts[stance] / w_total_classified, 4
                )

        # Window dominant stance.
        w_non_neutral = {k: v for k, v in w_stance_counts.items() if k != "neutral"}
        if w_non_neutral:
            w_dominant = max(w_non_neutral, key=lambda k: w_non_neutral[k])
        else:
            w_dominant = "neutral"

        windows.append(
            WindowCertaintyReport(
                window_index=wi,
                start_stroke=start,
                end_stroke=end,
                certainty_score=round(w_score, 4),
                marker_density=round(w_density, 4),
                dominant_stance=w_dominant,
                stance_distribution=w_dist,
            )
        )
        wi += 1

        if end >= n:
            break

    # Trend detection.
    if len(windows) >= 3:
        scores = [w.certainty_score for w in windows]
        first_half = scores[: len(scores) // 2]
        second_half = scores[len(scores) // 2 :]
        avg_first = sum(first_half) / len(first_half) if first_half else 0.0
        avg_second = sum(second_half) / len(second_half) if second_half else 0.0
        delta = avg_second - avg_first

        # Check for oscillation: count sign changes.
        sign_changes = 0
        for i in range(1, len(scores)):
            if (scores[i] - scores[i - 1]) * (scores[i - 1] - scores[i - 2] if i >= 2 else 1) < 0:
                sign_changes += 1

        if sign_changes >= len(scores) - 2 and len(scores) >= 4:
            trend = "oscillating"
        elif delta > 0.1:
            trend = "converging"
        elif delta < -0.1:
            trend = "diverging"
        else:
            trend = "flat"
    elif len(windows) == 2:
        delta = windows[-1].certainty_score - windows[0].certainty_score
        if delta > 0.1:
            trend = "converging"
        elif delta < -0.1:
            trend = "diverging"
        else:
            trend = "flat"
    else:
        delta = 0.0
        trend = "flat"

    return EvolutionReport(
        windows=windows,
        trend=trend,
        score_delta=round(delta, 4),
    )
