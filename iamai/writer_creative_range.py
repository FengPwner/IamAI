"""writer_creative_range — measure writing diversity and creative breadth.

An automated writer that produces the same sentence structure, the same
vocabulary, and the same topics on every stroke is *efficient* but not
*creative*.  This module quantifies how much variety exists in the recent
output across five orthogonal dimensions:

=============================  ============================================
metric                         meaning
=============================  ============================================
vocabulary_richness            type-token ratio of unique words
sentence_length_cv             coefficient of variation of sentence lengths
topic_diversity                Shannon entropy of content-word categories
structural_variety             fraction of sentences starting with
                               different grammatical patterns
polarity_range                 spread of positive/negative sentiment
                               across strokes
=============================  ============================================

Each metric is normalized to a 0–1 score and combined into an overall
``creative_range_score`` (weighted average).

Labels
------

    ≥ 0.75   exploring    — wide creative range, diverse output
    ≥ 0.55   expressive   — good variety with some focus
    ≥ 0.35   focused      — narrower range, more consistent voice
    < 0.35   repetitive   — low diversity, possible stagnation

Usage::

    python3 -m iamai.writer_creative_range                # last 200 strokes
    python3 -m iamai.writer_creative_range -n 500        # last 500 strokes
    python3 -m iamai.writer_creative_range --json        # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_N = 200
DEFAULT_STROKES_PATH = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"

# Common English stop words (minimal set for content-word extraction)
_STOP_WORDS = frozenset(
    "a an the and or but not is are was were be been being have has had do "
    "does did will would shall should may might can could i me my we our "
    "you your he him his she her it its they them their this that these "
    "those what which who whom where when how why all each every both few "
    "more most other some such no nor only own same so than too very just "
    "about above after again am as at be before below between by during "
    "for from further get got here if in into just let like make many much "
    "new now of off on once one out over own say she should show since "
    "still take tell than then there through to up us use want way well "
    "with while while yet".split()
)

# Sentence-starting pattern categories
_START_PATTERNS = [
    (re.compile(r"^[A-Z][a-z]+ing\b"), "gerund"),
    (re.compile(r"^The\b"), "article_the"),
    (re.compile(r"^[Aa]\b"), "article_a"),
    (re.compile(r"^(When|While|After|Before|If|Unless|Although|Though|Since|Because)\b"), "subordinate"),
    (re.compile(r"^(But|And|Yet|So|Or|However|Moreover|Furthermore|Nevertheless)\b"), "conjunction"),
    (re.compile(r"^(I|We|You|He|She|It|They)\b"), "pronoun"),
    (re.compile(r"^(In|On|At|From|To|With|By|For|About|Between|Through|During|Without)\b"), "preposition"),
    (re.compile(r"^\d"), "numeric"),
    (re.compile(r"^[a-z]"), "lowercase"),
    (re.compile(r"^[A-Z]"), "capitalized"),
]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    """Split text into lowercase word tokens."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using common delimiters."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _content_words(tokens: List[str]) -> List[str]:
    """Filter tokens to content words (remove stop words and short tokens)."""
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]


def _simple_sentiment(text: str) -> float:
    """Very lightweight sentiment: +1 per positive cue, -1 per negative.

    This is intentionally simple — it's a diversity metric, not a
    sentiment analysis tool.  We just need enough signal to measure range.
    """
    positive = {
        "good", "great", "excellent", "wonderful", "beautiful", "love",
        "happy", "joy", "amazing", "brilliant", "success", "progress",
        "improve", "grow", "create", "build", "help", "solve", "clear",
        "bright", "fresh", "strong", "vivid", "rich", "deep", "warm",
        "light", "open", "free", "fast", "smooth", "clean", "easy",
    }
    negative = {
        "bad", "terrible", "awful", "poor", "ugly", "hate", "sad",
        "pain", "fear", "broken", "fail", "crash", "error", "bug",
        "stall", "stuck", "slow", "dark", "cold", "hard", "wrong",
        "lost", "miss", "dead", "waste", "leak", "corrupt", "rot",
        "blame", "shame", "dull", "weak", "flat",
    }
    tokens = set(_tokenize(text))
    pos = len(tokens & positive)
    neg = len(tokens & negative)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def vocabulary_richness(strokes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Type-token ratio across all stroke texts.

    Returns dict with ttr, unique_words, total_words, score.
    """
    all_tokens: List[str] = []
    for s in strokes:
        all_tokens.extend(_tokenize(s.get("text", "")))

    if not all_tokens:
        return {"ttr": 0.0, "unique_words": 0, "total_words": 0, "score": 0.0}

    unique = len(set(all_tokens))
    total = len(all_tokens)
    ttr = unique / total if total > 0 else 0.0

    # Score: TTR above 0.6 is excellent, below 0.2 is poor
    score = max(0.0, min(1.0, (ttr - 0.1) / 0.6))

    return {
        "ttr": round(ttr, 4),
        "unique_words": unique,
        "total_words": total,
        "score": round(score, 4),
    }


def sentence_length_cv(strokes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Coefficient of variation of sentence lengths (in words).

    High CV = sentences vary a lot in length (more dynamic writing).
    Low CV = sentences are all similar length (monotonous).

    Returns dict with mean, std, cv, score.
    """
    lengths: List[int] = []
    for s in strokes:
        sentences = _split_sentences(s.get("text", ""))
        for sent in sentences:
            words = _tokenize(sent)
            if words:
                lengths.append(len(words))

    if len(lengths) < 2:
        return {"mean": 0.0, "std": 0.0, "cv": 0.0, "score": 0.0}

    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / (len(lengths) - 1)
    std = math.sqrt(variance)
    cv = std / mean if mean > 0 else 0.0

    # Score: CV of 0.6+ is very varied, 0.1 is very uniform
    score = max(0.0, min(1.0, (cv - 0.05) / 0.55))

    return {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "cv": round(cv, 4),
        "score": round(score, 4),
    }


def topic_diversity(strokes: List[Dict[str, Any]], n_buckets: int = 10) -> Dict[str, Any]:
    """Shannon entropy of content-word distribution across hash buckets.

    Words are hashed into *n_buckets* topic buckets.  High entropy means
    content words are spread across many topics; low entropy means the
    writing keeps circling the same vocabulary.

    Returns dict with entropy, max_entropy, normalized_entropy, score.
    """
    bucket_counts: Counter = Counter()
    for s in strokes:
        tokens = _tokenize(s.get("text", ""))
        content = _content_words(tokens)
        for w in content:
            bucket_counts[hash(w) % n_buckets] += 1

    total = sum(bucket_counts.values())
    if total == 0:
        return {
            "entropy": 0.0,
            "max_entropy": math.log2(n_buckets),
            "normalized_entropy": 0.0,
            "score": 0.0,
        }

    entropy = 0.0
    for count in bucket_counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    max_entropy = math.log2(n_buckets)
    normalized = entropy / max_entropy if max_entropy > 0 else 0.0

    # Score directly from normalized entropy
    score = max(0.0, min(1.0, normalized))

    return {
        "entropy": round(entropy, 4),
        "max_entropy": round(max_entropy, 4),
        "normalized_entropy": round(normalized, 4),
        "score": round(score, 4),
    }


def structural_variety(strokes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How many different sentence-starting patterns are used.

    Each sentence is classified by its opening pattern.  The score
    reflects both the number of distinct patterns used and how evenly
    sentences are distributed across them.

    Returns dict with patterns_found, total_patterns, distribution, score.
    """
    pattern_counts: Counter = Counter()
    for s in strokes:
        sentences = _split_sentences(s.get("text", ""))
        for sent in sentences:
            if not sent.strip():
                continue
            matched = False
            for regex, label in _START_PATTERNS:
                if regex.search(sent):
                    pattern_counts[label] += 1
                    matched = True
                    break
            if not matched:
                pattern_counts["other"] += 1

    total_patterns = len(_START_PATTERNS) + 1  # +1 for "other"
    found = len(pattern_counts)

    if found == 0:
        return {
            "patterns_found": 0,
            "total_patterns": total_patterns,
            "distribution": {},
            "score": 0.0,
        }

    # Combine coverage (what fraction of patterns are used) with evenness
    coverage = found / total_patterns
    total = sum(pattern_counts.values())
    evenness = 0.0
    if total > 0:
        max_fraction = max(c / total for c in pattern_counts.values())
        # Perfect evenness: all patterns have equal count → max_fraction = 1/found
        ideal = 1.0 / found if found > 0 else 1.0
        evenness = ideal / max_fraction if max_fraction > 0 else 0.0

    score = max(0.0, min(1.0, 0.6 * coverage + 0.4 * evenness))

    return {
        "patterns_found": found,
        "total_patterns": total_patterns,
        "distribution": dict(pattern_counts.most_common()),
        "score": round(score, 4),
    }


def polarity_range(strokes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Range of sentiment polarity across strokes.

    Each stroke gets a simple sentiment score.  The metric measures the
    spread: a writer that only produces neutral text scores low; one
    that alternates between enthusiastic and critical scores high.

    Returns dict with min, max, range, std, score.
    """
    scores: List[float] = []
    for s in strokes:
        text = s.get("text", "")
        if text.strip():
            scores.append(_simple_sentiment(text))

    if len(scores) < 2:
        return {"min": 0.0, "max": 0.0, "range": 0.0, "std": 0.0, "score": 0.0}

    lo = min(scores)
    hi = max(scores)
    rng = hi - lo
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / (len(scores) - 1)
    std = math.sqrt(variance)

    # Score: range of 1.0+ is excellent spread, 0.1 is very narrow
    score = max(0.0, min(1.0, rng / 1.0))

    return {
        "min": round(lo, 4),
        "max": round(hi, 4),
        "range": round(rng, 4),
        "std": round(std, 4),
        "score": round(score, 4),
    }


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "vocabulary_richness": 0.25,
    "sentence_length_cv": 0.20,
    "topic_diversity": 0.25,
    "structural_variety": 0.15,
    "polarity_range": 0.15,
}


def creative_range_score(metrics: Dict[str, Dict[str, Any]]) -> float:
    """Weighted average of individual metric scores."""
    total = 0.0
    weight_sum = 0.0
    for name, weight in _WEIGHTS.items():
        if name in metrics and "score" in metrics[name]:
            total += weight * metrics[name]["score"]
            weight_sum += weight
    if weight_sum == 0:
        return 0.0
    return round(total / weight_sum, 4)


def creative_label(score: float) -> str:
    """Human-readable label for the creative range score."""
    if score >= 0.75:
        return "exploring"
    if score >= 0.55:
        return "expressive"
    if score >= 0.35:
        return "focused"
    return "repetitive"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def load_strokes(path: Optional[Path] = None, n: int = DEFAULT_N) -> List[Dict[str, Any]]:
    """Load the last *n* strokes from the JSONL file."""
    p = path or DEFAULT_STROKES_PATH
    if not p.exists():
        return []
    lines = p.read_text().strip().splitlines()
    strokes = []
    for line in lines[-n:]:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def creative_range_report(
    n: int = DEFAULT_N,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate a full creative range report."""
    strokes = load_strokes(path=path, n=n)
    if not strokes:
        return {
            "strokes_analysed": 0,
            "vocabulary_richness": {"score": 0.0},
            "sentence_length_cv": {"score": 0.0},
            "topic_diversity": {"score": 0.0},
            "structural_variety": {"score": 0.0},
            "polarity_range": {"score": 0.0},
            "creative_range_score": 0.0,
            "label": "repetitive",
        }

    metrics = {
        "vocabulary_richness": vocabulary_richness(strokes),
        "sentence_length_cv": sentence_length_cv(strokes),
        "topic_diversity": topic_diversity(strokes),
        "structural_variety": structural_variety(strokes),
        "polarity_range": polarity_range(strokes),
    }
    score = creative_range_score(metrics)
    label = creative_label(score)

    return {
        "strokes_analysed": len(strokes),
        **metrics,
        "creative_range_score": score,
        "label": label,
    }


def creative_range_summary(report: Dict[str, Any]) -> str:
    """One-line human-readable summary."""
    n = report.get("strokes_analysed", 0)
    score = report.get("creative_range_score", 0)
    label = report.get("label", "unknown")
    vr = report.get("vocabulary_richness", {}).get("score", 0)
    td = report.get("topic_diversity", {}).get("score", 0)
    sv = report.get("structural_variety", {}).get("score", 0)
    return (
        f"creative range {label}: {n} strokes, "
        f"score {score:.2f}, "
        f"vocab {vr:.2f}, topics {td:.2f}, structure {sv:.2f}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure writing diversity and creative breadth.",
    )
    parser.add_argument(
        "-n", type=int, default=DEFAULT_N,
        help=f"Number of recent strokes to analyse (default {DEFAULT_N}).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full report as JSON.",
    )
    args = parser.parse_args(argv)

    report = creative_range_report(n=args.n)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(creative_range_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
