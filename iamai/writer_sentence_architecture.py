#!/usr/bin/env python3
"""writer_sentence_architecture — measure structural variety of sentences.

Sentence architecture is the craft of building sentences in different
shapes.  Good architecture varies sentence length, opens with diverse
structures, mixes simple and complex constructions, and uses short
sentences for punch alongside longer ones for flow.  Poor architecture
produces monotonous prose: every sentence the same length, every
sentence starting with the same word, every clause following the same
subject-verb-object pattern.

This module is orthogonal to the other writer metrics:

- **prose_rhythm** tracks *cadence and flow* — the musical quality of
  prose.  Rhythm is about how sentences *sound*; architecture is about
  how they are *built*.  Two texts can have similar rhythm (steady
  cadence) but very different architecture (one uses varied sentence
  structures, the other uses uniform structures at a steady pace).

- **concision** tracks *word count economy*.  Concision is about how
  *many* words you use.  Architecture is about the *shape* of those
  words — a concise text can have poor architecture (ten short sentences
  all structured identically) and a longer text can have excellent
  architecture (varied sentence shapes that earn their length).

- **elegance** tracks *overall craft quality*.  Elegance is a holistic
  judgment.  Architecture is a structural measurement — the variety and
  intentionality of sentence shapes, independent of whether the prose
  is beautiful.

- **density** tracks *information per word*.  Dense text can have poor
  architecture (every sentence a long, complex clause) or excellent
  architecture (short punchy claims alternating with detailed evidence).

- **readability** tracks *comprehension ease*.  Varied architecture can
  improve readability (short sentences break up complex ones) or hurt it
  (excessive variety can feel chaotic).  Architecture measures variety;
  readability measures comprehension.

Sentence architecture asks: **does the writer build sentences in
different shapes, or does every sentence look the same?**

Four signals are tracked:

1. **Length variance** — coefficient of variation of sentence lengths
   (standard deviation / mean).  High variance means the writer mixes
   short and long sentences deliberately.  Low variance means every
   sentence is approximately the same length, which produces a droning,
   mechanical feel.  The target is not maximum variance (which would
   mean random lengths) but *intentional* variance: short sentences for
   emphasis, longer ones for explanation.

2. **Opening diversity** — how many distinct structural patterns appear
   at the start of sentences.  Monotonous prose opens every sentence
   with the subject ("The system does X. The process handles Y. The
   module provides Z.").  Varied prose opens with adverbs, prepositional
   phrases, dependent clauses, participles, questions, and fragments.
   Measured as the normalized entropy of opening-word categories.

3. **Active ratio** — proportion of sentences using active voice rather
   than passive.  Active voice is not always better (passive has
   legitimate uses: when the agent is unknown, when the patient is the
   topic), but a low active ratio signals a writer who defaults to
   passive constructions, which is a structural monotony problem.

4. **Fragment rate** — deliberate use of sentence fragments for effect.
   "This matters. A lot." The fragment "A lot." is grammatically
   incomplete but rhetorically powerful.  Skilled writers use fragments
   sparingly and intentionally.  Zero fragments can signal rigid,
   academic prose; excessive fragments signal careless, choppy writing.
   The sweet spot is low but nonzero.

From these signals a session-level **architecture_index** is computed
and classified:

==============  ============================================================
class           meaning
==============  ============================================================
masterful       index >= 0.75 — sentences vary in length, open with
                diverse structures, mix active and passive deliberately,
                and use fragments for emphasis; the prose has structural
                variety that serves the content
varied          0.55 <= index < 0.75 — good structural variety with
                occasional monotony; most sentences are shaped
                intentionally but some patterns repeat
competent       0.35 <= index < 0.55 — adequate variety; the writer
                uses some structural variation but falls into patterns
                (same-length sentences, repetitive openings) often enough
                to notice
uniform         0.20 <= index < 0.35 — limited structural variety;
                sentences tend to be similar in length and shape,
                openings repeat, and the prose has a mechanical quality
monotonous      index < 0.20 — almost no structural variety; every
                sentence follows the same pattern, producing a droning,
                robotic effect that makes the reader work to stay engaged
==============  ============================================================

Orthogonal to prose_rhythm (prose_rhythm = cadence; architecture =
structural variety), concision (concision = word economy; architecture =
sentence shape), and elegance (elegance = craft quality; architecture =
structural measurement).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants: opening word categories
# ---------------------------------------------------------------------------

# Articles — boring sentence opener (subject-first)
ARTICLES = {"a", "an", "the"}

# Common pronouns — subject-first opener
PRONOUNS = {
    "i", "we", "you", "he", "she", "it", "they", "this", "that",
    "these", "those", "who", "what", "which",
}

# Prepositions — more interesting opener
PREPOSITIONS = {
    "in", "on", "at", "by", "for", "with", "from", "to", "of",
    "about", "between", "through", "during", "before", "after",
    "above", "below", "across", "along", "around", "behind",
    "beneath", "beside", "beyond", "despite", "down", "into",
    "near", "off", "onto", "out", "over", "past", "since",
    "throughout", "toward", "towards", "under", "underneath",
    "until", "up", "upon", "within", "without",
}

# Adverbs / conjunctive adverbs — varied opener
ADVERBS = {
    "however", "therefore", "moreover", "furthermore", "nevertheless",
    "nonetheless", "meanwhile", "consequently", "accordingly",
    "instead", "otherwise", "similarly", "likewise", "indeed",
    "certainly", "perhaps", "maybe", "clearly", "obviously",
    "interestingly", "notably", "importantly", "unfortunately",
    "fortunately", "surprisingly", "generally", "typically",
    "often", "sometimes", "usually", "rarely", "never", "always",
    "here", "there", "now", "then", "thus", "hence", "still",
    "yet", "also", "too", "only", "even", "just", "quite",
    "rather", "somewhat", "well",
}

# Conjunctions — clause-linking opener
CONJUNCTIONS = {"and", "but", "or", "nor", "for", "yet", "so",
                "although", "because", "since", "while", "if",
                "when", "unless", "though", "whether", "once"}

# Passive voice indicators
PASSIVE_INDICATORS = [
    re.compile(r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b", re.I),
    re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+\s+)?(?:by|with)\s+the\b", re.I),
]

# Sentence-ending punctuation
SENTENCE_END = re.compile(r"[.!?]+")

# Words (lowercase tokens)
WORD_RE = re.compile(r"[a-zA-Z'\u2019]+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on sentence-ending punctuation."""
    # Remove markdown formatting
    clean = re.sub(r"[#*_`~\[\]()>]", " ", text)
    # Split on sentence-ending punctuation followed by space or end
    parts = re.split(r"(?<=[.!?])\s+", clean.strip())
    return [s.strip() for s in parts if s.strip() and len(s.strip()) > 3]


def _split_words(sentence: str) -> list[str]:
    """Extract words from a sentence."""
    return WORD_RE.findall(sentence.lower())


def _get_stroke_text(stroke: dict[str, Any]) -> str:
    """Extract text content from a stroke record."""
    text = stroke.get("text", "")
    if not text:
        text = stroke.get("content", "")
    if not text:
        text = stroke.get("body", "")
    return text


# ---------------------------------------------------------------------------
# Signal 1: Length variance (coefficient of variation)
# ---------------------------------------------------------------------------


def compute_length_variance(sentences: list[str]) -> float:
    """Compute coefficient of variation of sentence word counts.

    Returns the CV (std / mean).  Higher values indicate more variety
    in sentence length.  Returns 0.0 for fewer than 2 sentences.

    Typical ranges:
    - CV < 0.3: very uniform sentence lengths
    - 0.3 <= CV < 0.6: moderate variety
    - 0.6 <= CV < 1.0: good variety
    - CV >= 1.0: high variety (may include deliberate fragments)
    """
    if len(sentences) < 2:
        return 0.0
    lengths = [len(_split_words(s)) for s in sentences]
    # Filter out zero-length "sentences"
    lengths = [l for l in lengths if l > 0]
    if len(lengths) < 2:
        return 0.0
    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return 0.0
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    std = math.sqrt(variance)
    return std / mean


def _score_length_variance(cv: float) -> float:
    """Score length variance on 0-1 scale.

    Sweet spot is CV around 0.5-0.8.  Too low is monotonous, too high
    is chaotic.
    """
    if cv <= 0.0:
        return 0.1
    if cv < 0.3:
        return 0.2 + (cv / 0.3) * 0.3  # 0.2 -> 0.5
    if cv < 0.6:
        return 0.5 + ((cv - 0.3) / 0.3) * 0.3  # 0.5 -> 0.8
    if cv < 1.0:
        return 0.8 + ((cv - 0.6) / 0.4) * 0.2  # 0.8 -> 1.0
    # Above 1.0, slight penalty for chaos
    return max(0.5, 1.0 - (cv - 1.0) * 0.3)


# ---------------------------------------------------------------------------
# Signal 2: Opening diversity
# ---------------------------------------------------------------------------


def _classify_opener(sentence: str) -> str:
    """Classify the opening word category of a sentence."""
    words = _split_words(sentence)
    if not words:
        return "unknown"
    first = words[0].lower()
    if first in ARTICLES:
        return "article"
    if first in PRONOUNS:
        return "pronoun"
    if first in PREPOSITIONS:
        return "preposition"
    if first in ADVERBS:
        return "adverb"
    if first in CONJUNCTIONS:
        return "conjunction"
    # Check if it looks like a number or proper noun (capitalized)
    if first[0].isupper() and first not in {"i"}:
        return "proper_or_content"
    return "content"


def compute_opening_diversity(sentences: list[str]) -> float:
    """Compute normalized entropy of sentence opening categories.

    Returns a value between 0.0 (all openings the same category) and
    1.0 (perfectly uniform distribution across all categories).

    Categories: article, pronoun, preposition, adverb, conjunction,
    content, proper_or_content, unknown.
    """
    if len(sentences) < 2:
        return 0.0
    openers = [_classify_opener(s) for s in sentences]
    # Count category frequencies
    counts: dict[str, int] = {}
    for o in openers:
        counts[o] = counts.get(o, 0) + 1
    total = len(openers)
    # Compute entropy
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    # Normalize by maximum possible entropy
    n_categories = len(counts)
    if n_categories <= 1:
        return 0.0
    max_entropy = math.log2(n_categories)
    if max_entropy == 0:
        return 0.0
    return entropy / max_entropy


# ---------------------------------------------------------------------------
# Signal 3: Active ratio
# ---------------------------------------------------------------------------


def _is_passive(sentence: str) -> bool:
    """Check if a sentence uses passive voice construction."""
    for pattern in PASSIVE_INDICATORS:
        if pattern.search(sentence):
            return True
    return False


def compute_active_ratio(sentences: list[str]) -> float:
    """Compute proportion of sentences using active voice.

    Returns a value between 0.0 (all passive) and 1.0 (all active).
    For fewer than 2 sentences, returns 0.5 (neutral).
    """
    if len(sentences) < 2:
        return 0.5
    active_count = sum(1 for s in sentences if not _is_passive(s))
    return active_count / len(sentences)


def _score_active_ratio(ratio: float) -> float:
    """Score active ratio on 0-1 scale.

    Sweet spot is 0.7-0.9 active.  Too much passive is monotonous;
    all-active can be blunt.
    """
    if ratio < 0.5:
        return 0.2 + ratio * 0.6  # 0.2 -> 0.5
    if ratio < 0.7:
        return 0.5 + ((ratio - 0.5) / 0.2) * 0.3  # 0.5 -> 0.8
    if ratio <= 0.95:
        return 0.8 + ((ratio - 0.7) / 0.25) * 0.2  # 0.8 -> 1.0
    # Nearly all active — slight deduction for lack of variety
    return 0.9


# ---------------------------------------------------------------------------
# Signal 4: Fragment rate
# ---------------------------------------------------------------------------


def _is_fragment(sentence: str) -> bool:
    """Heuristic: is this sentence a deliberate fragment?

    A fragment is a short group of words (1-4 words) that lacks a
    finite verb.  Not all short sentences are fragments — "Go." and
    "It works." are complete.  But "A lot." and "Very much." and
    "No way." are fragments used for rhetorical effect.
    """
    words = _split_words(sentence)
    if len(words) < 1 or len(words) > 3:
        return False
    # Check for a finite verb (crude heuristic: common verb forms)
    verb_indicators = [
        re.compile(
            r"\b(?:is|are|was|were|has|have|had|do|does|did|"
            r"can|could|will|would|shall|should|may|might|"
            r"go|goes|went|gone|come|comes|came|make|makes|made|take|takes|took|"
            r"know|knows|knew|think|thinks|thought|see|sees|saw|want|wants|need|needs|"
            r"use|uses|used|work|works|worked|show|shows|showed|shown|"
            r"run|runs|ran|give|gives|gave|get|gets|got|say|says|said|"
            r"tell|tells|told|find|finds|found|keep|keeps|kept|"
            r"stop|stops|stopped|start|starts|started|"
            r"try|tries|tried|help|helps|helped|"
            r"seem|seems|seemed|feel|feels|felt|"
            r"look|looks|looked|turn|turns|turned|"
            r"play|plays|played|move|moves|moved|"
            r"live|lives|lived|believe|believes|believed|"
            r"hold|holds|held|bring|brings|brought|"
            r"happen|happens|happened|write|writes|wrote|written|"
            r"provide|provides|provided|sit|sits|sat|stand|stands|stood|"
            r"lose|loses|lost|pay|pays|paid|meet|meets|met|"
            r"include|includes|included|continue|continues|continued|"
            r"set|sets|learn|learns|learned|change|changes|changed|"
            r"lead|leads|led|understand|understands|understood|"
            r"watch|watches|watched|follow|follows|followed|"
            r"create|creates|created|speak|speaks|spoke|"
            r"read|reads|allow|allows|allowed|add|adds|added|"
            r"spend|spends|spent|grow|grows|grew|open|opens|opened|"
            r"walk|walks|walked|win|wins|won|offer|offers|offered|"
            r"remember|remembers|remembered|love|loves|loved|"
            r"consider|considers|considered|appear|appears|appeared|"
            r"buy|buys|bought|wait|waits|waited|serve|serves|served|"
            r"die|dies|died|send|sends|sent|expect|expects|expected|"
            r"build|builds|built|stay|stays|stayed|fall|falls|fell|"
            r"cut|cuts|reach|reaches|reached|kill|kills|killed|"
            r"remain|remains|remained|suggest|suggests|suggested|"
            r"raise|raises|raised|pass|passes|passed|sell|sells|sold|"
            r"require|requires|required|report|reports|reported|"
            r"decide|decides|decided|pull|pulls|pulled|"
            r"develop|develops|developed|"
            r"\w+ed\b|\w+ing\b|\w+es\b|\w+[^aeiou]s\b)"
            r"",
            re.I,
        ),
    ]
    for pattern in verb_indicators:
        if pattern.search(sentence):
            return False
    return True


def compute_fragment_rate(sentences: list[str]) -> float:
    """Compute proportion of sentences that are deliberate fragments.

    Returns a value between 0.0 (no fragments) and 1.0 (all fragments).
    """
    if len(sentences) < 2:
        return 0.0
    fragments = sum(1 for s in sentences if _is_fragment(s))
    return fragments / len(sentences)


def _score_fragment_rate(rate: float) -> float:
    """Score fragment rate on 0-1 scale.

    Sweet spot is 0.03-0.10 (a few fragments for emphasis).  Zero is
    rigid, above 0.15 is choppy.
    """
    if rate == 0.0:
        return 0.5  # No fragments: competent but rigid
    if rate < 0.03:
        return 0.5 + (rate / 0.03) * 0.3  # 0.5 -> 0.8
    if rate <= 0.10:
        return 0.8 + ((rate - 0.03) / 0.07) * 0.2  # 0.8 -> 1.0
    if rate <= 0.20:
        return 1.0 - ((rate - 0.10) / 0.10) * 0.4  # 1.0 -> 0.6
    # Excessive fragments
    return max(0.2, 0.6 - (rate - 0.20) * 2.0)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


def compute_architecture_index(
    length_cv: float,
    opening_div: float,
    active_ratio: float,
    fragment_rate: float,
) -> float:
    """Compute weighted composite architecture index.

    Weights:
    - Length variance: 0.30 (most impactful for reader experience)
    - Opening diversity: 0.30 (strongly affects perceived monotony)
    - Active ratio: 0.25 (structural clarity)
    - Fragment rate: 0.15 (stylistic spice)
    """
    s_lv = _score_length_variance(length_cv)
    s_od = opening_div  # Already 0-1
    s_ar = _score_active_ratio(active_ratio)
    s_fr = _score_fragment_rate(fragment_rate)
    return 0.30 * s_lv + 0.30 * s_od + 0.25 * s_ar + 0.15 * s_fr


def _classify_architecture(index: float) -> str:
    """Classify the architecture index into a quality class."""
    if index >= 0.75:
        return "masterful"
    if index >= 0.55:
        return "varied"
    if index >= 0.35:
        return "competent"
    if index >= 0.20:
        return "uniform"
    return "monotonous"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyze_sentence_architecture(text: str) -> dict[str, Any]:
    """Analyze the sentence architecture of a text.

    Returns a dict with:
    - total_sentences: int
    - total_words: int
    - length_cv: float (coefficient of variation of sentence lengths)
    - opening_diversity: float (normalized entropy of openers)
    - active_ratio: float (proportion active voice)
    - fragment_rate: float (proportion of fragments)
    - architecture_index: float (weighted composite, 0-1)
    - architecture_class: str (masterful|varied|competent|uniform|monotonous)
    - opening_distribution: dict[str, int]
    """
    sentences = _split_sentences(text)
    if not sentences:
        return {
            "total_sentences": 0,
            "total_words": 0,
            "length_cv": 0.0,
            "opening_diversity": 0.0,
            "active_ratio": 0.5,
            "fragment_rate": 0.0,
            "architecture_index": 0.0,
            "architecture_class": "monotonous",
            "opening_distribution": {},
        }

    words = []
    for s in sentences:
        words.extend(_split_words(s))

    length_cv = compute_length_variance(sentences)
    opening_div = compute_opening_diversity(sentences)
    active_ratio = compute_active_ratio(sentences)
    fragment_rate = compute_fragment_rate(sentences)

    # Opening distribution for the report
    openers = [_classify_opener(s) for s in sentences]
    opening_dist: dict[str, int] = {}
    for o in openers:
        opening_dist[o] = opening_dist.get(o, 0) + 1

    arch_index = compute_architecture_index(
        length_cv, opening_div, active_ratio, fragment_rate
    )

    return {
        "total_sentences": len(sentences),
        "total_words": len(words),
        "length_cv": round(length_cv, 4),
        "opening_diversity": round(opening_div, 4),
        "active_ratio": round(active_ratio, 4),
        "fragment_rate": round(fragment_rate, 4),
        "architecture_index": round(arch_index, 4),
        "architecture_class": _classify_architecture(arch_index),
        "opening_distribution": opening_dist,
    }


def analyze_stroke_architecture(stroke: dict[str, Any]) -> dict[str, Any]:
    """Analyze sentence architecture for a single stroke record."""
    text = _get_stroke_text(stroke)
    return analyze_sentence_architecture(text)


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------


def compute_architecture_trend(
    strokes: list[dict[str, Any]],
    window: int = 20,
) -> dict[str, Any]:
    """Compute architecture trend over a series of strokes.

    Returns per-stroke architecture indices and a trend classification.
    """
    if not strokes:
        return {"indices": [], "trend": "no_data", "average": 0.0}

    indices = []
    for stroke in strokes:
        result = analyze_stroke_architecture(stroke)
        indices.append(result["architecture_index"])

    if len(indices) < 2:
        return {
            "indices": indices,
            "trend": "insufficient_data",
            "average": sum(indices) / len(indices) if indices else 0.0,
        }

    # Compute trend using recent window
    recent = indices[-window:]
    avg = sum(recent) / len(recent)

    # Simple trend: compare first half to second half
    mid = len(recent) // 2
    first_half = sum(recent[:mid]) / mid if mid > 0 else 0
    second_half = sum(recent[mid:]) / (len(recent) - mid) if (len(recent) - mid) > 0 else 0
    delta = second_half - first_half

    if delta > 0.05:
        trend = "improving"
    elif delta < -0.05:
        trend = "declining"
    else:
        trend = "stable"

    return {
        "indices": indices,
        "trend": trend,
        "average": round(avg, 4),
        "first_half_avg": round(first_half, 4),
        "second_half_avg": round(second_half, 4),
    }


def classify_trend(trend_data: dict[str, Any]) -> str:
    """Classify an architecture trend result."""
    return trend_data.get("trend", "unknown")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_architecture_report(result: dict[str, Any]) -> str:
    """Format an architecture analysis result as a human-readable report."""
    if result["total_sentences"] == 0:
        return "No sentences to analyze."

    lines = [
        f"Architecture: {result['architecture_class']}",
        f"  Index: {result['architecture_index']:.2f}",
        f"  Sentences: {result['total_sentences']}, Words: {result['total_words']}",
        f"  Length CV: {result['length_cv']:.3f} (higher = more varied)",
        f"  Opening diversity: {result['opening_diversity']:.3f} (1.0 = maximum variety)",
        f"  Active ratio: {result['active_ratio']:.2%}",
        f"  Fragment rate: {result['fragment_rate']:.2%}",
    ]

    if result.get("opening_distribution"):
        lines.append("  Opening patterns:")
        for cat, count in sorted(
            result["opening_distribution"].items(),
            key=lambda x: -x[1],
        ):
            lines.append(f"    {cat}: {count}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Strokes file integration
# ---------------------------------------------------------------------------


def analyze_session_architecture(
    strokes_path: str | Path | None = None,
    writer: str = "qwen",
    limit: int = 50,
) -> dict[str, Any]:
    """Analyze architecture across recent strokes from the strokes file.

    Reads the strokes.jsonl file and analyzes the most recent strokes
    for the given writer.
    """
    if strokes_path is None:
        strokes_path = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
    else:
        strokes_path = Path(strokes_path)

    if not strokes_path.exists():
        return {
            "error": f"Strokes file not found: {strokes_path}",
            "architecture_index": 0.0,
            "architecture_class": "no_data",
        }

    strokes = []
    with open(strokes_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
                if stroke.get("writer", "") == writer:
                    strokes.append(stroke)
            except json.JSONDecodeError:
                continue

    # Take the most recent `limit` strokes
    recent = strokes[-limit:] if len(strokes) > limit else strokes

    if not recent:
        return {
            "error": f"No strokes found for writer '{writer}'",
            "architecture_index": 0.0,
            "architecture_class": "no_data",
        }

    # Analyze each stroke
    results = [analyze_stroke_architecture(s) for s in recent]

    # Aggregate
    indices = [r["architecture_index"] for r in results]
    avg_index = sum(indices) / len(indices)

    return {
        "writer": writer,
        "strokes_analyzed": len(recent),
        "total_sentences": sum(r["total_sentences"] for r in results),
        "total_words": sum(r["total_words"] for r in results),
        "avg_length_cv": round(
            sum(r["length_cv"] for r in results) / len(results), 4
        ),
        "avg_opening_diversity": round(
            sum(r["opening_diversity"] for r in results) / len(results), 4
        ),
        "avg_active_ratio": round(
            sum(r["active_ratio"] for r in results) / len(results), 4
        ),
        "avg_fragment_rate": round(
            sum(r["fragment_rate"] for r in results) / len(results), 4
        ),
        "architecture_index": round(avg_index, 4),
        "architecture_class": _classify_architecture(avg_index),
        "class_distribution": _class_distribution(results),
    }


def _class_distribution(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count how many strokes fall into each architecture class."""
    dist: dict[str, int] = {}
    for r in results:
        cls = r.get("architecture_class", "unknown")
        dist[cls] = dist.get(cls, 0) + 1
    return dist
