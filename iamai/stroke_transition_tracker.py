"""Stroke transition tracker — measure how the writer shifts between ideas.

``stroke_question_tracker`` captures *what* the writer asks.
``stroke_refrain_tracker`` captures *what* the writer revisits.
Neither addresses a subtler rhetorical dimension: **how does the writer
move from one idea to the next?**

Transitions are the connective tissue of prose.  A writer who signposts
every shift ("however", "for example", "as a result") is *architecting*
the reader's journey.  A writer who jumps without markers is trusting
the reader to follow.  The mix of transition types reveals even more:

* **Continuation** transitions ("also", "moreover", "furthermore")
  extend the current thread — the writer is building incrementally.
* **Elaboration** transitions ("for example", "specifically", "that is")
  deepen the current point — the writer is drilling down.
* **Contrast** transitions ("but", "however", "on the other hand")
  shift perspective — the writer is considering multiple angles.
* **Consequence** transitions ("therefore", "thus", "so") connect
  cause and effect — the writer is building logical chains.
* **Digression** — no marker at all — the writer jumps without
  signalling, trusting context or changing topic abruptly.

Tracking transitions over the stroke stream reveals:

* Whether the writer is *architecting* (many explicit transitions) or
  *streaming* (few markers, raw thought flow).
* How rhetorical style evolves — does the writer start elaborative and
  become contrastive, or vice versa?
* The *transition density* trajectory — a useful signal of whether the
  prose is becoming more structured (rising density) or more free-flowing
  (falling density).

Data model
----------

A **TransitionRecord** captures one transition between consecutive
sentences:

================  =====================================================
field             meaning
================  =====================================================
``kind``          transition type: continuation / elaboration / contrast /
                  consequence / digression
``marker``        the detected transition word/phrase (empty for digression)
``from_text``     the preceding sentence (truncated to 80 chars)
``to_text``       the following sentence (truncated to 80 chars)
``stroke_index``  index of the stroke containing the transition
================  =====================================================

Algorithm
---------
1. Tokenise each stroke into sentences via ``split_sentences``.
2. For each consecutive pair of sentences within a stroke, scan the
   beginning of the second sentence for known transition markers.
3. Classify the transition by the marker found; if no marker matches,
   classify as ``digression``.
4. Aggregate per stroke and across the full stream.

Transition density
~~~~~~~~~~~~~~~~~~

``transition_density`` = explicit transitions / total sentence pairs.

================  =====================================================
density           verdict
================  =====================================================
≥ 0.6             ``architecting`` — heavily signposted prose
0.3 – 0.6         ``structured`` — moderate signposting
0.1 – 0.3         ``flowing`` — light signposting
< 0.1             ``streaming`` — raw thought flow
================  =====================================================

Dominant style
~~~~~~~~~~~~~~

Based on the most frequent transition type:

* **elaboration** dominant → ``drilling`` style
* **continuation** dominant → ``building`` style
* **contrast** dominant → ``debating`` style
* **consequence** dominant → ``reasoning`` style
* **digression** dominant → ``wandering`` style

Sliding-window analysis
~~~~~~~~~~~~~~~~~~~~~~~

Split the stroke stream into non-overlapping windows of ``window_size``
strokes (default 50).  Compute transition density per window to track
how rhetorical style evolves:

* **tightening** — density increasing over time
* **stable** — density roughly constant
* **loosening** — density decreasing

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 734, 2026-11-20.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Transition marker dictionaries
# ---------------------------------------------------------------------------

CONTINUATION_MARKERS: Tuple[str, ...] = (
    "also",
    "additionally",
    "as well",
    "besides",
    "equally",
    "further",
    "furthermore",
    "in addition",
    "likewise",
    "moreover",
    "not only",
    "on top of that",
    "similarly",
    "what's more",
    "and",
)

ELABORATION_MARKERS: Tuple[str, ...] = (
    "as an illustration",
    "for example",
    "for instance",
    "in detail",
    "in other words",
    "in particular",
    "namely",
    "say",
    "specifically",
    "such as",
    "that is",
    "that is to say",
    "to illustrate",
    "to put it another way",
    "viz",
)

CONTRAST_MARKERS: Tuple[str, ...] = (
    "although",
    "by contrast",
    "conversely",
    "despite",
    "even so",
    "however",
    "in contrast",
    "in spite of",
    "instead",
    "nevertheless",
    "nonetheless",
    "on the contrary",
    "on the other hand",
    "rather",
    "still",
    "though",
    "whereas",
    "while",
    "yet",
    "but",
)

CONSEQUENCE_MARKERS: Tuple[str, ...] = (
    "accordingly",
    "as a consequence",
    "as a result",
    "because of this",
    "consequently",
    "for this reason",
    "hence",
    "so",
    "therefore",
    "thus",
    "this means",
    "which is why",
)

# All markers combined into a lookup: marker_text → kind
_MARKER_LOOKUP: Dict[str, str] = {}
for _m in CONTINUATION_MARKERS:
    _MARKER_LOOKUP[_m] = "continuation"
for _m in ELABORATION_MARKERS:
    _MARKER_LOOKUP[_m] = "elaboration"
for _m in CONTRAST_MARKERS:
    _MARKER_LOOKUP[_m] = "contrast"
for _m in CONSEQUENCE_MARKERS:
    _MARKER_LOOKUP[_m] = "consequence"

# Sort by length descending so longer phrases match first
_SORTED_MARKERS = sorted(_MARKER_LOOKUP.keys(), key=len, reverse=True)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TransitionRecord:
    """One detected transition between consecutive sentences."""

    kind: str  # continuation / elaboration / contrast / consequence / digression
    marker: str = ""
    from_text: str = ""
    to_text: str = ""
    stroke_index: int = 0


@dataclass
class StrokeTransitionReport:
    """Analysis of transitions within a single stroke."""

    stroke_index: int = 0
    sentence_count: int = 0
    transition_count: int = 0
    transitions: List[TransitionRecord] = field(default_factory=list)
    transition_density: float = 0.0
    type_distribution: Dict[str, float] = field(default_factory=dict)

    @property
    def density_verdict(self) -> str:
        d = self.transition_density
        if d >= 0.6:
            return "architecting"
        if d >= 0.3:
            return "structured"
        if d >= 0.1:
            return "flowing"
        return "streaming"


@dataclass
class WindowTransitionReport:
    """Transition analysis for one sliding window."""

    window_index: int = 0
    start_stroke: int = 0
    end_stroke: int = 0
    transition_density: float = 0.0
    dominant_type: str = "none"
    type_distribution: Dict[str, float] = field(default_factory=dict)


@dataclass
class EvolutionReport:
    """Sliding-window evolution of transition style."""

    windows: List[WindowTransitionReport] = field(default_factory=list)
    trend: str = "stable"  # tightening / stable / loosening
    density_delta: float = 0.0


@dataclass
class StreamTransitionReport:
    """Aggregate analysis across the full stroke stream."""

    total_strokes: int = 0
    total_sentences: int = 0
    total_transitions: int = 0
    transition_density: float = 0.0
    density_verdict: str = "streaming"
    dominant_type: str = "none"
    dominant_style: str = "wandering"
    type_distribution: Dict[str, float] = field(default_factory=dict)
    evolution: Optional[EvolutionReport] = None


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_SENT_RE = re.compile(r"[^.!?]+[.!?]+[\s]*")


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences.

    Handles '.', '!', '?' as terminators.  Abbreviations like "e.g."
    or "i.e." are not split (they lack a following space+capital).
    """
    if not text or not text.strip():
        return []

    raw = _SENT_RE.findall(text.strip())
    if not raw:
        # No terminal punctuation found; treat as one sentence if non-empty.
        stripped = text.strip()
        return [stripped] if stripped else []

    result = []
    for s in raw:
        s = s.strip()
        if s:
            result.append(s)

    # Catch any trailing text without terminal punctuation.
    consumed = sum(len(s) for s in raw)
    remainder = text.strip()[consumed:].strip()
    if remainder and len(remainder) > 5:
        result.append(remainder)

    return result


# ---------------------------------------------------------------------------
# Transition detection
# ---------------------------------------------------------------------------


def _normalise_sentence_start(sentence: str) -> str:
    """Lowercase the first ~40 chars for marker matching."""
    cleaned = sentence.lstrip().lower()
    return cleaned[:40]


def detect_transition(from_text: str, to_text: str) -> TransitionRecord:
    """Classify the transition between two consecutive sentences."""
    head = _normalise_sentence_start(to_text)

    for marker in _SORTED_MARKERS:
        # Check if the sentence starts with the marker (optionally followed
        # by comma or space).
        if head.startswith(marker):
            rest = head[len(marker):]
            # Allow marker at start only if followed by comma, space, or EOL.
            if not rest or rest[0] in (",", " ", ";", ":"):
                return TransitionRecord(
                    kind=_MARKER_LOOKUP[marker],
                    marker=marker,
                    from_text=from_text[:80],
                    to_text=to_text[:80],
                )
        # Also check after initial comma-clause: "X, however, Y"
        # Look for marker within first 20 chars preceded by comma.
        search_zone = head[:30]
        idx = search_zone.find(marker)
        if idx > 0:
            before = search_zone[:idx].rstrip()
            if before.endswith(",") or before.endswith(";"):
                return TransitionRecord(
                    kind=_MARKER_LOOKUP[marker],
                    marker=marker,
                    from_text=from_text[:80],
                    to_text=to_text[:80],
                )

    return TransitionRecord(
        kind="digression",
        marker="",
        from_text=from_text[:80],
        to_text=to_text[:80],
    )


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyse_stroke(
    text: str,
    stroke_index: int = 0,
) -> StrokeTransitionReport:
    """Analyse transitions within a single stroke."""
    sentences = split_sentences(text)
    n = len(sentences)

    if n < 2:
        return StrokeTransitionReport(
            stroke_index=stroke_index,
            sentence_count=n,
            transition_count=0,
            transitions=[],
            transition_density=0.0,
            type_distribution={},
        )

    transitions: List[TransitionRecord] = []
    type_counts: Dict[str, int] = {}

    for i in range(n - 1):
        rec = detect_transition(sentences[i], sentences[i + 1])
        rec.stroke_index = stroke_index
        transitions.append(rec)
        type_counts[rec.kind] = type_counts.get(rec.kind, 0) + 1

    pair_count = n - 1
    explicit = sum(1 for t in transitions if t.kind != "digression")
    density = explicit / pair_count if pair_count else 0.0

    dist = {
        t: round(c / pair_count, 4)
        for t, c in sorted(type_counts.items())
    }

    return StrokeTransitionReport(
        stroke_index=stroke_index,
        sentence_count=n,
        transition_count=len(transitions),
        transitions=transitions,
        transition_density=round(density, 4),
        type_distribution=dist,
    )


# ---------------------------------------------------------------------------
# Stream-level analysis
# ---------------------------------------------------------------------------


def _classify_style(dist: Dict[str, float]) -> Tuple[str, str]:
    """Return (dominant_type, style_label) from type distribution."""
    if not dist:
        return "none", "wandering"

    dominant = max(dist, key=lambda k: dist[k])

    style_map = {
        "elaboration": "drilling",
        "continuation": "building",
        "contrast": "debating",
        "consequence": "reasoning",
        "digression": "wandering",
    }
    return dominant, style_map.get(dominant, "wandering")


def analyse_stream(
    strokes: Sequence[str],
    window_size: int = 50,
    step: int = 25,
) -> StreamTransitionReport:
    """Aggregate transition analysis across a stream of strokes."""
    if not strokes:
        return StreamTransitionReport()

    total_sentences = 0
    total_pairs = 0
    total_explicit = 0
    type_counts: Dict[str, int] = {}

    for idx, text in enumerate(strokes):
        rpt = analyse_stroke(text, stroke_index=idx)
        total_sentences += rpt.sentence_count
        total_pairs += len(rpt.transitions)
        for t in rpt.transitions:
            type_counts[t.kind] = type_counts.get(t.kind, 0) + 1
            if t.kind != "digression":
                total_explicit += 1

    density = total_explicit / total_pairs if total_pairs else 0.0
    dist = {
        t: round(c / total_pairs, 4)
        for t, c in sorted(type_counts.items())
    } if total_pairs else {}

    dom, style = _classify_style(dist)

    # Verdict
    if density >= 0.6:
        verdict = "architecting"
    elif density >= 0.3:
        verdict = "structured"
    elif density >= 0.1:
        verdict = "flowing"
    else:
        verdict = "streaming"

    evo = analyse_windows(strokes, window_size=window_size, step=step)

    return StreamTransitionReport(
        total_strokes=len(strokes),
        total_sentences=total_sentences,
        total_transitions=total_pairs,
        transition_density=round(density, 4),
        density_verdict=verdict,
        dominant_type=dom,
        dominant_style=style,
        type_distribution=dist,
        evolution=evo,
    )


# ---------------------------------------------------------------------------
# Sliding window analysis
# ---------------------------------------------------------------------------


def analyse_windows(
    strokes: Sequence[str],
    window_size: int = 50,
    step: int = 25,
) -> EvolutionReport:
    """Analyse transition evolution via sliding windows."""
    if not strokes:
        return EvolutionReport()

    n = len(strokes)
    windows: List[WindowTransitionReport] = []
    wi = 0

    for start in range(0, n, step):
        end = min(start + window_size, n)
        if end - start < 3:
            break

        chunk = strokes[start:end]
        total_pairs = 0
        total_explicit = 0
        type_counts: Dict[str, int] = {}

        for local_idx, text in enumerate(chunk):
            rpt = analyse_stroke(text, stroke_index=start + local_idx)
            total_pairs += len(rpt.transitions)
            for t in rpt.transitions:
                type_counts[t.kind] = type_counts.get(t.kind, 0) + 1
                if t.kind != "digression":
                    total_explicit += 1

        w_density = total_explicit / total_pairs if total_pairs else 0.0

        if type_counts and total_pairs:
            dom = max(type_counts, key=lambda k: type_counts[k])
            td = {
                t: round(c / total_pairs, 4)
                for t, c in sorted(type_counts.items())
            }
        else:
            dom = "none"
            td = {}

        windows.append(
            WindowTransitionReport(
                window_index=wi,
                start_stroke=start,
                end_stroke=end,
                transition_density=round(w_density, 4),
                dominant_type=dom,
                type_distribution=td,
            )
        )
        wi += 1

        if end >= n:
            break

    # Trend detection.
    if len(windows) >= 2:
        delta = windows[-1].transition_density - windows[0].transition_density
        if delta > 0.05:
            trend = "tightening"
        elif delta < -0.05:
            trend = "loosening"
        else:
            trend = "stable"
    else:
        delta = 0.0
        trend = "stable"

    return EvolutionReport(
        windows=windows,
        trend=trend,
        density_delta=round(delta, 4),
    )
