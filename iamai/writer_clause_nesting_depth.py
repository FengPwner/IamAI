#!/usr/bin/env python3
"""writer_clause_nesting_depth — measure how deeply clauses are embedded in prose.

Clause nesting depth is a proxy for syntactic complexity.  A sentence
like "The server crashed" has depth 1 — one independent clause, no
embedding.  A sentence like "The server crashed because the disk filled
up while the backup was running" has depth 3 — one main clause plus
two levels of subordination.

Deep nesting is not inherently bad.  Complex ideas often require
complex syntax.  But consistently deep nesting makes prose hard to
parse: readers must hold multiple unfinished clauses in working memory
before the sentence resolves.  Strunk and White's advice — "omit
needless words" — applies to clauses too.

This module approximates clause nesting depth without a full syntactic
parser.  It detects clause boundaries via subordinating conjunctions
(because, although, while, if, since, when, unless, etc.) and relative
pronouns (who, which, that, whose, where, when), then tracks depth by
maintaining a stack across a sentence.

What it measures:

- **max_depth**: deepest nesting level found in any sentence
- **mean_depth**: average depth across all sentences
- **deep_clause_ratio**: fraction of sentences with depth >= 3
- **depth_distribution**: histogram of depth levels (1, 2, 3, 4+)
- **subordinator_counts**: breakdown by subordinating conjunction type
- **relative_clause_count**: number of relative clauses detected
- **classification**: one of flat | simple | layered | complex | labyrinthine

The classification uses mean_depth:

    flat:          mean_depth < 1.3
    simple:        1.3 <= mean_depth < 1.8
    layered:       1.8 <= mean_depth < 2.5
    complex:       2.5 <= mean_depth < 3.5
    labyrinthine:  mean_depth >= 3.5

This metric is orthogonal to verbosity (word count), formality
(register), and discourse marker density.  A short sentence can be
deeply nested; a long sentence can be a string of independent clauses.

written by Qwen during manual caretaker visit 662, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from collections import Counter


# ── subordinating conjunctions ──────────────────────────────────
# These words, when they appear at the start of a clause or mid-
# sentence, signal a subordinate (dependent) clause that increases
# nesting depth.

_SUBORDINATORS = {
    # Causal
    "because", "since", "as", "given that", "seeing that",
    # Concessive
    "although", "though", "even though", "while", "whilst",
    "whereas", "notwithstanding",
    # Conditional
    "if", "unless", "provided", "providing", "supposing",
    "whether", "in case",
    # Temporal
    "when", "whenever", "before", "after", "until", "till",
    "once", "as soon as", "as long as", "by the time",
    # Purpose / result
    "so that", "in order that", "lest",
    # Manner
    "as if", "as though",
}

# Single-word subordinators for token-level matching
_SUBORDINATOR_WORDS = {
    "because", "since", "although", "though", "while", "whilst",
    "whereas", "unless", "whether", "before", "after", "until",
    "till", "once", "whenever", "lest", "if", "provided",
    "providing", "supposing",
}

# Multi-word subordinators (checked as phrase patterns)
_SUBORDINATOR_PHRASES = [
    (re.compile(r"\beven though\b", re.IGNORECASE), "even though"),
    (re.compile(r"\bgiven that\b", re.IGNORECASE), "given that"),
    (re.compile(r"\bseeing that\b", re.IGNORECASE), "seeing that"),
    (re.compile(r"\bas soon as\b", re.IGNORECASE), "as soon as"),
    (re.compile(r"\bas long as\b", re.IGNORECASE), "as long as"),
    (re.compile(r"\bby the time\b", re.IGNORECASE), "by the time"),
    (re.compile(r"\bso that\b", re.IGNORECASE), "so that"),
    (re.compile(r"\bin order that\b", re.IGNORECASE), "in order that"),
    (re.compile(r"\bas if\b", re.IGNORECASE), "as if"),
    (re.compile(r"\bas though\b", re.IGNORECASE), "as though"),
    (re.compile(r"\bin case\b", re.IGNORECASE), "in case"),
    (re.compile(r"\bnotwithstanding\b", re.IGNORECASE), "notwithstanding"),
]


# ── relative pronouns ───────────────────────────────────────────
# These signal relative clauses, which add a layer of embedding.

_RELATIVE_PRONOUNS = {"who", "whom", "whose", "which", "that", "where", "when"}

# Words that look like relative pronouns but often aren't
_RELATIVE_FALSE_POSITIVES = {
    "that": {
        # "that" as demonstrative: "that book", "that idea"
        # "that" as complementizer: "I think that..."
        # We use a heuristic: "that" after a noun is likely relative
    },
    "when": {
        # "when" can be interrogative: "I asked when..."
    },
    "where": {
        # "where" can be interrogative: "I asked where..."
    },
}


# ── sentence splitting ─────────────────────────────────────────

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


# ── data class ─────────────────────────────────────────────────

@dataclass
class ClauseNestingResult:
    """Result of clause nesting depth analysis."""
    max_depth: int = 0
    mean_depth: float = 0.0
    total_sentences: int = 0
    deep_clause_ratio: float = 0.0  # fraction with depth >= 3
    depth_distribution: Dict[int, int] = field(default_factory=dict)
    subordinator_counts: Dict[str, int] = field(default_factory=dict)
    relative_clause_count: int = 0
    sentence_depths: List[int] = field(default_factory=list)
    classification: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "max_depth": self.max_depth,
            "mean_depth": round(self.mean_depth, 2),
            "total_sentences": self.total_sentences,
            "deep_clause_ratio": round(self.deep_clause_ratio, 4),
            "depth_distribution": {
                str(k): v for k, v in sorted(self.depth_distribution.items())
            },
            "subordinator_counts": dict(self.subordinator_counts),
            "relative_clause_count": self.relative_clause_count,
            "classification": self.classification,
        }


# ── internal helpers ───────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation boundaries."""
    text = text.strip()
    if not text:
        return []
    sentences = _SENTENCE_END_RE.split(text)
    return [s.strip() for s in sentences if s.strip()]


def _count_clauses_in_sentence(sentence: str) -> Tuple[int, List[str], int]:
    """Estimate clause nesting depth in a single sentence.

    Returns:
        (max_depth, subordinators_found, relative_count)
    """
    words = [w.strip(".,;:!?\"'()[]{}").lower()
             for w in sentence.split()
             if w.strip(".,;:!?\"'()[]{}")]

    if not words:
        return (1, [], 0)

    # Start at depth 1 (the main clause)
    depth = 1
    max_d = 1
    subordinators_found: List[str] = []
    relative_count = 0

    # Check for multi-word subordinators first
    phrase_hits: List[str] = []
    for pattern, label in _SUBORDINATOR_PHRASES:
        matches = pattern.findall(sentence)
        for _ in matches:
            phrase_hits.append(label)
            depth += 1
            max_d = max(max_d, depth)
            subordinators_found.append(label)

    # Remove multi-word phrases from consideration to avoid double-counting
    # Build a set of words that are part of multi-word phrases
    phrase_words = set()
    for phrase in phrase_hits:
        for w in phrase.split():
            phrase_words.add(w.lower())

    # Check single-word subordinators
    for i, word in enumerate(words):
        if word in _SUBORDINATOR_WORDS:
            # Avoid double-counting with phrases
            if word in phrase_words:
                # Check if this specific instance is part of a phrase
                # Simple heuristic: skip if adjacent words form a known phrase
                skip = False
                for j in range(max(0, i - 2), min(len(words), i + 3)):
                    for phrase in phrase_hits:
                        if word in phrase and j != i:
                            skip = True
                            break
                    if skip:
                        break
                if skip:
                    continue

            depth += 1
            max_d = max(max_d, depth)
            subordinators_found.append(word)

        # Check relative pronouns
        elif word in _RELATIVE_PRONOUNS:
            # Heuristic: "that" after a noun is likely relative
            # "that" at sentence start or after a verb is likely demonstrative
            if word == "that":
                if i > 0 and words[i - 1] not in {
                    "think", "believe", "know", "said", "say",
                    "hope", "wish", "fear", "doubt", "suggest",
                    "argue", "claim", "assume", "imagine",
                    "is", "are", "was", "were", "be", "been",
                }:
                    relative_count += 1
                    depth += 1
                    max_d = max(max_d, depth)
            elif word in ("who", "whom", "whose", "which"):
                relative_count += 1
                depth += 1
                max_d = max(max_d, depth)
            elif word in ("where", "when"):
                # Only count if not at sentence start (interrogative)
                if i > 0:
                    relative_count += 1
                    depth += 1
                    max_d = max(max_d, depth)

    return (max_d, subordinators_found, relative_count)


def _classify(mean_depth: float) -> str:
    """Classify text by mean clause nesting depth."""
    if mean_depth < 1.3:
        return "flat"
    elif mean_depth < 1.8:
        return "simple"
    elif mean_depth < 2.5:
        return "layered"
    elif mean_depth < 3.5:
        return "complex"
    else:
        return "labyrinthine"


# ── public API ─────────────────────────────────────────────────

def measure_clause_nesting(text: str) -> ClauseNestingResult:
    """Analyze clause nesting depth in text.

    Args:
        text: input text to analyze

    Returns:
        ClauseNestingResult with depth metrics and classification
    """
    if not text or not text.strip():
        return ClauseNestingResult(classification="unknown")

    sentences = _split_sentences(text)
    if not sentences:
        return ClauseNestingResult(classification="unknown")

    depths: List[int] = []
    all_subordinators: List[str] = []
    total_relatives = 0

    for sent in sentences:
        max_d, subs, rels = _count_clauses_in_sentence(sent)
        depths.append(max_d)
        all_subordinators.extend(subs)
        total_relatives += rels

    # Compute metrics
    total_sents = len(depths)
    max_depth = max(depths) if depths else 0
    mean_depth = sum(depths) / total_sents if total_sents > 0 else 0.0

    # Deep clause ratio (depth >= 3)
    deep_count = sum(1 for d in depths if d >= 3)
    deep_ratio = deep_count / total_sents if total_sents > 0 else 0.0

    # Depth distribution
    dist: Counter = Counter()
    for d in depths:
        bucket = min(d, 4)  # cap at 4+
        dist[bucket] += 1

    # Subordinator breakdown
    sub_counts: Counter = Counter(all_subordinators)

    return ClauseNestingResult(
        max_depth=max_depth,
        mean_depth=round(mean_depth, 2),
        total_sentences=total_sents,
        deep_clause_ratio=round(deep_ratio, 4),
        depth_distribution=dict(dist),
        subordinator_counts=dict(sub_counts),
        relative_clause_count=total_relatives,
        sentence_depths=depths,
        classification=_classify(mean_depth),
    )


if __name__ == "__main__":
    import json

    flat_sample = (
        "The server crashed. The backup restored data. The team reviewed logs."
    )
    complex_sample = (
        "The server crashed because the disk filled up while the backup was "
        "running, which meant that the team, who had been on call since midnight, "
        "had to restore data manually before the morning deadline."
    )

    print("=== Flat prose ===")
    print(json.dumps(measure_clause_nesting(flat_sample).to_dict(), indent=2))

    print("\n=== Complex prose ===")
    print(json.dumps(measure_clause_nesting(complex_sample).to_dict(), indent=2))
