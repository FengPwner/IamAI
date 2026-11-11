#!/usr/bin/env python3
"""writer_restraint — measure whether writing trusts the reader.

Restraint is about *knowing when to stop*.  Restrained prose makes its
point and moves on.  Unrestrained prose over-explains, over-qualifies,
restates in simpler terms, piles on hedges, and signals — at every turn —
that the writer does not trust the reader to follow.

This module is orthogonal to the other writer metrics:

- **concision** tracks whether prose uses *more words than needed*.
  A text can be concise (few words) while still over-explaining (those
  few words restate what was already said).  Concision is about economy;
  restraint is about *trusting the reader*.

- **specificity** tracks whether prose uses *concrete, precise language*.
  A text can be specific (names, numbers, dates) while being unrestrained
  (every specific claim followed by three qualifying clauses).
  Specificity is about precision; restraint is about knowing when
  precision is sufficient.

- **readability** tracks whether prose is *easy to parse*.  A text can
  be readable (short sentences, simple words) while being unrestrained
  (each simple sentence restates the last).  Readability is about access;
  restraint is about *respect for the reader's intelligence*.

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A writer can have high clarity (no near-duplicates) while each stroke
  over-explains its single idea.  Clarity is about uniqueness; restraint
  is about not belaboring the unique idea.

- **grounding_density** tracks whether claims are *anchored in evidence*.
  A text can be well-grounded while being unrestrained (every piece of
  evidence introduced, then explained, then re-explained).  Grounding
  is about support; restraint is about not over-supporting.

Restraint asks: **does the writer stop when the point is made, or keep
going as if the reader might miss it?**

Four signals are tracked:

1. **Reader distrust density** — frequency per hundred words of phrases
   that signal the writer is re-explaining: "in other words", "that is
   to say", "to put it simply", "what this means is", "in simpler
   terms", "to put it another way", "basically", "essentially",
   "fundamentally", "at its core", "at the end of the day".  These
   phrases announce that the writer is about to repeat something.

2. **Qualifier stacking density** — instances where two or more
   qualifiers/hedges appear within a five-word window.  "Somewhat
   fairly reasonable" stacks three; "quite possibly the most" stacks
   two.  Each additional qualifier signals more anxiety about being
   misunderstood.

3. **Restatement ratio** — fraction of sentences that substantially
   overlap in content with the preceding sentence.  Measured via
   Jaccard similarity on content words (nouns, verbs, adjectives).
   A sentence that shares > 0.50 content-word overlap with its
   predecessor is likely restating rather than advancing.

4. **Parenthetical density** — frequency of parenthetical asides
   (text within parentheses, em-dash pairs, or comma-bracketed
   appositives) per hundred words.  Occasional parentheticals add
   precision; excessive ones suggest the writer cannot resist adding
   "one more thing" to every sentence.

The **restraint_index** is computed as a weighted composite:

    index = (1 - reader_distrust_norm) * 0.35
          + (1 - qualifier_stack_norm) * 0.25
          + (1 - restatement_ratio)    * 0.25
          + (1 - parenthetical_norm)   * 0.15

Classified as:

- **restrained** (>= 0.80): writing makes its point and stops; the
  writer trusts the reader to follow without constant re-explanation.

- **measured** (0.65 <= index < 0.80): mostly disciplined; occasional
  over-explanation but the writer generally knows when to move on.

- **over-eager** (0.50 <= index < 0.65): noticeable tendency to
  restate, qualify, and explain; the reader feels guided rather than
  trusted.

- **anxious** (0.35 <= index < 0.50): constant re-explanation and
  qualifier stacking; every claim arrives with a safety net of hedges
  and restatements; the writer does not trust the reader at all.

- **smothering** (index < 0.35): the prose is buried under layers of
  re-explanation, qualification, and parenthetical asides; the original
  point is lost in the effort to make it unmistakable.

Reference: Orwell's Rule 2: "If it is possible to cut a word out,
always cut it out."  Applied to autonomous writing: a writer that
cannot restrain itself produces output that is correct, thorough, and
exhausting — technically complete, rhetorically claustrophobic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Reader distrust phrases — signals the writer is about to re-explain
# ---------------------------------------------------------------------------

READER_DISTRUST_PHRASES: list[re.Pattern] = [
    re.compile(r"\bin\s+other\s+words\b", re.IGNORECASE),
    re.compile(r"\bthat\s+is\s+to\s+say\b", re.IGNORECASE),
    re.compile(r"\bto\s+put\s+it\s+simply\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+this\s+means\s+is\b", re.IGNORECASE),
    re.compile(r"\bin\s+simpler\s+terms\b", re.IGNORECASE),
    re.compile(r"\bto\s+put\s+it\s+another\s+way\b", re.IGNORECASE),
    re.compile(r"\bbasically\b", re.IGNORECASE),
    re.compile(r"\bessentially\b", re.IGNORECASE),
    re.compile(r"\bfundamentally\b", re.IGNORECASE),
    re.compile(r"\bat\s+its\s+core\b", re.IGNORECASE),
    re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day\b", re.IGNORECASE),
    re.compile(r"\bin\s+essence\b", re.IGNORECASE),
    re.compile(r"\bto\s+summarize\b", re.IGNORECASE),
    re.compile(r"\bputting\s+it\s+simply\b", re.IGNORECASE),
    re.compile(r"\bthe\s+point\s+is\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+i'?m\s+saying\s+is\b", re.IGNORECASE),
    re.compile(r"\blet\s+me\s+be\s+clear\b", re.IGNORECASE),
    re.compile(r"\bin\s+plain\s+terms\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Qualifier words — hedges, intensifiers, epistemic markers
# ---------------------------------------------------------------------------

QUALIFIER_WORDS: set[str] = {
    "somewhat", "fairly", "quite", "rather", "possibly", "probably",
    "perhaps", "maybe", "arguably", "seemingly", "apparently",
    "presumably", "supposedly", "allegedly", "ostensibly", "virtually",
    "practically", "nearly", "almost", "barely", "hardly", "scarcely",
    "slightly", "mildly", "marginally", "moderately", "reasonably",
    "relatively", "comparatively", "sufficiently", "adequately",
    "notably", "particularly", "especially", "certainly", "surely",
    "undeniably", "unquestionably", "indubitably",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z']+", re.IGNORECASE)
_CONTENT_POS_RE = re.compile(r"\b[a-z']+\b", re.IGNORECASE)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_words(text: str) -> list[str]:
    """Lowercased word list (contractions kept, numbers dropped)."""
    return [w.lower() for w in _WORD_RE.findall(text) if not w.isdigit()]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on trailing punctuation + space."""
    parts = _SENT_SPLIT_RE.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


def _content_words(words: list[str]) -> set[str]:
    """Approximate content-word set: drop articles, prepositions, pronouns."""
    stop = {
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "as", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "it", "its", "this", "that", "these", "those", "i", "we",
        "you", "he", "she", "they", "me", "him", "her", "us", "them",
        "my", "your", "his", "our", "their", "and", "or", "but", "not",
        "no", "nor", "so", "if", "then", "than", "too", "very",
    }
    return {w for w in words if w not in stop and len(w) > 1}


def _get_stroke_text(stroke: dict[str, Any]) -> str:
    """Extract text body from a stroke dict."""
    return str(stroke.get("text", "") or stroke.get("body", "") or "")


# ---------------------------------------------------------------------------
# Signal 1: Reader distrust density
# ---------------------------------------------------------------------------


def count_distrust_hits(text: str) -> int:
    """Count reader-distrust phrase occurrences."""
    hits = 0
    for pat in READER_DISTRUST_PHRASES:
        hits += len(pat.findall(text))
    return hits


def compute_reader_distrust_density(text: str) -> float:
    """Reader distrust phrases per 100 words."""
    words = _split_words(text)
    n = len(words)
    if n < 5:
        return 0.0
    return (count_distrust_hits(text) / n) * 100.0


# ---------------------------------------------------------------------------
# Signal 2: Qualifier stacking density
# ---------------------------------------------------------------------------


def count_qualifier_stacks(words: list[str], window: int = 5) -> int:
    """Count windows where 2+ qualifiers appear within `window` words."""
    if len(words) < window:
        return 0
    stacks = 0
    for i in range(len(words) - window + 1):
        chunk = words[i : i + window]
        qualifiers = [w for w in chunk if w in QUALIFIER_WORDS]
        if len(qualifiers) >= 2:
            stacks += 1
    return stacks


def compute_qualifier_stack_density(text: str) -> float:
    """Qualifier stacks per 100 words."""
    words = _split_words(text)
    n = len(words)
    if n < 5:
        return 0.0
    stacks = count_qualifier_stacks(words)
    return (stacks / n) * 100.0


# ---------------------------------------------------------------------------
# Signal 3: Restatement ratio
# ---------------------------------------------------------------------------


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def compute_restatement_ratio(text: str) -> float:
    """Fraction of sentences that restate the preceding sentence."""
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 0.0
    restatements = 0
    prev_words = _content_words(_split_words(sentences[0]))
    for sent in sentences[1:]:
        curr_words = _content_words(_split_words(sent))
        if _jaccard(prev_words, curr_words) > 0.50:
            restatements += 1
        prev_words = curr_words
    return restatements / (len(sentences) - 1)


# ---------------------------------------------------------------------------
# Signal 4: Parenthetical density
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\([^)]+\)")
_EM_DASH_RE = re.compile(r"—[^—]+—|–[^–]+–")


def count_parentheticals(text: str) -> int:
    """Count parenthetical asides (parens + em-dash pairs)."""
    return len(_PAREN_RE.findall(text)) + len(_EM_DASH_RE.findall(text))


def compute_parenthetical_density(text: str) -> float:
    """Parenthetical asides per 100 words."""
    words = _split_words(text)
    n = len(words)
    if n < 5:
        return 0.0
    return (count_parentheticals(text) / n) * 100.0


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------

# Normalization ceilings (empirical; values above these map to 1.0)
_DISTRUST_CEIL = 3.0    # 3 phrases per 100 words is very high
_STACK_CEIL = 4.0       # 4 stacks per 100 words is very high
_PAREN_CEIL = 5.0       # 5 parentheticals per 100 words is very high


def compute_restraint_index(
    distrust_density: float,
    stack_density: float,
    restatement_ratio: float,
    parenthetical_density: float,
) -> float:
    """Weighted composite restraint index (0-1, higher = more restrained)."""
    distrust_norm = min(distrust_density / _DISTRUST_CEIL, 1.0)
    stack_norm = min(stack_density / _STACK_CEIL, 1.0)
    paren_norm = min(parenthetical_density / _PAREN_CEIL, 1.0)

    index = (
        (1.0 - distrust_norm) * 0.35
        + (1.0 - stack_norm) * 0.25
        + (1.0 - restatement_ratio) * 0.25
        + (1.0 - paren_norm) * 0.15
    )
    return round(max(0.0, min(1.0, index)), 4)


def classify_restraint(index: float) -> str:
    """Classify restraint level from composite index."""
    if index >= 0.80:
        return "restrained"
    if index >= 0.65:
        return "measured"
    if index >= 0.50:
        return "over-eager"
    if index >= 0.35:
        return "anxious"
    return "smothering"


# ---------------------------------------------------------------------------
# Full analysis
# ---------------------------------------------------------------------------


def compute_restraint_metrics(text: str) -> dict[str, float]:
    """Compute all four signals for a block of text."""
    distrust = compute_reader_distrust_density(text)
    stack = compute_qualifier_stack_density(text)
    restatement = compute_restatement_ratio(text)
    paren = compute_parenthetical_density(text)
    return {
        "reader_distrust_density": round(distrust, 4),
        "qualifier_stack_density": round(stack, 4),
        "restatement_ratio": round(restatement, 4),
        "parenthetical_density": round(paren, 4),
    }


def analyze_stroke_restraint(stroke: dict[str, Any]) -> dict[str, Any]:
    """Analyze restraint for a single stroke."""
    text = _get_stroke_text(stroke)
    if not text.strip():
        return {
            "reader_distrust_density": 0.0,
            "qualifier_stack_density": 0.0,
            "restatement_ratio": 0.0,
            "parenthetical_density": 0.0,
            "restraint_index": 1.0,
            "restraint_class": "restrained",
        }
    metrics = compute_restraint_metrics(text)
    index = compute_restraint_index(
        metrics["reader_distrust_density"],
        metrics["qualifier_stack_density"],
        metrics["restatement_ratio"],
        metrics["parenthetical_density"],
    )
    metrics["restraint_index"] = index
    metrics["restraint_class"] = classify_restraint(index)
    return metrics


def analyze_session_restraint(strokes: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate restraint across a session of strokes."""
    all_text = " ".join(_get_stroke_text(s) for s in strokes)
    if not all_text.strip():
        return {
            "reader_distrust_density": 0.0,
            "qualifier_stack_density": 0.0,
            "restatement_ratio": 0.0,
            "parenthetical_density": 0.0,
            "restraint_index": 1.0,
            "restraint_class": "restrained",
            "n_strokes": 0,
        }
    metrics = compute_restraint_metrics(all_text)
    index = compute_restraint_index(
        metrics["reader_distrust_density"],
        metrics["qualifier_stack_density"],
        metrics["restatement_ratio"],
        metrics["parenthetical_density"],
    )
    metrics["restraint_index"] = index
    metrics["restraint_class"] = classify_restraint(index)
    metrics["n_strokes"] = len(strokes)
    return metrics


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_restraint_trend(
    strokes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute restraint trend over recent strokes."""
    if not strokes:
        return {
            "trend": "no_data",
            "recent_mean": 0.0,
            "older_mean": 0.0,
            "delta": 0.0,
        }
    indices = []
    for s in strokes:
        result = analyze_stroke_restraint(s)
        indices.append(result["restraint_index"])

    mid = max(1, len(indices) // 2)
    recent = indices[mid:]
    older = indices[:mid]

    recent_mean = sum(recent) / len(recent) if recent else 0.0
    older_mean = sum(older) / len(older) if older else 0.0
    delta = recent_mean - older_mean

    if delta > 0.05:
        trend = "improving"
    elif delta < -0.05:
        trend = "worsening"
    else:
        trend = "stable"

    return {
        "trend": trend,
        "recent_mean": round(recent_mean, 4),
        "older_mean": round(older_mean, 4),
        "delta": round(delta, 4),
    }


def classify_trend(delta: float) -> str:
    """Classify trend from delta."""
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "worsening"
    return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_restraint_report(metrics: dict[str, Any]) -> str:
    """Human-readable restraint report."""
    lines = [
        f"Restraint: {metrics.get('restraint_class', '?')} "
        f"(index={metrics.get('restraint_index', 0):.2f})",
        f"  reader distrust:  {metrics.get('reader_distrust_density', 0):.2f}/100w",
        f"  qualifier stacks: {metrics.get('qualifier_stack_density', 0):.2f}/100w",
        f"  restatement:      {metrics.get('restatement_ratio', 0):.2f}",
        f"  parentheticals:   {metrics.get('parenthetical_density', 0):.2f}/100w",
    ]
    return "\n".join(lines)
