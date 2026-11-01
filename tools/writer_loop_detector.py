#!/usr/bin/env python3
"""writer_loop_detector.py — detect content repetition loops in strokes.

When an automated writer runs unattended, a subtle failure mode is the
*content loop*: the writer keeps producing strokes, but each one says
roughly the same thing.  Timing monitors see healthy cadence; only a
content-level check reveals the stagnation.

This tool complements:

- **stroke_text_richness.py** — measures *lexical quality* (vocabulary
  diversity, sentence complexity) but does not compare strokes to each
  other.
- **stroke_kind_balance.py** — measures *category distribution* but is
  blind to whether two consecutive "thought" strokes say the same thing.

Three similarity metrics are computed over a sliding window:

====================  =================================================
metric                what it captures
====================  =================================================
pair_jaccard_mean     average Jaccard similarity of consecutive word
                      sets — high means adjacent strokes share vocabulary
trigram_overlap_mean  average character-trigram overlap of consecutive
                      stroke texts — catches near-duplicate content
                      even when word tokenization differs
max_run_length        longest run of consecutive pairs whose Jaccard
                      exceeds the *loop* threshold — sustained
                      repetition is worse than a single repeat
====================  =================================================

Verdicts:

==========  ============================================================
label       meaning
==========  ============================================================
healthy     no sustained repetition detected
mild        occasional similar pairs, but no persistent loop
moderate    clear repetition runs of 3+ consecutive similar pairs
severe      long runs (5+) of near-identical strokes
==========  ============================================================

Design goals:

1. **Pure Python** — no NLP libraries, no external deps.
2. **Windowed** — only looks at the most recent N strokes (default 50).
3. **Forgiving** — malformed JSONL lines are skipped, not raised.
4. **Deterministic** — same input always gives same output.

Usage::

    python3 tools/writer_loop_detector.py
    python3 tools/writer_loop_detector.py --window 100
    python3 tools/writer_loop_detector.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

# Thresholds for pair Jaccard similarity.
_LOOP_THRESHOLD = 0.55  # above this, a pair is "in a loop"
_HIGH_SIMILARITY = 0.75  # above this, nearly duplicate

# Thresholds for max run length to determine verdict.
_MILD_RUN = 2
_MODERATE_RUN = 3
_SEVERE_RUN = 5


def tokenize(text: str) -> list[str]:
    """Lowercase split into word tokens, stripping punctuation."""
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def word_set(tokens: list[str]) -> set[str]:
    """Convert token list to a set for Jaccard computation."""
    return set(tokens)


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard index between two sets.  Returns 0.0 when both are empty."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return intersection / union


def character_trigrams(text: str) -> set[str]:
    """Extract character-level trigrams from text."""
    t = text.lower().strip()
    if len(t) < 3:
        return {t} if t else set()
    return {t[i : i + 3] for i in range(len(t) - 2)}


def trigram_overlap(text_a: str, text_b: str) -> float:
    """Character-trigram Jaccard overlap between two texts."""
    tri_a = character_trigrams(text_a)
    tri_b = character_trigrams(text_b)
    return jaccard_similarity(tri_a, tri_b)


def pair_jaccard(texts: list[str]) -> list[float]:
    """Compute Jaccard similarity for each consecutive pair."""
    if len(texts) < 2:
        return []
    results = []
    for i in range(len(texts) - 1):
        set_a = word_set(tokenize(texts[i]))
        set_b = word_set(tokenize(texts[i + 1]))
        results.append(jaccard_similarity(set_a, set_b))
    return results


def pair_trigram_overlaps(texts: list[str]) -> list[float]:
    """Compute character-trigram overlap for each consecutive pair."""
    if len(texts) < 2:
        return []
    return [trigram_overlap(texts[i], texts[i + 1]) for i in range(len(texts) - 1)]


def max_loop_run(similarities: list[float], threshold: float) -> int:
    """Longest run of consecutive values above threshold.

    A *run* counts the number of consecutive pairs that exceed the
    threshold.  A run of 0 means no adjacent pair is similar.
    """
    best = 0
    current = 0
    for s in similarities:
        if s >= threshold:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def classify(run_length: int) -> str:
    """Map max run length to a verdict label."""
    if run_length >= _SEVERE_RUN:
        return "severe"
    if run_length >= _MODERATE_RUN:
        return "moderate"
    if run_length >= _MILD_RUN:
        return "mild"
    return "healthy"


def health_score(verdict: str, pair_mean: float, run_length: int) -> int:
    """Compute a 0-100 health score (100 = perfectly healthy).

    Score is penalized by both the average similarity and the run length.
    """
    # Base score from average similarity (lower is better).
    base = max(0, int(100 * (1 - pair_mean)))
    # Penalty for sustained runs.
    run_penalty = min(40, run_length * 8)
    return max(0, base - run_penalty)


def load_strokes(path: Path = STROKES_PATH) -> list[dict[str, Any]]:
    """Load strokes from JSONL, skipping malformed lines."""
    strokes: list[dict[str, Any]] = []
    if not path.exists():
        return strokes
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def extract_text(stroke: dict[str, Any]) -> str:
    """Extract the content text from a stroke record."""
    # Try common field names.
    for key in ("content", "text", "body", "summary"):
        val = stroke.get(key)
        if isinstance(val, str) and val.strip():
            return val
    # Fallback: serialize entire record.
    return json.dumps(stroke, ensure_ascii=False)


def analyze_window(texts: list[str]) -> dict[str, Any]:
    """Analyze a window of stroke texts for loop detection."""
    if len(texts) < 2:
        return {
            "pair_jaccard_mean": 0.0,
            "trigram_overlap_mean": 0.0,
            "max_run_length": 0,
            "verdict": "healthy",
            "health": 100,
            "pair_count": 0,
            "high_similarity_pairs": 0,
        }

    jaccards = pair_jaccard(texts)
    trigrams = pair_trigram_overlaps(texts)
    run = max_loop_run(jaccards, _LOOP_THRESHOLD)
    verdict = classify(run)
    j_mean = mean(jaccards) if jaccards else 0.0
    t_mean = mean(trigrams) if trigrams else 0.0
    high_sim = sum(1 for j in jaccards if j >= _HIGH_SIMILARITY)
    score = health_score(verdict, j_mean, run)

    return {
        "pair_jaccard_mean": round(j_mean, 4),
        "trigram_overlap_mean": round(t_mean, 4),
        "max_run_length": run,
        "verdict": verdict,
        "health": score,
        "pair_count": len(jaccards),
        "high_similarity_pairs": high_sim,
    }


def analyze(
    window: int = 50,
    strokes_path: Path = STROKES_PATH,
) -> dict[str, Any]:
    """Full analysis: load strokes, take last *window*, analyze."""
    strokes = load_strokes(strokes_path)
    recent = strokes[-window:] if len(strokes) >= window else strokes
    texts = [extract_text(s) for s in recent]
    result = analyze_window(texts)
    result["window"] = len(texts)
    result["total_strokes"] = len(strokes)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect content repetition loops in stroke data."
    )
    parser.add_argument(
        "--window",
        type=int,
        default=50,
        help="Number of recent strokes to analyze (default: 50).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON.",
    )
    parser.add_argument(
        "--strokes",
        type=str,
        default=str(STROKES_PATH),
        help="Path to strokes JSONL file.",
    )
    args = parser.parse_args()

    result = analyze(window=args.window, strokes_path=Path(args.strokes))

    if args.output_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Writer Loop Detector — window={result['window']}/{result['total_strokes']} strokes")
        print(f"  pair Jaccard mean:     {result['pair_jaccard_mean']:.4f}")
        print(f"  trigram overlap mean:  {result['trigram_overlap_mean']:.4f}")
        print(f"  max loop run:          {result['max_run_length']}")
        print(f"  high-similarity pairs: {result['high_similarity_pairs']}/{result['pair_count']}")
        print(f"  verdict:               {result['verdict']}")
        print(f"  health:                {result['health']}/100")


if __name__ == "__main__":
    main()
