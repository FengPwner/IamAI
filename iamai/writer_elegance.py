#!/usr/bin/env python3
"""writer_elegance — measure writing elegance as the art of simplicity with depth.

Elegance in writing is not about being fancy; it is about finding the
simplest expression that preserves the full meaning.  An elegant sentence
says exactly what it means, no more, no less, in the form that makes it
easiest to absorb.  It is the intersection of clarity, rhythm, economy,
and craft.

This module is orthogonal to the other writer metrics:

- **concision** tracks *economy of words* alone.  A text can be concise
  but inelegant (telegraphic, choppy, stripped of all texture).  Concision
  is one input to elegance but not the whole picture.

- **specificity** tracks *detail precision*.  A text can be specific but
  inelegant (a data dump with no structure).  Elegance incorporates
  specificity only to the degree that precision serves readability.

- **restraint** tracks *what is held back*.  A text can show restraint
  but still be inelegant in what it does say.  Restraint is about
  omission; elegance is about the quality of what remains.

- **subtext** tracks *layers of meaning*.  A text can have rich subtext
  but be inelegant in its surface expression.  Subtext is about depth;
  elegance is about the surface that reveals that depth.

- **readability** tracks *comprehension ease*.  Elegance subsumes
  readability — a text that is hard to read cannot be elegant — but
  adds the dimension of *craft*: an elegant text is not merely easy,
  it is *well-made*.

Elegance asks: **does the text achieve maximum effect with minimum means?**

Four signals are tracked:

1. **Vocabulary efficiency** — the ratio of unique content words to total
   content words, weighted by word frequency.  Elegant writing uses each
   word deliberately: no filler words ("basically", "actually", "really",
   "very", "just"), no redundant modifiers ("very unique", "completely
   finished", "absolutely essential"), no throat-clearing phrases ("it is
   important to note that", "it should be mentioned that").  Higher
   efficiency means every word earns its place.

2. **Sentence variety** — the coefficient of variation in sentence length,
   combined with sentence-opening diversity.  Monotonous writing uses the
   same sentence length and structure repeatedly.  Elegant writing varies
   its rhythms: a short sentence after a long one creates emphasis; a
   question breaks the declarative monotony; an inverted structure
   surprises the reader into attention.  Variety is measured by the
   standard deviation of sentence lengths divided by the mean (CV),
   and by the proportion of unique sentence openers.

3. **Active/passive ratio** — the proportion of active-voice constructions
   among all verb phrases.  Active voice ("She wrote the code") is
   generally more elegant than passive ("The code was written by her"):
   it is shorter, clearer, and more direct.  Passive voice is not wrong
   — sometimes it is the right choice (when the agent is unknown or
   irrelevant) — but a high proportion of passive voice usually indicates
   less elegant prose.

4. **Adverb density** — the frequency of -ly adverbs per hundred words.
   Stephen King's dictum: "the road to hell is paved with adverbs."
   Elegant writing uses strong verbs instead of adverb-verb combinations:
   "she sprinted" instead of "she ran quickly", "he whispered" instead of
   "he said quietly".  Adverb density is not zero in elegant prose —
   sometimes an adverb is the right word — but it tends to be low.

From these signals a session-level **elegance_index** is computed
and classified:

==============  ============================================================
class           meaning
==============  ============================================================
refined         index >= 0.75 — elegant prose; every word earns its place,
                sentence rhythms are varied, voice is direct, verbs are
                strong; the writing achieves maximum effect with minimum
                means
polished        0.55 <= index < 0.75 — well-crafted prose; mostly clean
                and varied, with occasional lapses into filler or
                monotony; above-average craft
functional      0.35 <= index < 0.55 — serviceable prose; meaning is
                conveyed but the expression could be tighter; filler
                words, passive constructions, or monotonous rhythms
                drag it down
cluttered       0.20 <= index < 0.35 — overloaded prose; excessive filler,
                passive voice, adverb stacking, or repetitive sentence
                patterns make the text harder to absorb than it needs
                to be
lead            index < 0.20 — heavy, laborious prose; every sentence
                carries unnecessary weight; the reader must wade through
                thickets of filler, passive constructions, and adverb-
                modified verbs to extract meaning
==============  ============================================================

Orthogonal to concision (concision = word economy; elegance = word economy
plus craft plus rhythm), subtext (subtext = implied meaning; elegance =
surface quality), and restraint (restraint = discipline of omission;
elegance = quality of what remains).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants: filler words and redundant modifiers
# ---------------------------------------------------------------------------

# Common filler words that add no meaning
FILLER_WORDS = [
    re.compile(r"\bbasically\b", re.I),
    re.compile(r"\bactually\b", re.I),
    re.compile(r"\breally\b", re.I),
    re.compile(r"\bvery\b", re.I),
    re.compile(r"\bjust\b", re.I),
    re.compile(r"\bquite\b", re.I),
    re.compile(r"\brather\b", re.I),
    re.compile(r"\bsomewhat\b", re.I),
    re.compile(r"\bfairly\b", re.I),
    re.compile(r"\bessentially\b", re.I),
    re.compile(r"\bvirtually\b", re.I),
    re.compile(r"\bpractically\b", re.I),
    re.compile(r"\bliterally\b", re.I),
    re.compile(r"\bhonestly\b", re.I),
    re.compile(r"\bfrankly\b", re.I),
    re.compile(r"\bobviously\b", re.I),
    re.compile(r"\bclearly\b", re.I),
    re.compile(r"\bsimply\b", re.I),
    re.compile(r"\bmerely\b", re.I),
]

# Redundant modifier patterns — adjective/noun that is already absolute
REDUNDANT_MODIFIERS = [
    re.compile(r"\b(completely|totally|absolutely|entirely|fully|utterly) (finished|done|complete|full|empty|dead|alive|unique|perfect|essential|necessary|impossible|certain|sure)\b", re.I),
    re.compile(r"\bvery (unique|special|different|same|identical|essential|necessary|impossible|obvious|clear|certain)\b", re.I),
    re.compile(r"\b(extremely|incredibly|amazingly|remarkably) (good|bad|big|small|fast|slow|easy|hard|simple|complex)\b", re.I),
    re.compile(r"\b(past|previous|prior) (experience|history|record)\b", re.I),
    re.compile(r"\bfuture (plans?|prospects?|goals?|intentions?|endeavors?)\b", re.I),
    re.compile(r"\b(true|actual|real) (fact|truth|reality)\b", re.I),
]

# Throat-clearing phrases — verbose lead-ins that could be cut
THROAT_CLEARING = [
    re.compile(r"\bit is (important|worth|necessary|essential|critical|vital) to (note|mention|remember|understand|recognize|realize|consider|point out)\b", re.I),
    re.compile(r"\bit should be (noted|mentioned|pointed out|emphasized|stressed|highlighted) that\b", re.I),
    re.compile(r"\bit (goes|should go) without saying that\b", re.I),
    re.compile(r"\b(needless|unnecessary) to say\b", re.I),
    re.compile(r"\bthe fact (of|that) the matter is\b", re.I),
    re.compile(r"\bat the end of the day\b", re.I),
    re.compile(r"\bwhen all is said and done\b", re.I),
    re.compile(r"\bin (the )?final analysis\b", re.I),
    re.compile(r"\bfor all intents and purposes\b", re.I),
    re.compile(r"\bas a matter of fact\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: passive voice detection
# ---------------------------------------------------------------------------

# Passive voice patterns: forms of "to be" + past participle
BE_VERBS = r"\b(am|is|are|was|were|be|been|being)\b"

# Common past participles (a representative sample; full detection would
# require a morphological analyzer)
PASSIVE_PATTERNS = [
    re.compile(rf"{BE_VERBS}\s+\w+(ed|en)\b", re.I),
    re.compile(rf"{BE_VERBS}\s+(being|been)\s+\w+(ed|en)\b", re.I),
    re.compile(rf"{BE_VERBS}\s+(made|done|taken|given|seen|known|found|told|asked|shown|built|run|written|read|set|put|held|kept|left|sent|paid|brought|thought|called|tried|needed|used|based|designed|developed|created|tested|deployed|released|published|written|compiled|executed|processed|handled|managed|stored|retrieved|returned|received|accepted|rejected|approved|denied|completed|started|stopped|paused|resumed)\b", re.I),
]

# Active voice signals — sentences starting with the subject doing the action
ACTIVE_OPENERS = [
    re.compile(r"^(I|We|You|He|She|It|They|The \w+|A \w+|This|That|These|Those)\s+\w+ed\b", re.I),
    re.compile(r"^(I|We|You|He|She|It|They|The \w+|A \w+|This|That|These|Those)\s+(run|write|read|build|make|take|give|see|find|tell|ask|show|set|put|hold|keep|leave|send|pay|bring|think|call|try|need|use|design|develop|create|test|deploy|release|publish|compile|execute|process|handle|manage|store|retrieve|return|receive|accept|reject|approve|deny|complete|start|stop|pause|resume)s?\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: adverb detection
# ---------------------------------------------------------------------------

# -ly adverbs (with common exceptions)
ADVERB_PATTERN = re.compile(r"\b\w{3,}ly\b", re.I)
ADVERB_EXCEPTIONS = {
    "only", "early", "late", "daily", "weekly", "monthly", "yearly",
    "family", "friendly", "lovely", "lonely", "likely", "unlikely",
    "apply", "reply", "rely", "comply", "supply", "imply", "multiply",
    "fly", "cry", "try", "dry", "sly", "shy", "spy", "sty", "guy",
    "july", "mostly", "already", "always", "belly", "jelly", "holly",
    "silly", "chilly", "ully", "bully", "dully", "fully",
    "homely", "lively", "timely", "comely", "orderly", "elderly",
    "gentlemanly", "womanly", "manly", "brotherly", "sisterly",
    "motherly", "fatherly", "neighborly", "scholarly",
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words, stripping punctuation."""
    return [w.lower() for w in re.findall(r"[a-zA-Z']+", text)]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
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


def _get_content_words(words: list[str]) -> list[str]:
    """Filter to content words (nouns, verbs, adjectives, adverbs).

    Simplified: exclude common function words.
    """
    function_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "am", "have", "has", "had", "do", "does", "did",
        "will", "would", "shall", "should", "may", "might", "must",
        "can", "could", "of", "in", "to", "for", "with", "on", "at",
        "by", "from", "as", "into", "through", "during", "before",
        "after", "above", "below", "between", "under", "over", "and",
        "but", "or", "nor", "not", "so", "yet", "both", "either",
        "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same",
        "than", "too", "very", "just", "because", "if", "when",
        "where", "how", "what", "which", "who", "whom", "whose",
        "this", "that", "these", "those", "i", "me", "my", "mine",
        "we", "us", "our", "ours", "you", "your", "yours", "he",
        "him", "his", "she", "her", "hers", "it", "its", "they",
        "them", "their", "theirs", "about", "up", "out", "then",
    }
    return [w for w in words if w not in function_words and len(w) > 1]


# ---------------------------------------------------------------------------
# Signal 1: Vocabulary efficiency
# ---------------------------------------------------------------------------


def compute_vocabulary_efficiency(text: str) -> dict[str, Any]:
    """Measure how efficiently each word earns its place.

    Combines filler word count, redundant modifier count, and
    throat-clearing phrase count into a single efficiency score.

    Returns
    -------
    dict with keys:
        fillers: int
        redundant_modifiers: int
        throat_clearing: int
        total_waste: int
        word_count: int
        efficiency: float  (1.0 = no waste, 0.0 = all waste)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    fillers = _count_pattern_matches(text, FILLER_WORDS)
    redundant = _count_pattern_matches(text, REDUNDANT_MODIFIERS)
    throat = _count_pattern_matches(text, THROAT_CLEARING)

    total_waste = fillers + redundant + throat
    # Efficiency: proportion of non-wasted words
    # Each waste item affects ~1-3 words; estimate 2 words per waste item
    wasted_words = min(total_waste * 2, word_count)
    efficiency = 1.0 - (wasted_words / word_count)

    return {
        "fillers": fillers,
        "redundant_modifiers": redundant,
        "throat_clearing": throat,
        "total_waste": total_waste,
        "word_count": word_count,
        "efficiency": round(max(0.0, efficiency), 4),
    }


# ---------------------------------------------------------------------------
# Signal 2: Sentence variety
# ---------------------------------------------------------------------------


def compute_sentence_variety(text: str) -> dict[str, Any]:
    """Measure variation in sentence length and structure.

    Uses coefficient of variation (CV) for sentence lengths and
    diversity of sentence openers.

    Returns
    -------
    dict with keys:
        sentence_count: int
        mean_length: float
        std_length: float
        cv: float  (coefficient of variation = std/mean)
        unique_openers: int
        total_openers: int
        opener_diversity: float  (unique/total, 1.0 = all different)
        variety_score: float  (combined score)
    """
    sentences = _split_sentences(text)
    sentence_count = len(sentences)

    if sentence_count < 2:
        return {
            "sentence_count": sentence_count,
            "mean_length": 0.0,
            "std_length": 0.0,
            "cv": 0.0,
            "unique_openers": 0,
            "total_openers": 0,
            "opener_diversity": 0.0,
            "variety_score": 0.0,
        }

    # Sentence lengths
    lengths = [len(_split_words(s)) for s in sentences]
    mean_length = sum(lengths) / len(lengths)
    variance = sum((l - mean_length) ** 2 for l in lengths) / len(lengths)
    std_length = math.sqrt(variance)
    cv = std_length / mean_length if mean_length > 0 else 0.0

    # Sentence openers (first word of each sentence)
    openers = []
    for s in sentences:
        words = _split_words(s)
        if words:
            openers.append(words[0])

    total_openers = len(openers)
    unique_openers = len(set(openers))
    opener_diversity = unique_openers / total_openers if total_openers > 0 else 0.0

    # Combined variety score
    # CV: good range is 0.3–0.7; too low = monotonous, too high = erratic
    # Map CV to [0, 1] with peak at 0.5
    cv_score = 1.0 - abs(cv - 0.5) / 0.5 if cv <= 1.0 else max(0.0, 1.0 - (cv - 1.0))
    # Opener diversity is already [0, 1]
    variety_score = 0.5 * cv_score + 0.5 * opener_diversity

    return {
        "sentence_count": sentence_count,
        "mean_length": round(mean_length, 2),
        "std_length": round(std_length, 2),
        "cv": round(cv, 4),
        "unique_openers": unique_openers,
        "total_openers": total_openers,
        "opener_diversity": round(opener_diversity, 4),
        "variety_score": round(variety_score, 4),
    }


# ---------------------------------------------------------------------------
# Signal 3: Active/passive ratio
# ---------------------------------------------------------------------------


def compute_active_passive_ratio(text: str) -> dict[str, Any]:
    """Measure the proportion of active vs passive voice.

    Returns
    -------
    dict with keys:
        passive_count: int
        active_count: int
        total_verbs: int
        active_ratio: float  (active / total, 1.0 = all active)
        word_count: int
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    sentences = _split_sentences(text)
    passive_count = 0
    active_count = 0

    for sent in sentences:
        is_passive = any(pat.search(sent) for pat in PASSIVE_PATTERNS)
        is_active = any(pat.search(sent) for pat in ACTIVE_OPENERS)

        if is_passive:
            passive_count += 1
        if is_active:
            active_count += 1
        # A sentence can be neither (e.g., intransitive, imperative)

    total_verbs = passive_count + active_count
    active_ratio = active_count / total_verbs if total_verbs > 0 else 0.5

    return {
        "passive_count": passive_count,
        "active_count": active_count,
        "total_verbs": total_verbs,
        "active_ratio": round(active_ratio, 4),
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Signal 4: Adverb density
# ---------------------------------------------------------------------------


def compute_adverb_density(text: str) -> dict[str, Any]:
    """Measure the frequency of -ly adverbs per hundred words.

    Excludes common non-adverb -ly words (family, friendly, etc.).

    Returns
    -------
    dict with keys:
        adverb_count: int
        word_count: int
        density: float  (adverbs per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    adverb_count = 0
    for word in words:
        if ADVERB_PATTERN.match(word) and word not in ADVERB_EXCEPTIONS:
            adverb_count += 1

    density = (adverb_count / word_count) * 100

    return {
        "adverb_count": adverb_count,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_elegance(stroke: dict[str, Any] | str) -> dict[str, Any]:
    """Analyze elegance signals for a single stroke.

    Returns
    -------
    dict with all four signal analyses plus a composite elegance_score.
    """
    text = _get_stroke_text(stroke)
    if not text or not text.strip():
        return {
            "vocabulary": compute_vocabulary_efficiency(""),
            "variety": compute_sentence_variety(""),
            "voice": compute_active_passive_ratio(""),
            "adverbs": compute_adverb_density(""),
            "elegance_score": 0.0,
            "elegance_class": "lead",
        }

    vocab = compute_vocabulary_efficiency(text)
    variety = compute_sentence_variety(text)
    voice = compute_active_passive_ratio(text)
    adverbs = compute_adverb_density(text)

    # Normalize each signal to [0, 1]
    vocab_score = vocab["efficiency"]  # already [0, 1]
    variety_score = variety["variety_score"]  # already [0, 1]
    voice_score = voice["active_ratio"]  # already [0, 1]

    # Adverb density: 0 = best, 5+ per 100 words = worst
    # Invert: lower density = higher score
    adverb_score = max(0.0, 1.0 - (adverbs["density"] / 5.0))

    # Weighted composite
    score = (
        0.30 * vocab_score
        + 0.25 * variety_score
        + 0.25 * voice_score
        + 0.20 * adverb_score
    )

    return {
        "vocabulary": vocab,
        "variety": variety,
        "voice": voice,
        "adverbs": adverbs,
        "elegance_score": round(score, 4),
        "elegance_class": _classify_elegance(score),
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_elegance(score: float) -> str:
    """Classify an elegance score into a human-readable label."""
    if score >= 0.75:
        return "refined"
    elif score >= 0.55:
        return "polished"
    elif score >= 0.35:
        return "functional"
    elif score >= 0.20:
        return "cluttered"
    else:
        return "lead"


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


def compute_elegance_metrics(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute session-level elegance metrics over recent strokes.

    Parameters
    ----------
    strokes : list
        List of stroke dicts or strings.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict with session-level elegance metrics.
    """
    if not strokes:
        return _empty_metrics()

    recent = strokes[-window_size:]
    analyses = [analyze_stroke_elegance(s) for s in recent]

    if not analyses:
        return _empty_metrics()

    scores = [a["elegance_score"] for a in analyses]
    avg_score = sum(scores) / len(scores)

    total_words = sum(a["vocabulary"]["word_count"] for a in analyses)
    total_fillers = sum(a["vocabulary"]["fillers"] for a in analyses)
    total_redundant = sum(a["vocabulary"]["redundant_modifiers"] for a in analyses)
    total_throat = sum(a["vocabulary"]["throat_clearing"] for a in analyses)
    total_passive = sum(a["voice"]["passive_count"] for a in analyses)
    total_active = sum(a["voice"]["active_count"] for a in analyses)
    total_adverbs = sum(a["adverbs"]["adverb_count"] for a in analyses)

    avg_variety = sum(a["variety"]["variety_score"] for a in analyses) / len(analyses)

    elegance_class = _classify_elegance(avg_score)

    # Class distribution
    class_dist: dict[str, int] = {}
    for a in analyses:
        cc = a["elegance_class"]
        class_dist[cc] = class_dist.get(cc, 0) + 1

    return {
        "strokes_analyzed": len(analyses),
        "total_words": total_words,
        "elegance_index": round(avg_score, 4),
        "elegance_class": elegance_class,
        "total_fillers": total_fillers,
        "total_redundant_modifiers": total_redundant,
        "total_throat_clearing": total_throat,
        "total_passive": total_passive,
        "total_active": total_active,
        "active_ratio": round(
            total_active / (total_active + total_passive)
            if (total_active + total_passive) > 0 else 0.5, 4
        ),
        "total_adverbs": total_adverbs,
        "avg_variety": round(avg_variety, 4),
        "class_distribution": class_dist,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "elegance_index": 0.0,
        "elegance_class": "lead",
        "total_fillers": 0,
        "total_redundant_modifiers": 0,
        "total_throat_clearing": 0,
        "total_passive": 0,
        "total_active": 0,
        "active_ratio": 0.5,
        "total_adverbs": 0,
        "avg_variety": 0.0,
        "class_distribution": {},
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_elegance_trend(
    strokes: list[dict[str, Any] | str],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute elegance snapshots over time for trend analysis.

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
        List of snapshot dicts with elegance metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_elegance_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the elegance trend from snapshots.

    Returns one of: refining, stable, degrading, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("elegance_index", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "refining"
    elif delta < -0.05:
        return "degrading"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_elegance_report(metrics: dict[str, Any]) -> str:
    """Format elegance metrics as a human-readable report."""
    lines = [
        "=== Writer Elegance ===",
        f"Strokes analyzed:        {metrics['strokes_analyzed']}",
        f"Total words:             {metrics['total_words']}",
        f"Elegance index:          {metrics['elegance_index']:.4f} ({metrics['elegance_class']})",
        "",
        f"Filler words:            {metrics['total_fillers']}",
        f"Redundant modifiers:     {metrics['total_redundant_modifiers']}",
        f"Throat-clearing phrases: {metrics['total_throat_clearing']}",
        f"Passive constructions:   {metrics['total_passive']}",
        f"Active constructions:    {metrics['total_active']}",
        f"Active ratio:            {metrics['active_ratio']:.4f}",
        f"Total adverbs:           {metrics['total_adverbs']}",
        f"Avg sentence variety:    {metrics['avg_variety']:.4f}",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("refined", "polished", "functional", "cluttered", "lead"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    cc = metrics["elegance_class"]
    lines.append("Interpretation:")
    if cc == "refined":
        lines.append("  Elegant prose. Every word earns its place, rhythms")
        lines.append("  are varied, voice is direct, verbs are strong.")
    elif cc == "polished":
        lines.append("  Well-crafted prose. Mostly clean and varied, with")
        lines.append("  occasional lapses into filler or monotony.")
    elif cc == "functional":
        lines.append("  Serviceable prose. Meaning is conveyed but expression")
        lines.append("  could be tighter; filler and passive drag it down.")
    elif cc == "cluttered":
        lines.append("  Overloaded prose. Excessive filler, passive voice, or")
        lines.append("  repetitive patterns make the text harder to absorb.")
    else:
        lines.append("  Heavy, laborious prose. Every sentence carries")
        lines.append("  unnecessary weight; the reader must wade through")
        lines.append("  thickets of filler to extract meaning.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_elegance(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze elegance from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Elegance metrics.
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

    return compute_elegance_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_elegance()
    print(format_elegance_report(metrics))
