#!/usr/bin/env python3
"""writer_subtext — measure the gap between what is said and what is meant.

Subtext is about *layers of meaning*.  A text with rich subtext says
one thing on the surface while implying another underneath.  The reader
must participate — filling gaps, reading between lines, detecting irony,
connecting what is stated to what is withheld.

A text with no subtext reads like a technical manual — every meaning is
explicit, nothing is implied, the surface is all there is.  A text with
strong subtext reads like Chekhov — a character says "the weather is
changing" and the reader understands that everything is about to fall
apart.  The surface is a door; the real meaning is in the next room.

This module is orthogonal to the other writer metrics:

- **tension** tracks *anticipation and forward pull*.  A text can have
  strong tension (cliffhangers, unresolved questions) while having no
  subtext (the unresolved questions are literal, not implied).  Tension
  is about the reader wanting to know *what happens next*; subtext is
  about the reader sensing *what is really happening now*.

- **coherence** tracks *logical flow*.  A text can be perfectly coherent
  (every statement follows from the last) while having no subtext (every
  statement means exactly what it says).  Coherence is about the chain
  of reasoning; subtext is about the shadow beneath the chain.

- **concision** tracks *economy of words*.  A text can be concise
  (no wasted words) while having no subtext (the efficient words are
  all literal).  Concision is about efficiency; subtext is about depth
  beneath the efficient surface.

- **specificity** tracks *detail and precision*.  A text can be highly
  specific (exact numbers, named entities, precise descriptions) while
  having no subtext (the specific details are all surface-level).
  Specificity is about the granularity of what is stated; subtext is
  about what is *not* stated.

- **restraint** tracks *what is held back*.  A text can show restraint
  (avoiding excess, knowing when to stop) while having no subtext
  (what is held back is simply omitted, not implied).  Restraint is
  about discipline; subtext is about implication.

Subtext asks: **does the text trust the reader to read between the lines?**

Four signals are tracked:

1. **Indirectness density** — the frequency of indirect speech acts per
   hundred words.  These include rhetorical questions (questions that
   assert rather than ask), hedged assertions ("one might argue",
   "it could be suggested"), litotes ("not unlike", "not without merit",
   "not exactly a failure"), and understatement markers ("somewhat",
   "rather", "a bit" applied to dramatic situations).  Higher density
   means more meaning is being conveyed indirectly.

2. **Irony markers** — signals that the literal meaning diverges from
   the intended meaning.  Includes explicit irony signals ("ironically",
   "of course" in contexts of failure, "naturally" preceding unexpected
   outcomes), sentiment inversion (positive words in negative contexts
   or vice versa), and hyperbolic mismatch (extreme language applied to
   trivial subjects).  Each marker indicates a layer beneath the surface.

3. **Gap density** — the frequency of deliberate omissions per hundred
   words.  Ellipses, dashes used for interruption or trailing off,
   aposiopesis (sentences that break off unfinished), loaded pauses
   (short sentences following long ones that signal withholding), and
   referential gaps (pronouns or demonstratives whose referent is
   deliberately vague: "they know what they did", "that thing",
   "you know what I mean").  Gaps invite the reader to fill in meaning.

4. **Show-vs-tell ratio** — the proportion of sensory/action language
   relative to evaluative/abstract language.  "She slammed the door and
   walked to the car without looking back" *shows* anger; "she was
   furious" *tells* it.  Showing creates subtext because the reader
   must infer the emotional state from the physical action.  Telling
   eliminates subtext by making the evaluation explicit.

From these signals a session-level **subtext_index** is computed
and classified:

==============  ============================================================
class           meaning
==============  ============================================================
layered         index >= 0.75 — rich subtext; the text operates on multiple
                levels simultaneously; the reader must actively interpret
                what lies beneath the surface
suggestive      0.55 <= index < 0.75 — moderate subtext; indirect language
                and implication are present; the text trusts the reader
                to connect dots
literal         0.35 <= index < 0.55 — mostly surface-level; meaning is
                stated directly with little implication; functional but
                flat
flat            0.20 <= index < 0.35 — almost no subtext; every statement
                means exactly what it says; the text reads like a manual
opaque          index < 0.20 — subtext is either absent or so buried that
                the text is impenetrable; either everything is explicit
                or the implications are incoherent
==============  ============================================================

Orthogonal to restraint (restraint = discipline of omission; subtext =
implication through omission), tension (tension = forward pull; subtext =
depth beneath the current surface), and specificity (specificity = detail
granularity; subtext = meaning beneath the detail).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants: indirect language patterns
# ---------------------------------------------------------------------------

# Rhetorical question patterns — questions that assert rather than ask
RHETORICAL_QUESTION_PATTERNS = [
    re.compile(r"\bisn't it (true|obvious|clear|apparent|evident)\b", re.I),
    re.compile(r"\bwho (would|could|should) (have|want|need)\b", re.I),
    re.compile(r"\bwhat (more|else|better|worse) could\b", re.I),
    re.compile(r"\bhow (could|would|can) (anyone|one|we|you|they)\b", re.I),
    re.compile(r"\bwhy (would|would anyone|bother|not)\b", re.I),
    re.compile(r"\bafter all,?\s", re.I),
    re.compile(r"\bneed (I|we|you|they) (say|remind|explain|elaborate)\b", re.I),
    re.compile(r"\bsuffice (it )?to say\b", re.I),
    re.compile(r"\bthe question (is|remains|becomes)\b", re.I),
    re.compile(r"\bone (has to|must|can only) (wonder|ask|imagine)\b", re.I),
]

# Hedged assertion patterns
HEDGE_PATTERNS = [
    re.compile(r"\bone might (argue|suggest|say|think|wonder|observe)\b", re.I),
    re.compile(r"\bit (could|might|may) be (argued|suggested|said|thought|noted)\b", re.I),
    re.compile(r"\bperhaps (it is|we should|one could|the most)\b", re.I),
    re.compile(r"\bit is (not hard|easy|tempting|possible) to (see|imagine|understand|argue)\b", re.I),
    re.compile(r"\barguably\b", re.I),
    re.compile(r"\bin a sense\b", re.I),
    re.compile(r"\bif you will\b", re.I),
    re.compile(r"\bso to speak\b", re.I),
    re.compile(r"\bas it were\b", re.I),
    re.compile(r"\bfor (better|worse) or (worse|better)\b", re.I),
]

# Litotes patterns — negation of the opposite
LITOTES_PATTERNS = [
    re.compile(r"\bnot (un\w+)\b", re.I),
    re.compile(r"\bnot (without|exactly|precisely|quite|entirely|altogether)\b", re.I),
    re.compile(r"\bnot (a|the) (small|insignificant|trivial|minor) (matter|thing|feat|accomplishment)\b", re.I),
    re.compile(r"\bnot (bad|half bad|too shabby)\b", re.I),
    re.compile(r"\bno (small|mean|slight|trivial) (feat|achievement|accomplishment|task)\b", re.I),
    re.compile(r"\bfar from (it|true|the case|over|done|clear)\b", re.I),
]

# Understatement markers — minimizers applied to significant events
UNDERSTATEMENT_MARKERS = [
    re.compile(r"\b(a bit|rather|somewhat|slightly|a little) (of a|an?)\b", re.I),
    re.compile(r"\bto (say the least|put it mildly|be generous|understate)\b", re.I),
    re.compile(r"\bmildly (put|interesting|surprising|concerning|amusing)\b", re.I),
    re.compile(r"\bnot (the end of|exactly|precisely)\b", re.I),
    re.compile(r"\ba (slight|minor|small|certain) (issue|problem|complication|matter)\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: irony markers
# ---------------------------------------------------------------------------

# Explicit irony signals
IRONY_SIGNALS = [
    re.compile(r"\bironically\b", re.I),
    re.compile(r"\bof course\b", re.I),
    re.compile(r"\bnaturally\b", re.I),
    re.compile(r"\bpredictably\b", re.I),
    re.compile(r"\bunsurprisingly\b", re.I),
    re.compile(r"\bas (expected|predicted|always|usual|ever)\b", re.I),
    re.compile(r"\bneedless to say\b", re.I),
    re.compile(r"\bgo figure\b", re.I),
    re.compile(r"\bwhat (a|an) (surprise|shock|wonder|delight|relief)\b", re.I),
    re.compile(r"\bfunny (how|enough)\b", re.I),
]

# Sentiment inversion patterns — positive words in negative contexts
# or negative words in positive contexts (simplified detection)
SENTIMENT_POSITIVE = re.compile(
    r"\b(wonderful|excellent|perfect|brilliant|outstanding|magnificent|"
    r"superb|fantastic|delightful|marvelous|glorious|splendid)\b",
    re.I,
)
SENTIMENT_NEGATIVE = re.compile(
    r"\b(terrible|awful|dreadful|disastrous|horrible|abysmal|atrocious|"
    r"appalling|catastrophic|devastating|pathetic|wretched)\b",
    re.I,
)

# Hyperbole markers — extreme language
HYPERBOLE_PATTERNS = [
    re.compile(r"\b(absolutely|completely|totally|utterly|entirely) (ridiculous|absurd|insane|impossible)\b", re.I),
    re.compile(r"\bthe (most|least|worst|best) (thing|idea|plan|decision|outcome) (ever|in history|imaginable)\b", re.I),
    re.compile(r"\b(literally|actually) (dying|dead|screaming|crying|exploding)\b", re.I),
    re.compile(r"\ba (million|billion|trillion|gazillion) (times|reasons|ways|things)\b", re.I),
    re.compile(r"\b(endless|infinite|countless) (hours|days|weeks|times)\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: gap/omission markers
# ---------------------------------------------------------------------------

# Ellipsis and trailing off
ELLIPSIS_PATTERN = re.compile(r"\.{2,}|…")
DASH_TRAILING = re.compile(r"——\s*$|—\s*$|---\s*$", re.M)
APOSiopesis = re.compile(r"[.!?]?\s*(and|but|if|when|because|although|while)\s*[.]{0,3}\s*$", re.M | re.I)

# Loaded pauses — very short sentences (≤ 5 words) following long ones (≥ 20 words)
# Detected at analysis time via sentence splitting

# Referential gaps — deliberately vague references
REFERENTIAL_GAP_PATTERNS = [
    re.compile(r"\b(they|you|we|one) (know|knew) (what|how)\b", re.I),
    re.compile(r"\bthat (thing|stuff|matter|business|affair)\b", re.I),
    re.compile(r"\byou know what (I|we) mean\b", re.I),
    re.compile(r"\bthe (usual|certain|particular) (reasons?|circumstances?|matters?)\b", re.I),
    re.compile(r"\bfor (obvious|clear|apparent) reasons?\b", re.I),
    re.compile(r"\bshall we say\b", re.I),
    re.compile(r"\blet's (just|not) (say|go there|get into)\b", re.I),
    re.compile(r"\bwithout (going into|getting into|naming|mentioning)\b", re.I),
    re.compile(r"\bcertain (people|parties|individuals|entities)\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: show vs tell
# ---------------------------------------------------------------------------

# Sensory / action language (showing)
SHOW_VERBS = re.compile(
    r"\b(walked|ran|slammed|opened|closed|pushed|pulled|threw|caught|"
    r"whispered|muttered|mumbled|shouted|screamed|gasped|sighed|laughed|"
    r"frowned|smiled|glared|stared|looked|turned|stepped|reached|"
    r"trembled|shook|clenched|gripped|tapped|drummed|paced|leaned|"
    r"slumped|straightened|nodded|shrugged|wiped|rubbed|pressed)\b",
    re.I,
)

# Evaluative / abstract language (telling)
TELL_WORDS = re.compile(
    r"\b(was|were|felt|seemed|appeared|became) (happy|sad|angry|furious|"
    r"delighted|terrified|anxious|nervous|excited|bored|frustrated|"
    r"pleased|disappointed|confused|confident|worried|relieved|guilty|"
    r"proud|ashamed|jealous|grateful|lonely|content|miserable|elated|"
    r"hopeful|desperate|overwhelmed|determined|resigned|indifferent)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words, stripping punctuation."""
    return [w.lower() for w in re.findall(r"[a-zA-Z']+", text)]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Handle common abbreviations before splitting
    cleaned = re.sub(r"(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc)\.", r"\1DOT", text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    return [s.replace("DOT", ".") for s in sentences if s.strip()]


def _get_stroke_text(stroke: dict[str, Any] | str) -> str:
    """Extract text from a stroke (string or dict)."""
    if isinstance(stroke, str):
        return stroke
    for key in ("text", "content", "body"):
        if key in stroke and isinstance(stroke[key], str):
            return stroke[key]
    return ""


def _count_pattern_matches(text: str, patterns: list[re.Pattern]) -> int:
    """Count total matches across a list of patterns."""
    total = 0
    for pat in patterns:
        total += len(pat.findall(text))
    return total


# ---------------------------------------------------------------------------
# Signal 1: Indirectness density
# ---------------------------------------------------------------------------


def compute_indirectness_density(text: str) -> dict[str, Any]:
    """Measure indirect speech acts per hundred words.

    Tracks rhetorical questions, hedged assertions, litotes, and
    understatement markers.

    Returns
    -------
    dict with keys:
        rhetorical_questions: int
        hedges: int
        litotes: int
        understatement: int
        total_indirect: int
        word_count: int
        density: float  (indirect acts per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    rhetorical = _count_pattern_matches(text, RHETORICAL_QUESTION_PATTERNS)
    hedges = _count_pattern_matches(text, HEDGE_PATTERNS)
    litotes = _count_pattern_matches(text, LITOTES_PATTERNS)
    understatement = _count_pattern_matches(text, UNDERSTATEMENT_MARKERS)

    total = rhetorical + hedges + litotes + understatement
    density = (total / word_count) * 100

    return {
        "rhetorical_questions": rhetorical,
        "hedges": hedges,
        "litotes": litotes,
        "understatement": understatement,
        "total_indirect": total,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Signal 2: Irony markers
# ---------------------------------------------------------------------------


def compute_irony_markers(text: str) -> dict[str, Any]:
    """Detect signals that literal meaning diverges from intended meaning.

    Tracks explicit irony signals, sentiment inversion contexts, and
    hyperbolic mismatch.

    Returns
    -------
    dict with keys:
        explicit_irony: int
        sentiment_inversions: int
        hyperbole: int
        total_irony: int
        word_count: int
        density: float  (irony markers per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    explicit = _count_pattern_matches(text, IRONY_SIGNALS)

    # Sentiment inversion: positive word near negative context or vice versa
    sentences = _split_sentences(text)
    inversions = 0
    for sent in sentences:
        has_pos = bool(SENTIMENT_POSITIVE.search(sent))
        has_neg = bool(SENTIMENT_NEGATIVE.search(sent))
        # Both sentiments in one short sentence suggests inversion
        if has_pos and has_neg:
            inversions += 1
        # Irony signal word + sentiment word suggests inversion
        if _count_pattern_matches(sent, IRONY_SIGNALS) > 0 and (has_pos or has_neg):
            inversions += 1

    hyperbole = _count_pattern_matches(text, HYPERBOLE_PATTERNS)

    total = explicit + inversions + hyperbole
    density = (total / word_count) * 100

    return {
        "explicit_irony": explicit,
        "sentiment_inversions": inversions,
        "hyperbole": hyperbole,
        "total_irony": total,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Signal 3: Gap density
# ---------------------------------------------------------------------------


def compute_gap_density(text: str) -> dict[str, Any]:
    """Measure deliberate omissions per hundred words.

    Tracks ellipses, trailing dashes, aposiopesis, loaded pauses
    (short sentences after long ones), and referential gaps.

    Returns
    -------
    dict with keys:
        ellipses: int
        trailing_dashes: int
        aposiopesis: int
        loaded_pauses: int
        referential_gaps: int
        total_gaps: int
        word_count: int
        density: float  (gaps per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    ellipses = len(ELLIPSIS_PATTERN.findall(text))
    trailing = len(DASH_TRAILING.findall(text))
    apop = len(APOSiopesis.findall(text))
    referential = _count_pattern_matches(text, REFERENTIAL_GAP_PATTERNS)

    # Loaded pauses: short sentence (≤ 5 words) after long sentence (≥ 20 words)
    sentences = _split_sentences(text)
    loaded = 0
    for i in range(1, len(sentences)):
        prev_words = len(_split_words(sentences[i - 1]))
        curr_words = len(_split_words(sentences[i]))
        if prev_words >= 20 and curr_words <= 5:
            loaded += 1

    total = ellipses + trailing + apop + loaded + referential
    density = (total / word_count) * 100

    return {
        "ellipses": ellipses,
        "trailing_dashes": trailing,
        "aposiopesis": apop,
        "loaded_pauses": loaded,
        "referential_gaps": referential,
        "total_gaps": total,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Signal 4: Show vs tell ratio
# ---------------------------------------------------------------------------


def compute_show_tell_ratio(text: str) -> dict[str, Any]:
    """Measure the proportion of showing (sensory/action) vs telling
    (evaluative/abstract) language.

    High ratio = mostly showing (reader infers emotional state from
    physical action and sensory detail).
    Low ratio = mostly telling (emotional state is stated directly).

    Returns
    -------
    dict with keys:
        show_count: int
        tell_count: int
        ratio: float  (show / (show + tell), 0.0 if both zero)
        word_count: int
        density: float  (show + tell per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    show = len(SHOW_VERBS.findall(text))
    tell = len(TELL_WORDS.findall(text))

    total = show + tell
    ratio = show / total if total > 0 else 0.5  # neutral default
    density = (total / word_count) * 100

    return {
        "show_count": show,
        "tell_count": tell,
        "ratio": round(ratio, 4),
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_subtext(stroke: dict[str, Any] | str) -> dict[str, Any]:
    """Analyze subtext signals for a single stroke.

    Returns
    -------
    dict with all four signal analyses plus a composite subtext_class.
    """
    text = _get_stroke_text(stroke)
    if not text or not text.strip():
        return {
            "indirectness": compute_indirectness_density(""),
            "irony": compute_irony_markers(""),
            "gaps": compute_gap_density(""),
            "show_tell": compute_show_tell_ratio(""),
            "subtext_score": 0.0,
            "subtext_class": "opaque",
        }

    indirectness = compute_indirectness_density(text)
    irony = compute_irony_markers(text)
    gaps = compute_gap_density(text)
    show_tell = compute_show_tell_ratio(text)

    # Normalize each signal to [0, 1] range
    # Indirectness: 0–5 per 100 words maps to 0–1
    ind_norm = min(indirectness["density"] / 5.0, 1.0)
    # Irony: 0–3 per 100 words maps to 0–1
    iron_norm = min(irony["density"] / 3.0, 1.0)
    # Gaps: 0–4 per 100 words maps to 0–1
    gap_norm = min(gaps["density"] / 4.0, 1.0)
    # Show/tell: ratio is already [0, 1], but weight density too
    st_norm = show_tell["ratio"] * min(show_tell["density"] / 3.0, 1.0)
    # If show_tell density is very low (no emotion words at all), neutral
    if show_tell["show_count"] + show_tell["tell_count"] == 0:
        st_norm = 0.4  # slightly above neutral — absence of telling is mild showing

    # Weighted composite
    score = (
        0.30 * ind_norm
        + 0.20 * iron_norm
        + 0.25 * gap_norm
        + 0.25 * st_norm
    )

    return {
        "indirectness": indirectness,
        "irony": irony,
        "gaps": gaps,
        "show_tell": show_tell,
        "subtext_score": round(score, 4),
        "subtext_class": _classify_subtext(score),
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_subtext(score: float) -> str:
    """Classify a subtext score into a human-readable label."""
    if score >= 0.75:
        return "layered"
    elif score >= 0.55:
        return "suggestive"
    elif score >= 0.35:
        return "literal"
    elif score >= 0.20:
        return "flat"
    else:
        return "opaque"


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


def compute_subtext_metrics(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute session-level subtext metrics over recent strokes.

    Parameters
    ----------
    strokes : list
        List of stroke dicts or strings.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict with session-level subtext metrics.
    """
    if not strokes:
        return _empty_metrics()

    recent = strokes[-window_size:]
    stroke_analyses = [analyze_stroke_subtext(s) for s in recent]
    stroke_analyses = [a for a in stroke_analyses if a.get("subtext_score", 0) > 0 or True]

    if not stroke_analyses:
        return _empty_metrics()

    scores = [a["subtext_score"] for a in stroke_analyses]
    avg_score = sum(scores) / len(scores)

    total_words = sum(
        a["indirectness"]["word_count"] for a in stroke_analyses
    )

    # Aggregate signal counts
    total_indirect = sum(a["indirectness"]["total_indirect"] for a in stroke_analyses)
    total_irony = sum(a["irony"]["total_irony"] for a in stroke_analyses)
    total_gaps = sum(a["gaps"]["total_gaps"] for a in stroke_analyses)
    total_show = sum(a["show_tell"]["show_count"] for a in stroke_analyses)
    total_tell = sum(a["show_tell"]["tell_count"] for a in stroke_analyses)

    show_tell_ratio = total_show / (total_show + total_tell) if (total_show + total_tell) > 0 else 0.5

    subtext_class = _classify_subtext(avg_score)

    # Class distribution
    class_dist: dict[str, int] = {}
    for a in stroke_analyses:
        cc = a["subtext_class"]
        class_dist[cc] = class_dist.get(cc, 0) + 1

    return {
        "strokes_analyzed": len(stroke_analyses),
        "total_words": total_words,
        "subtext_index": round(avg_score, 4),
        "subtext_class": subtext_class,
        "total_indirect_acts": total_indirect,
        "total_irony_markers": total_irony,
        "total_gaps": total_gaps,
        "total_show_words": total_show,
        "total_tell_words": total_tell,
        "show_tell_ratio": round(show_tell_ratio, 4),
        "class_distribution": class_dist,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "subtext_index": 0.0,
        "subtext_class": "opaque",
        "total_indirect_acts": 0,
        "total_irony_markers": 0,
        "total_gaps": 0,
        "total_show_words": 0,
        "total_tell_words": 0,
        "show_tell_ratio": 0.5,
        "class_distribution": {},
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_subtext_trend(
    strokes: list[dict[str, Any] | str],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute subtext snapshots over time for trend analysis.

    Parameters
    ----------
    strokes : list
        Full stroke list.
    window_size : int
        Strokes per snapshot window.
    step : int
        Stride between windows.

    Returns
    -------
    list[dict]
        List of snapshot dicts with subtext metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_subtext_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the subtext trend from snapshots.

    Returns one of: deepening, stable, flattening, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("subtext_index", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "deepening"
    elif delta < -0.05:
        return "flattening"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_subtext_report(metrics: dict[str, Any]) -> str:
    """Format subtext metrics as a human-readable report."""
    lines = [
        "=== Writer Subtext ===",
        f"Strokes analyzed:    {metrics['strokes_analyzed']}",
        f"Total words:         {metrics['total_words']}",
        f"Subtext index:       {metrics['subtext_index']:.4f} ({metrics['subtext_class']})",
        "",
        f"Total indirect acts: {metrics['total_indirect_acts']}",
        f"Total irony markers: {metrics['total_irony_markers']}",
        f"Total gaps:          {metrics['total_gaps']}",
        f"Show words:          {metrics['total_show_words']}",
        f"Tell words:          {metrics['total_tell_words']}",
        f"Show/tell ratio:     {metrics['show_tell_ratio']:.4f}",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("layered", "suggestive", "literal", "flat", "opaque"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    cc = metrics["subtext_class"]
    lines.append("Interpretation:")
    if cc == "layered":
        lines.append("  Rich subtext. The text operates on multiple levels;")
        lines.append("  the reader must actively interpret what lies beneath.")
    elif cc == "suggestive":
        lines.append("  Moderate subtext. Indirect language and implication")
        lines.append("  are present; the text trusts the reader to connect dots.")
    elif cc == "literal":
        lines.append("  Mostly surface-level. Meaning is stated directly with")
        lines.append("  little implication. Functional but flat.")
    elif cc == "flat":
        lines.append("  Almost no subtext. Every statement means exactly what")
        lines.append("  it says. The text reads like a manual.")
    else:
        lines.append("  Subtext is absent or incoherent. Either everything is")
        lines.append("  explicit, or the implications are impenetrable.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_subtext(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze subtext from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Subtext metrics.
    """
    path = Path(strokes_path)
    if not path.exists():
        return _empty_metrics()

    strokes: list[dict[str, Any]] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return compute_subtext_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_subtext()
    print(format_subtext_report(metrics))
