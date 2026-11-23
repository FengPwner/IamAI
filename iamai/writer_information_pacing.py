#!/usr/bin/env python3
"""writer_information_pacing — analyse how new vocabulary enters the text stream.

Information pacing is the rate at which a text introduces *novel* lexical
items.  A well-paced text introduces new concepts and terms at a rate the
reader can absorb: not so fast that each sentence is a glossary, not so
slow that the reader skims ahead looking for something they haven't seen.

This module tracks the position of each word's **first occurrence** in the
text and derives a compact set of pacing indicators:

========================  =============================================
metric                    meaning
========================  =============================================
total_words               total word tokens analysed
unique_words              distinct word types
type_token_ratio          unique / total (vocabulary diversity)
mean_novelty_rate         fraction of words per sentence that are
                          first-occurrences
novelty_entropy           Shannon entropy of first-occurrence
                          positions normalised across text (higher =
                          more evenly distributed)
front_loading_index       fraction of unique words whose first
                          occurrence falls in the first third
heaps_alpha               Heaps' law exponent (V = K·N^α); higher α
                          means faster vocabulary growth
pacing_label              human-readable classification
========================  =============================================

Pacing labels
-------------

==============  =======================================================
label           description
==============  =======================================================
front_loaded    most new words cluster in the opening third; the
                remainder rehashes established vocabulary
steady          new words arrive at a roughly constant rate across
                the text
bursty          new words appear in clusters separated by dry
                spells — topic-switching or list-heavy prose
sparse          very low type-token ratio; the text recycles a small
                vocabulary almost entirely
accelerating    vocabulary growth accelerates toward the end —
                the text opens with familiar terms and layers in
                new ones
exhausting      nearly every word is a first occurrence (very short
                text or extreme diversity with no reuse)
==============  =======================================================

Usage::

    python3 -m iamai.writer_information_pacing               # last 200 strokes
    python3 -m iamai.writer_information_pacing -n 500         # last 500 strokes
    python3 -m iamai.writer_information_pacing --json         # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_N = 200
DEFAULT_STROKES_PATH = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"

_WORD_RE = re.compile(r"[a-z']+", re.IGNORECASE)

# Common English stop words to exclude from novelty tracking.
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "not", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "shall",
    "can", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "too", "very", "just", "don", "t",
    "s", "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves", "he", "him",
    "his", "himself", "she", "her", "hers", "herself", "it", "its",
    "itself", "they", "them", "their", "theirs", "themselves", "what",
    "which", "who", "whom", "this", "that", "these", "those", "am",
    "if", "because", "until", "while", "so", "than", "about", "up",
    "own", "same", "also", "only", "still", "even", "well", "much",
    "many", "get", "got", "make", "like", "know", "think", "see",
    "want", "give", "use", "find", "tell", "ask", "work", "seem",
    "feel", "try", "leave", "call", "need", "become", "keep", "let",
    "begin", "show", "hear", "play", "run", "move", "live", "believe",
    "bring", "happen", "write", "provide", "sit", "stand", "lose",
    "pay", "meet", "include", "continue", "set", "learn", "change",
    "lead", "understand", "watch", "follow", "stop", "create", "speak",
    "read", "allow", "add", "spend", "grow", "open", "walk", "win",
    "teach", "offer", "remember", "love", "consider", "appear", "buy",
    "wait", "serve", "die", "send", "expect", "build", "stay", "fall",
    "cut", "reach", "kill", "remain", "suggest", "raise", "pass",
    "sell", "require", "report", "decide", "pull", "develop",
})


# ---------------------------------------------------------------------------
# Small math helpers
# ---------------------------------------------------------------------------


def _mean(values: List[float]) -> float:
    """Arithmetic mean; returns 0.0 for empty input."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _entropy(proportions: List[float]) -> float:
    """Shannon entropy (base 2) from a list of proportions summing to ~1."""
    return -sum(p * math.log2(p) for p in proportions if p > 0)


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    """Lowercase tokenise, filtering stop words and very short tokens."""
    tokens = _WORD_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _split_sentences(text: str) -> List[str]:
    """Naive sentence splitting on terminal punctuation."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _first_occurrence_positions(tokens: List[str]) -> Dict[str, int]:
    """Map each unique token to the index of its first occurrence."""
    seen: Dict[str, int] = {}
    for i, token in enumerate(tokens):
        if token not in seen:
            seen[token] = i
    return seen


def _heaps_alpha(total: int, unique: int) -> float:
    """Estimate Heaps' law exponent α from V = K·N^α.

    Using the simplified form: α ≈ log(V) / log(N) for N > 1.
    Returns 0.0 when N ≤ 1.
    """
    if total <= 1 or unique <= 0:
        return 0.0
    return math.log(unique) / math.log(total)


def _sentence_novelty_rates(texts: List[str]) -> List[float]:
    """Compute per-sentence novelty rate: fraction of words that are new."""
    seen: set = set()
    rates: List[float] = []
    for text in texts:
        for sentence in _split_sentences(text):
            tokens = _tokenize(sentence)
            if not tokens:
                continue
            novel = sum(1 for t in tokens if t not in seen)
            seen.update(tokens)
            rates.append(novel / len(tokens))
    return rates


def compute_pacing(texts: List[str]) -> Dict[str, Any]:
    """Compute information-pacing metrics from a list of text strings.

    Parameters
    ----------
    texts : list of str
        Each element is one stroke's text content.

    Returns
    -------
    dict with keys matching the metric table in the module docstring.
    """
    all_tokens: List[str] = []
    for text in texts:
        all_tokens.extend(_tokenize(text))

    total_words = len(all_tokens)
    if total_words == 0:
        return {
            "total_words": 0,
            "unique_words": 0,
            "type_token_ratio": 0.0,
            "mean_novelty_rate": 0.0,
            "novelty_entropy": 0.0,
            "front_loading_index": 0.0,
            "heaps_alpha": 0.0,
            "pacing_label": "sparse",
        }

    first_occ = _first_occurrence_positions(all_tokens)
    unique_words = len(first_occ)
    type_token_ratio = unique_words / total_words

    # Front-loading: fraction of unique words in the first third
    third = total_words // 3
    front_count = sum(1 for pos in first_occ.values() if pos < third)
    front_loading_index = front_count / unique_words if unique_words else 0.0

    # Novelty entropy: how evenly first-occurrences distribute across the text
    # Divide text into 10 bins and compute entropy over bin counts.
    n_bins = min(10, total_words)
    bins = [0] * n_bins
    for pos in first_occ.values():
        bin_idx = min(int(pos * n_bins / total_words), n_bins - 1)
        bins[bin_idx] += 1
    bin_total = sum(bins)
    proportions = [b / bin_total for b in bins] if bin_total else []
    novelty_entropy = _entropy(proportions) if proportions else 0.0
    max_entropy = math.log2(n_bins) if n_bins > 1 else 1.0
    normalised_entropy = novelty_entropy / max_entropy if max_entropy else 0.0

    # Heaps' law exponent
    heaps_alpha = _heaps_alpha(total_words, unique_words)

    # Per-sentence novelty rates
    novelty_rates = _sentence_novelty_rates(texts)
    mean_novelty_rate = _mean(novelty_rates)

    # Classification
    pacing_label = _classify_pacing(
        type_token_ratio=type_token_ratio,
        front_loading_index=front_loading_index,
        normalised_entropy=normalised_entropy,
        heaps_alpha=heaps_alpha,
        mean_novelty_rate=mean_novelty_rate,
        total_words=total_words,
    )

    return {
        "total_words": total_words,
        "unique_words": unique_words,
        "type_token_ratio": round(type_token_ratio, 4),
        "mean_novelty_rate": round(mean_novelty_rate, 4),
        "novelty_entropy": round(normalised_entropy, 4),
        "front_loading_index": round(front_loading_index, 4),
        "heaps_alpha": round(heaps_alpha, 4),
        "pacing_label": pacing_label,
    }


def _classify_pacing(
    *,
    type_token_ratio: float,
    front_loading_index: float,
    normalised_entropy: float,
    heaps_alpha: float,
    mean_novelty_rate: float,
    total_words: int,
) -> str:
    """Priority-based pacing classification."""
    if total_words < 20:
        return "exhausting"

    if type_token_ratio < 0.15:
        return "sparse"

    if normalised_entropy > 0.85 and mean_novelty_rate > 0.6:
        return "exhausting"

    if front_loading_index > 0.65:
        return "front_loaded"

    if heaps_alpha > 0.7 and front_loading_index < 0.4:
        return "accelerating"

    # Bursty: high variance in per-bin novelty (entropy below middle band)
    if normalised_entropy < 0.55:
        return "bursty"

    return "steady"


# ---------------------------------------------------------------------------
# Stroke loading
# ---------------------------------------------------------------------------


def _load_strokes(path: Path, n: int) -> List[Dict[str, Any]]:
    """Load the last *n* strokes from a JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    strokes: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def pacing_report(n: int = DEFAULT_N, strokes_path: Optional[Path] = None) -> Dict[str, Any]:
    """Generate a pacing report from on-disk strokes."""
    path = strokes_path or DEFAULT_STROKES_PATH
    strokes = _load_strokes(path, n)
    texts = [s.get("text", "") for s in strokes if s.get("text")]
    return compute_pacing(texts)


def pacing_summary(report: Dict[str, Any]) -> str:
    """One-paragraph human-readable summary."""
    n = report["total_words"]
    if n == 0:
        return "No words to analyse."

    label = report["pacing_label"]
    ttr = report["type_token_ratio"]
    entropy = report["novelty_entropy"]
    alpha = report["heaps_alpha"]

    parts = [f"writer_information_pacing: {n} words, {report['unique_words']} unique"]
    parts.append(f"pacing={label}")
    parts.append(f"TTR={ttr:.3f}")
    parts.append(f"entropy={entropy:.2f}")
    parts.append(f"Heaps α={alpha:.3f}")

    front = report["front_loading_index"]
    if front > 0.6:
        parts.append(f"front-loaded ({front:.0%} in first third)")

    novelty = report["mean_novelty_rate"]
    parts.append(f"novelty rate={novelty:.2f}/sentence")

    return ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------


def pacing_state(strokes_path: Optional[Path] = None, n: int = DEFAULT_N) -> Dict[str, Any]:
    """Compute pacing and return a state dict suitable for writer_state JSON."""
    report = pacing_report(n=n, strokes_path=strokes_path)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyse vocabulary introduction pacing as a writing-style signal."
    )
    parser.add_argument(
        "-n", "--strokes", type=int, default=DEFAULT_N,
        help=f"number of recent strokes to analyse (default {DEFAULT_N})"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit full JSON report"
    )
    args = parser.parse_args(argv)

    report = pacing_report(n=args.strokes)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(pacing_summary(report))

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
