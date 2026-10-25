"""vocabulary_richness — measure lexical diversity of written strokes.

A writer that produces 400 strokes can still be saying the same thing
over and over. Stroke count measures output; vocabulary measures
variety. This module reads ``data/strokes.jsonl`` and computes:

- **type_token_ratio** — unique words / total words (1.0 = every word unique,
  0.0 = same word repeated)
- **h_density** — hapax legomena / total words (words appearing exactly once)
- **moving_average_ttr** — windowed TTR smoothed over N-word chunks
- **vocabulary_grade** — A/B/C/F for quick at-a-glance assessment

Usage::

    from iamai.vocabulary_richness import richness_report, richness_summary

    report = richness_report(window_strokes=100)
    print(report["type_token_ratio"])      # e.g. 0.68
    print(report["h_density"])             # e.g. 0.42
    print(report["grade"])                 # "B"

    summary = richness_summary()
    print(summary)

Design choices:
  - Lowercase and strip punctuation before counting.
  - Stopwords are counted (they matter for TTR in short texts).
  - Window size defaults to 100 strokes; smaller windows inflate TTR.
  - Grade thresholds calibrated on 400-stroke corpus: A≥0.70, B≥0.55,
    C≥0.40, F<0.40.
"""

from __future__ import annotations

import json
import re
import string
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO_ROOT / "data" / "strokes.jsonl"

# Grade thresholds (type-token ratio).
_GRADE_THRESHOLDS = [
    (0.70, "A"),
    (0.55, "B"),
    (0.40, "C"),
    (0.00, "F"),
]

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    cleaned = text.translate(_PUNCT_TABLE).lower()
    return [w for w in cleaned.split() if w]


def _load_strokes(path: Path, window_strokes: Optional[int] = None) -> List[str]:
    """Read stroke texts from JSONL file, optionally tailing the last N."""
    if not path.exists():
        return []

    texts = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                text = obj.get("text", "")
                if text:
                    texts.append(text)
            except (json.JSONDecodeError, ValueError):
                continue

    if window_strokes and len(texts) > window_strokes:
        texts = texts[-window_strokes:]

    return texts


def type_token_ratio(tokens: List[str]) -> float:
    """Classic TTR: unique types / total tokens."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def h_density(tokens: List[str]) -> float:
    """Hapax density: words appearing exactly once / total tokens."""
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    hapax = sum(1 for w, c in counts.items() if c == 1)
    return hapax / len(tokens)


def moving_average_ttr(tokens: List[str], window_size: int = 50) -> float:
    """Moving-average TTR: average of TTRs over fixed-size chunks.

    Smoother than raw TTR for long texts because it doesn't deflate
    as total token count grows.
    """
    if not tokens or window_size <= 0:
        return 0.0

    chunks = [tokens[i:i + window_size] for i in range(0, len(tokens), window_size)]
    ttrs = [type_token_ratio(chunk) for chunk in chunks]
    return sum(ttrs) / len(ttrs) if ttrs else 0.0


def _grade(ttr: float) -> str:
    """Map TTR to a letter grade."""
    for threshold, grade in _GRADE_THRESHOLDS:
        if ttr >= threshold:
            return grade
    return "F"


def richness_report(
    window_strokes: Optional[int] = 100,
    strokes_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute vocabulary richness metrics for recent strokes.

    Args:
        window_strokes: Number of most recent strokes to analyze.
            None = all strokes.
        strokes_path: Override default strokes.jsonl path.

    Returns:
        Dict with keys: type_token_ratio, h_density, moving_average_ttr,
        total_tokens, unique_tokens, hapax_count, grade.
    """
    path = strokes_path or STROKES_PATH
    texts = _load_strokes(path, window_strokes)

    if not texts:
        return {
            "type_token_ratio": 0.0,
            "h_density": 0.0,
            "moving_average_ttr": 0.0,
            "total_tokens": 0,
            "unique_tokens": 0,
            "hapax_count": 0,
            "grade": "F",
        }

    all_tokens = []
    for text in texts:
        all_tokens.extend(_tokenize(text))

    counts = Counter(all_tokens)
    hapax = sum(1 for w, c in counts.items() if c == 1)

    ttr = type_token_ratio(all_tokens)
    h = h_density(all_tokens)
    mattr = moving_average_ttr(all_tokens)

    return {
        "type_token_ratio": round(ttr, 4),
        "h_density": round(h, 4),
        "moving_average_ttr": round(mattr, 4),
        "total_tokens": len(all_tokens),
        "unique_tokens": len(counts),
        "hapax_count": hapax,
        "grade": _grade(ttr),
    }


def richness_summary(
    window_strokes: Optional[int] = 100,
    strokes_path: Optional[Path] = None,
) -> str:
    """One-line summary suitable for caretaker dashboards."""
    r = richness_report(window_strokes, strokes_path)
    return (
        f"vocabulary: grade={r['grade']} TTR={r['type_token_ratio']:.3f} "
        f"H={r['h_density']:.3f} tokens={r['total_tokens']} "
        f"unique={r['unique_tokens']}"
    )
