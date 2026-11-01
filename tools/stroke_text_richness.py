#!/usr/bin/env python3
"""stroke_text_richness.py — measure lexical quality of stroke texts.

Most monitoring tools look at *process metadata*: timing, counts, gaps.
This one looks at the *content itself* — are the strokes saying
interesting things, or has the writer devolved into repetition?

Three complementary metrics:

===================  ====================================================
metric               what it captures
===================  ====================================================
type_token_ratio     vocabulary diversity — unique words / total words
novel_word_rate      fresh vocabulary introduction — new words per stroke
sentence_complexity  syntactic variation — stddev of sentence lengths
===================  ====================================================

Each metric produces a value per window; trends over successive windows
reveal whether content quality is improving, flat, or degrading.

verdicts:

==========  ============================================================
label       meaning
==========  ============================================================
rich        diverse vocabulary, varied sentences, steady novelty
adequate    acceptable quality with room for improvement
stale       repetitive language, low novelty, uniform sentence structure
==========  ============================================================

Design goals:

1. **Pure Python** — no NLP libraries, no external deps.
2. **Windowed** — only looks at the most recent N strokes (default 50).
3. **Forgiving** — malformed JSONL lines are skipped, not raised.
4. **Deterministic** — same input always gives same output.

Usage::

    python3 tools/stroke_text_richness.py
    python3 tools/stroke_text_richness.py --window 100
    python3 tools/stroke_text_richness.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from statistics import mean, stdev

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

# Thresholds for composite richness score (0-1 scale).
_RICH_THRESHOLD = 0.65
_ADEQUATE_THRESHOLD = 0.40


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]+")
_SENT_SPLIT_RE = re.compile(r"[.!?;。！？；]+")


def tokenize(text: str) -> list[str]:
    """Lowercase tokenize a text into word tokens.

    Supports both Latin and CJK characters. Each CJK character
    counts as one token (no segmentation library dependency).
    """
    return _WORD_RE.findall(text.lower())


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-like fragments."""
    parts = _SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# core metrics
# ---------------------------------------------------------------------------


def type_token_ratio(tokens: list[str]) -> float:
    """Vocabulary diversity: unique words / total words.

    Returns 0.0 for empty input. Uses log-normalised TTR (MATTR-style
    approximation) for better comparability across different text lengths.
    """
    if not tokens:
        return 0.0
    n = len(tokens)
    v = len(set(tokens))
    if n <= 1:
        return float(v)
    # Log-normalised TTR: more stable across text lengths.
    return math.log(v + 1) / math.log(n + 1)


def novel_word_rate(
    current_tokens: list[str],
    previous_tokens: list[str],
) -> float:
    """Fraction of current tokens that are new (not in previous window).

    Returns 0.0 when current_tokens is empty.
    """
    if not current_tokens:
        return 0.0
    prev_vocab = set(previous_tokens)
    novel = sum(1 for t in current_tokens if t not in prev_vocab)
    return novel / len(current_tokens)


def sentence_complexity(sentences: list[str]) -> float:
    """Syntactic variation: coefficient of variation of sentence lengths.

    Higher means more varied sentence structure. Returns 0.0 when
    there are fewer than 2 sentences.
    """
    if len(sentences) < 2:
        return 0.0
    lengths = [len(tokenize(s)) for s in sentences]
    if not lengths:
        return 0.0
    avg = mean(lengths)
    if avg == 0:
        return 0.0
    return stdev(lengths) / avg


# ---------------------------------------------------------------------------
# composite score and classification
# ---------------------------------------------------------------------------


def richness_score(
    ttr: float,
    novelty: float,
    complexity: float,
) -> float:
    """Combine three metrics into a single 0-1 richness score.

    Weights: TTR 40%, novelty 35%, complexity 25%.
    Each component is clipped to [0, 1] before weighting.
    """
    ttr_c = max(0.0, min(1.0, ttr))
    nov_c = max(0.0, min(1.0, novelty))
    com_c = max(0.0, min(1.0, complexity))
    return 0.40 * ttr_c + 0.35 * nov_c + 0.25 * com_c


def classify(score: float) -> str:
    """Map a richness score to a verdict label."""
    if score >= _RICH_THRESHOLD:
        return "rich"
    if score >= _ADEQUATE_THRESHOLD:
        return "adequate"
    return "stale"


def trend_label(scores: list[float]) -> str:
    """Classify the trend of a series of richness scores.

    Compares the mean of the last third to the mean of the first third.
    """
    if len(scores) < 3:
        return "insufficient-data"
    third = max(1, len(scores) // 3)
    early = mean(scores[:third])
    late = mean(scores[-third:])
    delta = late - early
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "declining"
    return "flat"


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------


def load_strokes(
    path: Path = STROKES_PATH,
    window: int = 50,
) -> list[dict]:
    """Load the most recent `window` strokes from JSONL.

    Malformed lines are silently skipped.
    """
    if not path.exists():
        return []
    lines: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            lines.append(line)
    # Take the last `window` lines.
    recent = lines[-window:]
    strokes: list[dict] = []
    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def analyze_window(
    current_strokes: list[dict],
    previous_strokes: list[dict] | None = None,
) -> dict:
    """Compute all metrics for a window of strokes.

    Returns a dict with keys: ttr, novelty, complexity, score, verdict.
    """
    # Gather all text from current window.
    current_tokens: list[str] = []
    current_sentences: list[str] = []
    for s in current_strokes:
        text = s.get("text", "")
        current_tokens.extend(tokenize(text))
        current_sentences.extend(split_sentences(text))

    # Previous window tokens for novelty calculation.
    prev_tokens: list[str] = []
    if previous_strokes:
        for s in previous_strokes:
            prev_tokens.extend(tokenize(s.get("text", "")))

    ttr = type_token_ratio(current_tokens)
    novelty = novel_word_rate(current_tokens, prev_tokens)
    complexity = sentence_complexity(current_sentences)
    score = richness_score(ttr, novelty, complexity)

    return {
        "ttr": round(ttr, 4),
        "novelty": round(novelty, 4),
        "complexity": round(complexity, 4),
        "score": round(score, 4),
        "verdict": classify(score),
        "stroke_count": len(current_strokes),
        "token_count": len(current_tokens),
        "unique_tokens": len(set(current_tokens)),
    }


def analyze(
    path: Path = STROKES_PATH,
    window: int = 50,
) -> dict:
    """Full analysis: current window metrics + trend from history.

    Loads 2x window strokes to compute both current metrics and
    a novelty baseline from the preceding window.
    """
    if not path.exists():
        return {
            "error": "strokes file not found",
            "path": str(path),
        }

    # Load enough strokes for two windows.
    all_lines: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            all_lines.append(line)

    total_needed = window * 2
    recent_lines = all_lines[-total_needed:] if len(all_lines) > total_needed else all_lines

    strokes: list[dict] = []
    for line in recent_lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if len(strokes) < window:
        # Not enough data for two windows; analyze what we have.
        current = strokes
        previous: list[dict] = []
    else:
        current = strokes[-window:]
        previous = strokes[-(window * 2):-window] if len(strokes) >= window * 2 else []

    result = analyze_window(current, previous if previous else None)

    # Historical trend: split all loaded strokes into sequential windows.
    chunk_size = max(10, window // 5)
    scores: list[float] = []
    prev_chunk: list[dict] = []
    for i in range(0, len(strokes), chunk_size):
        chunk = strokes[i:i + chunk_size]
        if len(chunk) < chunk_size // 2:
            break
        r = analyze_window(chunk, prev_chunk if prev_chunk else None)
        scores.append(r["score"])
        prev_chunk = chunk

    result["trend"] = trend_label(scores)
    result["history_scores"] = [round(s, 3) for s in scores]

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure lexical richness of recent stroke texts.",
    )
    parser.add_argument(
        "--window", type=int, default=50,
        help="Number of recent strokes to analyze (default: 50).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--path", type=str, default=None,
        help="Path to strokes JSONL file.",
    )
    args = parser.parse_args(argv)

    strokes_path = Path(args.path) if args.path else STROKES_PATH
    result = analyze(path=strokes_path, window=args.window)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if "error" in result:
            print(f"ERROR: {result['error']}")
            return 1
        print(f"Stroke Text Richness Analysis")
        print(f"  Window:    {result['stroke_count']} strokes, "
              f"{result['token_count']} tokens")
        print(f"  TTR:       {result['ttr']:.4f}")
        print(f"  Novelty:   {result['novelty']:.4f}")
        print(f"  Complexity:{result['complexity']:.4f}")
        print(f"  Score:     {result['score']:.4f}")
        print(f"  Verdict:   {result['verdict']}")
        print(f"  Trend:     {result['trend']}")
        if result.get("history_scores"):
            print(f"  History:   {result['history_scores']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
