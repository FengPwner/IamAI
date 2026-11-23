#!/usr/bin/env python3
"""writer_anchor_words — detect and analyse thematic anchor words in text.

Every text has *anchor words*: content words that recur across sentences
and paragraphs, acting as gravitational centres that hold the discourse
together.  A well-anchored text is easy to follow because the reader
always has familiar concepts to latch onto; a poorly anchored text feels
scattered, even when each individual sentence is clear.

This module identifies anchor words and quantifies how they shape the
text's thematic structure.

========================  =============================================
metric                    meaning
========================  =============================================
total_words               total token count (all words)
content_words             tokens that are not stop words
unique_content_words      distinct content-word types
top_anchors               list of the *k* most frequent content words
                          (default k = 10)
anchor_token_count        total occurrences of the top anchors
anchor_density            anchor_token_count / total_words
thematic_focus            anchor_token_count / content_words;
                          higher means the text orbits a small set
                          of recurring concepts
anchor_persistence        1 − CV of per-paragraph anchor density;
                          1 = perfectly stable, 0 = highly erratic
anchor_dispersion         fraction of paragraphs that contain at
                          least one anchor word
gravitational_index       composite score in [0, 1]; higher means
                          the text is more strongly anchored
anchor_label              human-readable classification
========================  =============================================

Anchor labels
-------------

================  =====================================================
label             description
================  =====================================================
anchored          strong, persistent anchor words with high
                  gravitational index; the text orbits clear themes
multi-pole        several competing anchor clusters; the text
                  covers multiple themes without a single centre
drifting          weak or inconsistent anchors; the text meanders
                  without recurring touchstones
mono-fixated      one or two words dominate overwhelmingly; the
                  text is repetitive rather than thematically rich
diffuse           many content words at similar frequencies; no
                  clear anchor emerges
stable            moderate anchors with very high persistence;
                  the text maintains a steady thematic presence
================  =====================================================

Usage::

    python3 -m iamai.writer_anchor_words              # last 200 strokes
    python3 -m iamai.writer_anchor_words -n 500       # last 500 strokes
    python3 -m iamai.writer_anchor_words --json       # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Common English stop words (function words that carry little lexical meaning).
STOP_WORDS = frozenset({
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "from", "by", "of", "with", "as", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "under", "over", "out", "off", "up", "down", "is", "am", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "need", "dare", "ought", "used", "it", "its",
    "this", "that", "these", "those", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "when", "where", "why",
    "how", "not", "no", "nor", "if", "then", "than", "too", "very",
    "just", "about", "also", "more", "most", "some", "any", "all",
    "each", "every", "both", "few", "many", "much", "other", "another",
    "such", "only", "own", "same", "so", "here", "there", "now",
    "once", "again", "further", "because", "until", "while", "since",
    "although", "though", "however", "therefore", "moreover",
    "furthermore", "nevertheless", "nonetheless", "accordingly",
    "consequently", "meanwhile", "otherwise", "instead", "indeed",
    "thus", "hence", "still", "already", "even", "also", "well",
    "back", "like", "make", "made", "get", "got", "go", "went",
    "gone", "come", "came", "take", "took", "give", "gave", "know",
    "knew", "think", "thought", "say", "said", "let", "see", "saw",
    "want", "look", "put", "keep", "begin", "seem", "help", "show",
    "hear", "play", "run", "move", "live", "believe", "bring",
    "happen", "write", "provide", "sit", "stand", "lose", "pay",
    "meet", "include", "continue", "set", "learn", "change", "lead",
    "understand", "watch", "follow", "stop", "create", "speak",
    "read", "allow", "add", "spend", "grow", "open", "walk", "win",
    "offer", "remember", "love", "consider", "appear", "buy", "wait",
    "serve", "die", "send", "expect", "build", "stay", "fall", "cut",
    "reach", "kill", "remain", "suggest", "raise", "pass", "sell",
    "require", "report", "decide", "pull", "develop",
})

# Minimum word length to count as a content word.
_MIN_WORD_LEN = 3

# Default number of top anchors to track.
_DEFAULT_K = 10

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STROKES_FILE = DATA_DIR / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise, stripping punctuation and short words."""
    tokens = re.findall(r"[a-zA-Z']+", text.lower())
    return [t for t in tokens if len(t) >= _MIN_WORD_LEN]


def _content_words(tokens: list[str]) -> list[str]:
    """Filter tokens to content words only (not stop words)."""
    return [t for t in tokens if t not in STOP_WORDS]


def _split_paragraphs(text: str) -> list[str]:
    """Split text on blank lines."""
    paras = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paras if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitting on terminal punctuation."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _find_top_anchors(content_tokens: list[str], k: int = _DEFAULT_K) -> list[tuple[str, int]]:
    """Return the *k* most frequent content words with their counts."""
    freq = Counter(content_tokens)
    return freq.most_common(k)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_anchor_words(
    texts: list[str],
    k: int = _DEFAULT_K,
) -> dict[str, Any]:
    """Compute anchor-word metrics for a list of stroke texts.

    Parameters
    ----------
    texts:
        List of text strings (one per stroke).
    k:
        Number of top anchor words to track.

    Returns
    -------
    dict with all anchor-word metrics.
    """
    if not texts:
        return _empty_result(k)

    combined = "\n\n".join(texts)
    all_tokens = _tokenize(combined)
    content_tokens = _content_words(all_tokens)

    if not content_tokens:
        return _empty_result(k)

    total_words = len(all_tokens)
    n_content = len(content_tokens)
    unique_content = len(set(content_tokens))

    # Top anchors
    top_anchors = _find_top_anchors(content_tokens, k)
    anchor_set = {w for w, _ in top_anchors}
    anchor_token_count = sum(c for _, c in top_anchors)

    # Density: anchors as fraction of all words
    anchor_density = anchor_token_count / total_words if total_words else 0.0

    # Thematic focus: anchors as fraction of content words
    thematic_focus = anchor_token_count / n_content if n_content else 0.0

    # Per-paragraph analysis
    paragraphs = _split_paragraphs(combined)
    if not paragraphs:
        paragraphs = [combined]

    para_anchor_densities: list[float] = []
    paras_with_anchor = 0

    for para in paragraphs:
        para_tokens = _tokenize(para)
        if not para_tokens:
            continue
        para_anchor_count = sum(1 for t in para_tokens if t in anchor_set)
        para_density = para_anchor_count / len(para_tokens)
        para_anchor_densities.append(para_density)
        if para_anchor_count > 0:
            paras_with_anchor += 1

    # Persistence: 1 - CV of per-paragraph anchor density
    if len(para_anchor_densities) >= 2:
        mean_pd = sum(para_anchor_densities) / len(para_anchor_densities)
        if mean_pd > 0:
            var_pd = sum((d - mean_pd) ** 2 for d in para_anchor_densities) / len(para_anchor_densities)
            cv_pd = math.sqrt(var_pd) / mean_pd
            anchor_persistence = max(0.0, min(1.0, 1.0 - cv_pd))
        else:
            anchor_persistence = 0.0
    else:
        anchor_persistence = 1.0 if para_anchor_densities else 0.0

    # Dispersion: fraction of paragraphs containing at least one anchor
    anchor_dispersion = paras_with_anchor / len(paragraphs) if paragraphs else 0.0

    # Gravitational index: weighted composite
    # Components: thematic_focus (0.30), anchor_persistence (0.25),
    #             anchor_dispersion (0.25), anchor_density (0.20)
    gravitational_index = (
        0.30 * min(thematic_focus, 1.0)
        + 0.25 * anchor_persistence
        + 0.25 * anchor_dispersion
        + 0.20 * min(anchor_density / 0.15, 1.0)  # normalise: 0.15 → 1.0
    )
    gravitational_index = round(max(0.0, min(1.0, gravitational_index)), 4)

    # Classification
    anchor_label = _classify(
        gravitational_index, thematic_focus, anchor_persistence,
        anchor_dispersion, top_anchors, unique_content,
    )

    return {
        "total_words": total_words,
        "content_words": n_content,
        "unique_content_words": unique_content,
        "top_anchors": [(w, c) for w, c in top_anchors],
        "anchor_token_count": anchor_token_count,
        "anchor_density": round(anchor_density, 4),
        "thematic_focus": round(thematic_focus, 4),
        "anchor_persistence": round(anchor_persistence, 4),
        "anchor_dispersion": round(anchor_dispersion, 4),
        "gravitational_index": gravitational_index,
        "anchor_label": anchor_label,
    }


def _empty_result(k: int = _DEFAULT_K) -> dict[str, Any]:
    """Return a zeroed-out result when there is no text to analyse."""
    return {
        "total_words": 0,
        "content_words": 0,
        "unique_content_words": 0,
        "top_anchors": [],
        "anchor_token_count": 0,
        "anchor_density": 0.0,
        "thematic_focus": 0.0,
        "anchor_persistence": 0.0,
        "anchor_dispersion": 0.0,
        "gravitational_index": 0.0,
        "anchor_label": "drifting",
    }


def _classify(
    grav_index: float,
    thematic_focus: float,
    persistence: float,
    dispersion: float,
    top_anchors: list[tuple[str, int]],
    unique_content: int,
) -> str:
    """Classify the text's anchoring pattern."""
    if not top_anchors:
        return "drifting"

    top_count = top_anchors[0][1] if top_anchors else 0
    second_count = top_anchors[1][1] if len(top_anchors) > 1 else 0

    # Mono-fixated: one word dominates overwhelmingly
    if top_anchors and second_count > 0 and top_count / second_count >= 3.0 and thematic_focus >= 0.15:
        return "mono-fixated"

    # Diffuse: many unique content words, low thematic focus
    if unique_content > 0 and thematic_focus < 0.08 and grav_index < 0.35:
        return "diffuse"

    # Strong anchoring
    if grav_index >= 0.60 and persistence >= 0.60:
        return "anchored"

    # Stable: moderate anchors but very high persistence
    if persistence >= 0.80 and dispersion >= 0.70:
        return "stable"

    # Multi-pole: several anchor clusters
    if len(top_anchors) >= 3:
        top3 = [c for _, c in top_anchors[:3]]
        if top3[0] > 0 and top3[2] / top3[0] >= 0.4:
            return "multi-pole"

    # Drifting: weak or inconsistent
    if grav_index < 0.35 or persistence < 0.30:
        return "drifting"

    # Default
    if grav_index >= 0.45:
        return "anchored"

    return "multi-pole"


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------

def _load_strokes(n: int = 200) -> list[str]:
    """Load the last *n* stroke texts from the JSONL file."""
    if not STROKES_FILE.exists():
        return []
    lines = STROKES_FILE.read_text(encoding="utf-8").strip().splitlines()
    texts: list[str] = []
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
            t = obj.get("text", "")
            if t:
                texts.append(t)
        except json.JSONDecodeError:
            continue
    return texts


def anchor_report(n: int = 200, k: int = _DEFAULT_K) -> dict[str, Any]:
    """Compute anchor-word metrics from the on-disk strokes file."""
    texts = _load_strokes(n)
    metrics = compute_anchor_words(texts, k)
    metrics["strokes_analysed"] = len(texts)
    return metrics


def anchor_summary(metrics: dict[str, Any]) -> str:
    """Human-readable summary of anchor-word metrics."""
    anchors_str = ", ".join(f"{w} ({c})" for w, c in metrics.get("top_anchors", [])[:5])
    lines = [
        f"Total words      : {metrics['total_words']}",
        f"Content words    : {metrics['content_words']}",
        f"Unique content   : {metrics['unique_content_words']}",
        f"Top anchors      : {anchors_str}",
        f"Anchor density   : {metrics['anchor_density']:.2%}",
        f"Thematic focus   : {metrics['thematic_focus']:.2%}",
        f"Persistence      : {metrics['anchor_persistence']:.3f}",
        f"Dispersion       : {metrics['anchor_dispersion']:.2%}",
        f"Gravitational idx: {metrics['gravitational_index']:.3f}",
        f"Label            : {metrics['anchor_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Analyse thematic anchor words in recent strokes.",
    )
    ap.add_argument(
        "-n", "--strokes", type=int, default=200,
        help="number of recent strokes to analyse (default: 200)",
    )
    ap.add_argument(
        "-k", "--anchors", type=int, default=_DEFAULT_K,
        help="number of top anchor words to track (default: 10)",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="output full JSON report",
    )
    args = ap.parse_args(argv)

    metrics = anchor_report(args.strokes, args.anchors)

    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(anchor_summary(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(main())
