#!/usr/bin/env python3
"""stroke_coherence.py — measure semantic thread continuity between strokes.

While stroke_novelty detects template repetition and stroke_loop_detector
catches exact cycles, neither measures whether consecutive strokes form a
coherent thread of thought. A writer can produce varied content that
still jumps randomly between unrelated topics.

This module fills that gap:

  coherence_score = weighted_token_overlap(stroke_n, stroke_n+1)

where overlap is computed using IDF-weighted tokens so that common words
("the", "is", "a") contribute less than distinctive terms.

  score > 0.4   coherent   — strokes share a semantic thread
  score 0.2-0.4 drifting   — topic is shifting but not abruptly
  score 0.1-0.2 jarring    — abrupt topic jump
  score < 0.1   disconnected — no meaningful connection

Usage:
    python3 tools/stroke_coherence.py
    python3 tools/stroke_coherence.py --window 50
    python3 tools/stroke_coherence.py --json

Exit codes:
    0  coherence is healthy
    1  coherence is drifting
    2  coherence is poor (jarring or disconnected)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from collections import Counter
from typing import Any


REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Classification thresholds
COHERENT_THRESHOLD = 0.4
DRIFTING_THRESHOLD = 0.2
JARRING_THRESHOLD = 0.1

# Common English stop words to downweight
STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
    "either", "neither", "each", "every", "all", "any", "few", "more",
    "most", "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "where", "how", "what",
    "which", "who", "whom", "this", "that", "these", "those", "it", "its",
})


def tokenize(text: str) -> list[str]:
    """Lowercase tokenize and filter stop words."""
    tokens = []
    for word in text.lower().split():
        cleaned = word.strip(".,;:!?\"'()[]{}<>`*-_/\\|@#$%^&+=~")
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 1:
            tokens.append(cleaned)
    return tokens


def compute_idf(corpus: list[list[str]]) -> dict[str, float]:
    """Compute IDF scores from a corpus of token lists."""
    if not corpus:
        return {}
    n_docs = len(corpus)
    df: Counter = Counter()
    for tokens in corpus:
        unique = set(tokens)
        for token in unique:
            df[token] += 1
    idf = {}
    for token, count in df.items():
        idf[token] = math.log((n_docs + 1) / (count + 1)) + 1
    return idf


def weighted_overlap(
    tokens_a: list[str],
    tokens_b: list[str],
    idf: dict[str, float],
) -> float:
    """Compute IDF-weighted Jaccard-like overlap between two token sets."""
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    numerator = sum(idf.get(t, 1.0) for t in intersection)
    denominator = sum(idf.get(t, 1.0) for t in union)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def classify(score: float) -> str:
    """Classify a coherence score into a band."""
    if score >= COHERENT_THRESHOLD:
        return "coherent"
    elif score >= DRIFTING_THRESHOLD:
        return "drifting"
    elif score >= JARRING_THRESHOLD:
        return "jarring"
    else:
        return "disconnected"


def transition_label(prev_label: str, curr_label: str) -> str:
    """Describe the transition between two consecutive coherence bands."""
    if prev_label == curr_label:
        return f"stable_{curr_label}"
    band_rank = {"coherent": 3, "drifting": 2, "jarring": 1, "disconnected": 0}
    prev_rank = band_rank.get(prev_label, 0)
    curr_rank = band_rank.get(curr_label, 0)
    if curr_rank > prev_rank:
        return "improving"
    return "degrading"


def load_strokes(path: Path) -> list[dict[str, Any]]:
    """Load strokes from a JSONL file."""
    strokes = []
    if not path.exists():
        return strokes
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return strokes


def extract_text(stroke: dict[str, Any]) -> str:
    """Extract text content from a stroke record."""
    return stroke.get("text", "") or stroke.get("body", "") or ""


def analyze_window(
    strokes: list[dict[str, Any]],
    window: int = 100,
) -> dict[str, Any]:
    """Analyze coherence for a window of strokes."""
    if len(strokes) < 2:
        return {
            "count": len(strokes),
            "pairs": 0,
            "scores": [],
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "bands": {"coherent": 0, "drifting": 0, "jarring": 0, "disconnected": 0},
            "transitions": [],
        }

    window_strokes = strokes[-window:]
    texts = [extract_text(s) for s in window_strokes]
    token_lists = [tokenize(t) for t in texts]
    idf = compute_idf(token_lists)

    scores = []
    bands: Counter = Counter()
    transitions = []
    prev_label = None

    for i in range(len(token_lists) - 1):
        score = weighted_overlap(token_lists[i], token_lists[i + 1], idf)
        label = classify(score)
        scores.append(score)
        bands[label] += 1

        if prev_label is not None:
            transitions.append(transition_label(prev_label, label))
        prev_label = label

    mean_score = sum(scores) / len(scores) if scores else 0.0

    return {
        "count": len(window_strokes),
        "pairs": len(scores),
        "scores": [round(s, 4) for s in scores],
        "mean": round(mean_score, 4),
        "min": round(min(scores), 4) if scores else 0.0,
        "max": round(max(scores), 4) if scores else 0.0,
        "bands": {
            "coherent": bands.get("coherent", 0),
            "drifting": bands.get("drifting", 0),
            "jarring": bands.get("jarring", 0),
            "disconnected": bands.get("disconnected", 0),
        },
        "transitions": transitions,
    }


def snapshot_report(strokes_path: Path, window: int = 100) -> dict[str, Any]:
    """Generate a full coherence report from a strokes file."""
    strokes = load_strokes(strokes_path)
    result = analyze_window(strokes, window)
    result["file"] = str(strokes_path)
    result["total_strokes"] = len(strokes)

    # Overall health assessment
    mean = result["mean"]
    disconnected_ratio = result["bands"]["disconnected"] / max(result["pairs"], 1)
    if mean >= COHERENT_THRESHOLD and disconnected_ratio < 0.1:
        result["health"] = "healthy"
    elif mean >= DRIFTING_THRESHOLD:
        result["health"] = "drifting"
    else:
        result["health"] = "poor"

    return result


def delta_report(
    before_path: Path,
    after_path: Path,
    window: int = 100,
) -> dict[str, Any]:
    """Compare coherence between two snapshots."""
    before = snapshot_report(before_path, window)
    after = snapshot_report(after_path, window)
    return {
        "before": before,
        "after": after,
        "delta_mean": round(after["mean"] - before["mean"], 4),
        "delta_disconnected": (
            after["bands"]["disconnected"] - before["bands"]["disconnected"]
        ),
        "health_change": f"{before['health']} -> {after['health']}",
    }


def main():
    parser = argparse.ArgumentParser(description="Measure stroke coherence")
    parser.add_argument(
        "--strokes", type=str, default=str(DEFAULT_STROKES),
        help="Path to strokes JSONL file",
    )
    parser.add_argument("--window", type=int, default=100, help="Window size")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    report = snapshot_report(Path(args.strokes), args.window)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Coherence Report ({report['file']})")
        print(f"  Total strokes: {report['total_strokes']}")
        print(f"  Window: {report['count']} strokes, {report['pairs']} pairs")
        print(f"  Mean score: {report['mean']}")
        print(f"  Range: {report['min']} — {report['max']}")
        print(f"  Bands:")
        for band, count in report["bands"].items():
            print(f"    {band}: {count}")
        print(f"  Health: {report['health']}")

    # Exit code based on health
    if report["health"] == "healthy":
        sys.exit(0)
    elif report["health"] == "drifting":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
