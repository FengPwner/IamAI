#!/usr/bin/env python3
"""writer_discourse_markers — measure argumentative connective density in prose.

Discourse markers are the signposts of written argumentation.
"However" signals contrast; "therefore" signals consequence;
"moreover" signals addition; "for example" signals illustration.
These connectives tell readers how each sentence relates to what
came before — they are the mortar between propositional bricks.

Too few discourse markers and prose feels choppy or stream-of-
consciousness: ideas appear without explicit relationships.
Too many and prose feels over-signposted or condescending:
every logical step is announced as if the reader could not
infer the connection independently.

This module detects discourse markers across eight functional
categories:

**Additive** (adding information):
- moreover, furthermore, additionally, also, besides, in addition,
  what is more, not only...but also, as well as, equally important

**Adversative** (contrasting ideas):
- however, nevertheless, nonetheless, on the other hand, conversely,
  in contrast, by contrast, whereas, while, although, even though,
  despite, in spite of, yet, still, nonetheless

**Causal** (showing cause/effect):
- therefore, thus, consequently, as a result, hence, accordingly,
  for this reason, because of this, due to this, so

**Illustrative** (providing examples):
- for example, for instance, to illustrate, specifically, namely,
  in particular, such as, as an illustration, to demonstrate

**Sequential** (ordering ideas):
- first, second, third, finally, next, then, subsequently,
  meanwhile, in the meantime, after that, before that

**Summative** (concluding/restating):
- in conclusion, to summarize, in summary, in short, in brief,
  to sum up, overall, in other words, that is to say

**Concessive** (acknowledging limitations):
- admittedly, granted, of course, to be sure, it is true that,
  while it is true, granted that, even if

**Clarifying** (rephrasing/specifying):
- that is, in other words, to put it another way, more precisely,
  specifically, to clarify, put differently

For each text, the module computes:
- **total_markers**: raw count of all discourse markers found
- **marker_rate**: markers per 100 words
- **category_counts**: breakdown by functional category
- **category_distribution**: normalized distribution (entropy proxy)
- **top_markers**: 5 most frequent markers
- **classification**: one of sparse, lean, adequate, rich, over-signposted

The classification uses marker_rate:

| marker_rate | classification    |
|-------------|-------------------|
| < 0.3       | sparse            |
| 0.3–1.0     | lean              |
| 1.0–2.5     | adequate          |
| 2.5–4.0     | rich              |
| > 4.0       | over_signposted   |

This metric is orthogonal to verbosity (word count), formality
(register), and hedging language. A short informal text can be
rich in discourse markers; a long formal paper can be sparse.

written by Qwen during manual caretaker visit 661, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import Counter


# ── marker categories ────────────────────────────────────────────

# Single-word markers (case-insensitive)
_CATEGORY_WORDS: Dict[str, set] = {
    "additive": {
        "moreover", "furthermore", "additionally", "besides",
    },
    "adversative": {
        "however", "nevertheless", "nonetheless", "conversely",
        "whereas", "although", "yet", "still",
    },
    "causal": {
        "therefore", "thus", "consequently", "hence", "accordingly",
        "so",
    },
    "sequential": {
        "first", "second", "third", "finally", "next", "then",
        "subsequently", "meanwhile",
    },
    "summative": {
        "overall",
    },
    "concessive": {
        "admittedly", "granted",
    },
}

# Multi-word phrase markers (regex patterns with category)
_CATEGORY_PHRASES: List[Tuple[str, str]] = [
    # additive
    (r"\bin\s+addition\b", "additive"),
    (r"\bwhat\s+is\s+more\b", "additive"),
    (r"\bnot\s+only\b", "additive"),
    (r"\bas\s+well\s+as\b", "additive"),
    (r"\bequally\s+important\b", "additive"),
    # adversative
    (r"\bon\s+the\s+other\s+hand\b", "adversative"),
    (r"\bin\s+contrast\b", "adversative"),
    (r"\bby\s+contrast\b", "adversative"),
    (r"\beven\s+though\b", "adversative"),
    (r"\bin\s+spite\s+of\b", "adversative"),
    (r"\bdespite\s+(?:this|that)\b", "adversative"),
    # causal
    (r"\bas\s+a\s+result\b", "causal"),
    (r"\bfor\s+this\s+reason\b", "causal"),
    (r"\bbecause\s+of\s+this\b", "causal"),
    (r"\bdue\s+to\s+this\b", "causal"),
    # illustrative
    (r"\bfor\s+example\b", "illustrative"),
    (r"\bfor\s+instance\b", "illustrative"),
    (r"\bto\s+illustrate\b", "illustrative"),
    (r"\bin\s+particular\b", "illustrative"),
    (r"\bsuch\s+as\b", "illustrative"),
    (r"\bas\s+an\s+illustration\b", "illustrative"),
    (r"\bto\s+demonstrate\b", "illustrative"),
    # sequential
    (r"\bin\s+the\s+meantime\b", "sequential"),
    (r"\bafter\s+that\b", "sequential"),
    (r"\bbefore\s+that\b", "sequential"),
    # summative
    (r"\bin\s+conclusion\b", "summative"),
    (r"\bto\s+summarize\b", "summative"),
    (r"\bin\s+summary\b", "summative"),
    (r"\bin\s+short\b", "summative"),
    (r"\bin\s+brief\b", "summative"),
    (r"\bto\s+sum\s+up\b", "summative"),
    (r"\bin\s+other\s+words\b", "summative"),
    (r"\bthat\s+is\s+to\s+say\b", "summative"),
    # concessive
    (r"\bof\s+course\b", "concessive"),
    (r"\bto\s+be\s+sure\b", "concessive"),
    (r"\bit\s+is\s+true\s+that\b", "concessive"),
    (r"\bgranted\s+that\b", "concessive"),
    (r"\beven\s+if\b", "concessive"),
    # clarifying
    (r"\bthat\s+is\b", "clarifying"),
    (r"\bto\s+put\s+it\s+another\s+way\b", "clarifying"),
    (r"\bmore\s+precisely\b", "clarifying"),
    (r"\bto\s+clarify\b", "clarifying"),
    (r"\bput\s+differently\b", "clarifying"),
]


# ── result dataclass ─────────────────────────────────────────────

@dataclass
class DiscourseMarkerResult:
    """Result of discourse marker analysis."""
    total_markers: int = 0
    total_words: int = 0
    marker_rate: float = 0.0
    category_counts: Dict[str, int] = field(default_factory=dict)
    category_distribution: Dict[str, float] = field(default_factory=dict)
    marker_counts: Dict[str, int] = field(default_factory=dict)
    top_markers: List[Tuple[str, int]] = field(default_factory=list)
    classification: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "total_markers": self.total_markers,
            "total_words": self.total_words,
            "marker_rate": round(self.marker_rate, 3),
            "category_counts": self.category_counts,
            "category_distribution": {
                k: round(v, 3) for k, v in self.category_distribution.items()
            },
            "top_markers": self.top_markers,
            "classification": self.classification,
        }


# ── internal helpers ─────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Split text into words, stripping punctuation."""
    return [w.strip(".,;:!?\"'()[]{}").lower()
            for w in text.split() if w.strip(".,;:!?\"'()[]{}")]


def _find_word_markers(words: List[str]) -> List[Tuple[str, str]]:
    """Find single-word discourse markers. Returns (marker, category)."""
    found = []
    for w in words:
        for cat, wordset in _CATEGORY_WORDS.items():
            if w in wordset:
                found.append((w, cat))
    return found


def _find_phrase_markers(text: str) -> List[Tuple[str, str]]:
    """Find multi-word discourse markers. Returns (marker, category)."""
    text_lower = text.lower()
    found = []
    for pattern, cat in _CATEGORY_PHRASES:
        matches = re.findall(pattern, text_lower)
        for m in matches:
            found.append((m, cat))
    return found


def _classify(rate: float) -> str:
    """Classify based on marker rate per 100 words."""
    if rate < 0.3:
        return "sparse"
    elif rate < 1.0:
        return "lean"
    elif rate < 2.5:
        return "adequate"
    elif rate < 4.0:
        return "rich"
    else:
        return "over_signposted"


# ── public API ───────────────────────────────────────────────────

def measure_discourse_markers(text: str) -> DiscourseMarkerResult:
    """Analyze discourse marker usage in text.

    Args:
        text: input text to analyze

    Returns:
        DiscourseMarkerResult with counts, rates, and classification
    """
    if not text or not text.strip():
        return DiscourseMarkerResult(classification="unknown")

    words = _tokenize(text)
    if not words:
        return DiscourseMarkerResult(classification="unknown")

    # Find all markers
    word_markers = _find_word_markers(words)
    phrase_markers = _find_phrase_markers(text)
    all_markers = word_markers + phrase_markers

    if not all_markers:
        return DiscourseMarkerResult(
            total_words=len(words),
            classification="sparse",
        )

    # Count by category
    cat_counter: Counter = Counter()
    marker_counter: Counter = Counter()
    for marker, cat in all_markers:
        cat_counter[cat] += 1
        marker_counter[marker] += 1

    total = len(all_markers)
    rate = (total / len(words)) * 100  # per 100 words

    # Category distribution (normalized)
    distribution = {cat: count / total for cat, count in cat_counter.items()}

    # Top 5 markers
    top = marker_counter.most_common(5)

    return DiscourseMarkerResult(
        total_markers=total,
        total_words=len(words),
        marker_rate=rate,
        category_counts=dict(cat_counter),
        category_distribution=distribution,
        marker_counts=dict(marker_counter),
        top_markers=top,
        classification=_classify(rate),
    )


if __name__ == "__main__":
    import json
    sample = (
        "First, we need to understand the problem. However, the data is incomplete. "
        "For example, the logs show timeouts but not their cause. Therefore, we should "
        "add more instrumentation. Moreover, the error handling needs improvement. "
        "In conclusion, we have three action items: add logging, improve errors, and "
        "write tests. In short, the system works but needs hardening."
    )
    result = measure_discourse_markers(sample)
    print(json.dumps(result.to_dict(), indent=2))
