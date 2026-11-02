#!/usr/bin/env python3
"""stroke_vocabulary.py — measure lexical diversity of the stroke log.

While stroke_novelty.py detects template repetition, this tool looks at
the *language* inside each stroke: how varied is the vocabulary? A writer
that cycles through the same seven templates will also show a shrinking
vocabulary over time — the same words repeated in the same order.

Metrics:

  type_token_ratio (TTR) = unique_words / total_words
    The classic measure of lexical diversity.
    1.0 = every word is unique; 0.0 = only one word used.

  mean_length = average word count per stroke

  hapax_ratio = words_used_exactly_once / unique_words
    High hapax ratio means the writer keeps introducing new words.
    Low ratio means the vocabulary has calcified.

Severity (based on TTR over a window):

  TTR > 0.40   rich    — vocabulary is diverse
  TTR 0.20-0.40 flat    — narrowing but not dead
  TTR < 0.20   barren  — same handful of words recycled

Usage:
    python3 tools/stroke_vocabulary.py
    python3 tools/stroke_vocabulary.py --tail 500 --json
    python3 tools/stroke_vocabulary.py --min-words 3

Exit codes:
    0  rich
    1  flat
    2  barren
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Thresholds
RICH_THRESHOLD = 0.40
FLAT_THRESHOLD = 0.20

# Strip the "measured now" suffix — it's metadata, not content
MEASURED_SEP = "-- measured now"


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, drop tokens shorter than 2 chars."""
    if MEASURED_SEP in text:
        text = text.split(MEASURED_SEP)[0]
    tokens = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
    return tokens


def load_strokes(path: Path, tail: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if tail is not None:
        lines = lines[-tail:]
    strokes = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def analyze(
    strokes: list[dict],
    window: int | None = None,
    min_words: int = 1,
) -> dict:
    """Compute vocabulary metrics over a list of strokes.

    Returns:
        total_strokes:  number of strokes examined
        total_words:    total token count
        unique_words:   vocabulary size (types)
        type_token_ratio: unique_words / total_words
        mean_length:    average words per stroke
        hapax_ratio:    proportion of words used exactly once
        severity:       'rich' | 'flat' | 'barren'
    """
    if window is not None:
        strokes = strokes[-window:]

    if not strokes:
        return {
            "total_strokes": 0,
            "total_words": 0,
            "unique_words": 0,
            "type_token_ratio": 0.0,
            "mean_length": 0.0,
            "hapax_ratio": 0.0,
            "severity": "barren",
        }

    all_tokens: list[str] = []
    per_stroke_lengths: list[int] = []

    for s in strokes:
        tokens = _tokenize(s.get("text", ""))
        if len(tokens) < min_words:
            continue
        all_tokens.extend(tokens)
        per_stroke_lengths.append(len(tokens))

    if not all_tokens:
        return {
            "total_strokes": len(strokes),
            "total_words": 0,
            "unique_words": 0,
            "type_token_ratio": 0.0,
            "mean_length": 0.0,
            "hapax_ratio": 0.0,
            "severity": "barren",
        }

    counter = Counter(all_tokens)
    total_words = len(all_tokens)
    unique_words = len(counter)
    ttr = unique_words / total_words
    mean_len = (
        sum(per_stroke_lengths) / len(per_stroke_lengths)
        if per_stroke_lengths
        else 0.0
    )
    hapax = sum(1 for c in counter.values() if c == 1)
    hapax_ratio = hapax / unique_words if unique_words else 0.0

    if ttr >= RICH_THRESHOLD:
        severity = "rich"
    elif ttr >= FLAT_THRESHOLD:
        severity = "flat"
    else:
        severity = "barren"

    return {
        "total_strokes": len(strokes),
        "total_words": total_words,
        "unique_words": unique_words,
        "type_token_ratio": round(ttr, 4),
        "mean_length": round(mean_len, 1),
        "hapax_ratio": round(hapax_ratio, 4),
        "severity": severity,
    }


def severity_exit(severity: str) -> int:
    return {"rich": 0, "flat": 1, "barren": 2}.get(severity, 2)


def format_report(result: dict) -> str:
    lines = [
        "stroke vocabulary report",
        f"  strokes examined:   {result['total_strokes']}",
        f"  total words:        {result['total_words']}",
        f"  unique words:       {result['unique_words']}",
        f"  type-token ratio:   {result['type_token_ratio']:.2%}",
        f"  mean stroke length: {result['mean_length']:.1f} words",
        f"  hapax ratio:        {result['hapax_ratio']:.2%}",
        f"  severity:           {result['severity']}",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strokes", type=Path, default=DEFAULT_STROKES,
        help="path to strokes JSONL (default: data/strokes.jsonl)",
    )
    ap.add_argument("--tail", type=int, default=None,
                    help="only examine last N strokes")
    ap.add_argument("--window", type=int, default=None,
                    help="sliding window within the tail")
    ap.add_argument("--min-words", type=int, default=1,
                    help="skip strokes with fewer than N words")
    ap.add_argument("--json", action="store_true",
                    help="output JSON instead of text")
    args = ap.parse_args()

    strokes = load_strokes(args.strokes, tail=args.tail)
    result = analyze(strokes, window=args.window, min_words=args.min_words)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_report(result))

    return severity_exit(result["severity"])


if __name__ == "__main__":
    sys.exit(main())
