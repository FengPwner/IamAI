"""stroke_entropy — information-theoretic diversity analysis for strokes.

While stroke_text_richness measures lexical quality (vocabulary, novelty,
sentence variation), this module looks at strokes through the lens of
information theory: how much *surprise* does each new stroke carry?

Three entropy measures:

====================  ====================================================
metric                what it captures
====================  ====================================================
shannon_entropy       bits of information per token in a window
perplexity            effective vocabulary size (2^entropy)
diminishing_return    rate at which new strokes add unique information
====================  ====================================================

A writer stuck in a loop has low entropy — each stroke is predictable.
A writer exploring new territory has high entropy — each stroke carries
genuine surprise.

verdicts:

==========  ============================================================
label       meaning
==========  ============================================================
exploring   high entropy, each stroke brings new information
routine     moderate entropy, some variation but predictable patterns
looping     low entropy, strokes are near-duplicates of each other
==========  ============================================================

Design goals:

1. **Pure Python** — no NLP or ML libraries.
2. **Windowed** — only looks at the most recent N strokes (default 50).
3. **Kind-aware** — entropy computed per stroke kind (thought, note, etc.)
   so that a writer cycling through kinds still shows structure.
4. **Forgiving** — malformed JSONL lines are silently skipped.

Usage::

    from iamai.stroke_entropy import stroke_entropy, entropy_report

    result = stroke_entropy(strokes, window=50)
    print(entropy_report(result))
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

# Thresholds for verdict classification (Shannon entropy in bits).
_EXPLORING_THRESHOLD = 4.5
_ROUTINE_THRESHOLD = 3.0


# ---------------------------------------------------------------------------
# text helpers (shared with stroke_text_richness but self-contained)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenize into word tokens."""
    return _WORD_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# core metrics
# ---------------------------------------------------------------------------


def shannon_entropy(tokens: list[str]) -> float:
    """Shannon entropy in bits per token.

    H = -sum(p_i * log2(p_i)) for each unique token i.
    Returns 0.0 for empty input.
    """
    if not tokens:
        return 0.0
    n = len(tokens)
    counts = Counter(tokens)
    h = 0.0
    for count in counts.values():
        p = count / n
        if p > 0:
            h -= p * math.log2(p)
    return h


def perplexity(tokens: list[str]) -> float:
    """Perplexity: 2^H, the effective vocabulary size.

    Higher means the writer is drawing from a larger pool of words.
    Returns 1.0 for empty input (no surprise, nothing to predict).
    """
    h = shannon_entropy(tokens)
    return 2.0 ** h


def diminishing_return(
    current_tokens: list[str],
    previous_tokens: list[str],
) -> float:
    """Fraction of current tokens already seen in the previous window.

    Returns 1.0 when both windows are empty (nothing new to return).
    A high value means the writer is reusing the same words — diminishing
    returns on each new stroke.
    """
    if not current_tokens:
        return 1.0
    prev_vocab = set(previous_tokens)
    seen = sum(1 for t in current_tokens if t in prev_vocab)
    return seen / len(current_tokens)


def entropy_classify(entropy: float) -> str:
    """Map a Shannon entropy value to a verdict label."""
    if entropy >= _EXPLORING_THRESHOLD:
        return "exploring"
    if entropy >= _ROUTINE_THRESHOLD:
        return "routine"
    return "looping"


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


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


def stroke_entropy(
    strokes: list[dict],
    previous_strokes: list[dict] | None = None,
    window: int = 50,
) -> dict:
    """Compute entropy metrics for a window of strokes.

    Returns a dict with: entropy, perplexity, diminishing, verdict,
    stroke_count, token_count, unique_tokens.
    """
    # Limit to window.
    current = strokes[-window:] if len(strokes) > window else strokes

    current_tokens: list[str] = []
    for s in current:
        text = s.get("text", "")
        current_tokens.extend(_tokenize(text))

    prev_tokens: list[str] = []
    if previous_strokes:
        for s in previous_strokes:
            prev_tokens.extend(_tokenize(s.get("text", "")))

    h = shannon_entropy(current_tokens)
    perp = perplexity(current_tokens)
    dim = diminishing_return(current_tokens, prev_tokens)

    return {
        "entropy": round(h, 4),
        "perplexity": round(perp, 2),
        "diminishing": round(dim, 4),
        "verdict": entropy_classify(h),
        "stroke_count": len(current),
        "token_count": len(current_tokens),
        "unique_tokens": len(set(current_tokens)),
    }


def entropy_trend(scores: list[float]) -> str:
    """Classify the trend of a series of entropy scores.

    Compares the mean of the last third to the mean of the first third.
    """
    if len(scores) < 3:
        return "insufficient-data"
    third = max(1, len(scores) // 3)
    early = mean(scores[:third])
    late = mean(scores[-third:])
    delta = late - early
    if delta > 0.3:
        return "diversifying"
    if delta < -0.3:
        return "narrowing"
    return "stable"


def entropy_report(result: dict) -> str:
    """Format an entropy analysis result as a human-readable string."""
    if "error" in result:
        return f"ERROR: {result['error']}"
    parts = [
        f"stroke entropy: {result['entropy']:.2f} bits",
        f"perplexity: {result['perplexity']:.1f} (effective vocab)",
        f"diminishing: {result['diminishing']:.2%} reuse rate",
        f"verdict: {result['verdict']}",
        f"window: {result['stroke_count']} strokes, "
        f"{result['token_count']} tokens, "
        f"{result['unique_tokens']} unique",
    ]
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# full analysis with trend
# ---------------------------------------------------------------------------


def analyze(
    path: Path = STROKES_PATH,
    window: int = 50,
) -> dict:
    """Full analysis: current window metrics + trend from history.

    Loads 2x window strokes to compute both current metrics and
    a diminishing baseline from the preceding window.
    """
    if not path.exists():
        return {"error": "strokes file not found", "path": str(path)}

    all_lines: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            all_lines.append(line)

    total_needed = window * 2
    recent_lines = (
        all_lines[-total_needed:] if len(all_lines) > total_needed else all_lines
    )

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
        current = strokes
        previous: list[dict] = []
    else:
        current = strokes[-window:]
        previous = (
            strokes[-(window * 2) : -window] if len(strokes) >= window * 2 else []
        )

    result = stroke_entropy(current, previous if previous else None)

    # Historical trend: split all loaded strokes into sequential chunks.
    chunk_size = max(10, window // 5)
    scores: list[float] = []
    prev_chunk: list[dict] = []
    for i in range(0, len(strokes), chunk_size):
        chunk = strokes[i : i + chunk_size]
        if len(chunk) < chunk_size // 2:
            break
        r = stroke_entropy(chunk, prev_chunk if prev_chunk else None)
        scores.append(r["entropy"])
        prev_chunk = chunk

    result["trend"] = entropy_trend(scores)
    result["history_scores"] = [round(s, 3) for s in scores]

    return result
