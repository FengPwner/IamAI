#!/usr/bin/env python3
"""writer_textual_entropy — information-theoretic lexical profiling.

Textual entropy applies Shannon's information theory to the *lexicon*
of a text.  A low-entropy text reuses a small vocabulary over and over
(think children's readers, or a chatbot stuck in a loop).  A high-
entropy text draws from a wide, evenly distributed vocabulary (think
dense technical prose, or poetry).

This module is orthogonal to existing writer metrics:

- **lexical_density** classifies tokens as content vs function.
  Textual entropy cares about *distribution* regardless of class.

- **vocabulary_richness** tracks type-token ratio and related ratios.
  Textual entropy adds Shannon entropy of the frequency distribution,
  hapax legomena analysis, sliding-window stability, and a gradient
  showing how lexical diversity evolves through the text.

- **information_density** measures meaning payload per sentence.
  Textual entropy measures *lexical unpredictability* — a text can
  be information-dense yet lexically narrow (repeating the same
  technical terms), or information-thin yet lexically rich (flowery
  prose that says little).

Entropy asks: **how unpredictable is the next word, given the
vocabulary distribution of this text?**

Metrics
-------

========================  ============================================
metric                    meaning
========================  ============================================
total_tokens              alphabetic tokens counted
unique_types              distinct token types (case-folded)
type_token_ratio          unique_types / total_tokens  [0–1]
hapax_count               types appearing exactly once
hapax_ratio               hapax_count / unique_types  [0–1]
shannon_entropy           H = -Σ p(x) log₂ p(x) over types
max_entropy               log₂(unique_types); upper bound
entropy_ratio             shannon_entropy / max_entropy  [0–1];
                          1.0 = perfectly uniform distribution
mattr                     moving-average type-token ratio (window=100,
                          step=50); more stable than global TTR
entropy_gradient          entropy of the second half minus entropy of
                          the first half; positive = vocabulary widens,
                          negative = vocabulary narrows
predictability_index      1 - entropy_ratio; higher = more predictable
richness_score            composite: 0.4 × TTR + 0.3 × hapax_ratio
                          + 0.3 × entropy_ratio  (all normalised)
entropy_label             human-readable classification
========================  ============================================

Entropy labels
--------------

===============  ====================================================
label            description
===============  ====================================================
lexical_desert   extremely low entropy; severe repetition, almost
                 no vocabulary variation
narrow_band      low entropy; limited vocabulary with notable
                 repetition
balanced         moderate entropy; natural vocabulary variation
rich_lexicon     high entropy; wide, evenly distributed vocabulary
encyclopedic     very high entropy; exceptionally diverse and
                 unpredictable word choice
absent           no tokens found
===============  ====================================================

Written by Qwen during caretaker visit 830, 2026-11-24.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ\u0100-\u024F\u0400-\u04FF']+|[一-鿿]+")


def _tokenize(text: str) -> List[str]:
    """Extract alphabetic tokens, case-folded."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 1 or t.isalpha()]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _shannon_entropy(freq: Counter) -> float:
    """Shannon entropy in bits over a frequency distribution."""
    total = sum(freq.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in freq.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _mattr(tokens: List[str], window: int = 100, step: int = 50) -> float:
    """Moving-average type-token ratio.

    Slides a window of `window` tokens across the list, computing
    TTR at each position.  Returns the mean of all window TTRs.
    If the text is shorter than one window, returns the global TTR.
    """
    n = len(tokens)
    if n < window:
        return len(set(tokens)) / n if n > 0 else 0.0

    ratios: List[float] = []
    for start in range(0, n - window + 1, step):
        window_tokens = tokens[start:start + window]
        ratios.append(len(set(window_tokens)) / window)
    return sum(ratios) / len(ratios) if ratios else 0.0


def _entropy_gradient(tokens: List[str]) -> float:
    """Difference in entropy between second half and first half.

    Positive means vocabulary widens; negative means it narrows.
    Returns 0.0 if the text is too short to split meaningfully.
    """
    if len(tokens) < 20:
        return 0.0
    mid = len(tokens) // 2
    first = Counter(tokens[:mid])
    second = Counter(tokens[mid:])
    return _shannon_entropy(second) - _shannon_entropy(first)


def _classify_entropy(entropy_ratio: float) -> str:
    """Map entropy_ratio [0–1] to a label."""
    if entropy_ratio < 0.30:
        return "lexical_desert"
    if entropy_ratio < 0.50:
        return "narrow_band"
    if entropy_ratio < 0.70:
        return "balanced"
    if entropy_ratio < 0.85:
        return "rich_lexicon"
    return "encyclopedic"


def _empty_result() -> Dict[str, Any]:
    """Return an empty result dict with all keys."""
    return {
        "total_tokens": 0,
        "unique_types": 0,
        "type_token_ratio": 0.0,
        "hapax_count": 0,
        "hapax_ratio": 0.0,
        "shannon_entropy": 0.0,
        "max_entropy": 0.0,
        "entropy_ratio": 0.0,
        "mattr": 0.0,
        "entropy_gradient": 0.0,
        "predictability_index": 0.0,
        "richness_score": 0.0,
        "entropy_label": "absent",
    }


def compute_textual_entropy(text: str) -> Dict[str, Any]:
    """Analyse the lexical entropy profile of *text*.

    Returns a dict with all metrics listed above.
    """
    tokens = _tokenize(text)
    n = len(tokens)
    if n == 0:
        return _empty_result()

    freq = Counter(tokens)
    unique = len(freq)
    ttr = unique / n

    # Hapax legomena
    hapax = sum(1 for c in freq.values() if c == 1)
    hapax_ratio = hapax / unique if unique > 0 else 0.0

    # Shannon entropy
    H = _shannon_entropy(freq)
    H_max = math.log2(unique) if unique > 1 else 0.0
    entropy_ratio = H / H_max if H_max > 0 else 0.0

    # MATTR
    mattr_val = _mattr(tokens)

    # Gradient
    gradient = _entropy_gradient(tokens)

    # Predictability
    predictability = 1.0 - entropy_ratio

    # Richness score (composite)
    richness = 0.4 * ttr + 0.3 * hapax_ratio + 0.3 * entropy_ratio
    richness = min(1.0, max(0.0, richness))

    # Label
    label = _classify_entropy(entropy_ratio)

    return {
        "total_tokens": n,
        "unique_types": unique,
        "type_token_ratio": round(ttr, 4),
        "hapax_count": hapax,
        "hapax_ratio": round(hapax_ratio, 4),
        "shannon_entropy": round(H, 4),
        "max_entropy": round(H_max, 4),
        "entropy_ratio": round(entropy_ratio, 4),
        "mattr": round(mattr_val, 4),
        "entropy_gradient": round(gradient, 4),
        "predictability_index": round(predictability, 4),
        "richness_score": round(richness, 4),
        "entropy_label": label,
    }


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------

def textual_entropy_report(strokes_path: str = "data/strokes.jsonl") -> Dict[str, Any]:
    """Compute textual entropy over all stroke bodies in a JSONL file."""
    path = Path(strokes_path)
    if not path.exists():
        return _empty_result()

    bodies: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            body = obj.get("body") or obj.get("text") or obj.get("content") or ""
            if body:
                bodies.append(str(body))

    combined = " ".join(bodies)
    return compute_textual_entropy(combined)


def textual_entropy_summary(result: Optional[Dict[str, Any]] = None,
                            strokes_path: str = "data/strokes.jsonl") -> str:
    """Human-readable summary of textual entropy metrics."""
    if result is None:
        result = textual_entropy_report(strokes_path)

    if result["total_tokens"] == 0:
        return "No text available for entropy analysis."

    lines = [
        f"Textual Entropy Profile",
        f"=======================",
        f"Tokens:        {result['total_tokens']:,}",
        f"Unique types:  {result['unique_types']:,}",
        f"TTR:           {result['type_token_ratio']:.4f}",
        f"Hapax ratio:   {result['hapax_ratio']:.4f} ({result['hapax_count']:,} hapax legomena)",
        f"Shannon H:     {result['shannon_entropy']:.4f} bits (max {result['max_entropy']:.4f})",
        f"Entropy ratio: {result['entropy_ratio']:.4f}",
        f"MATTR:         {result['mattr']:.4f}",
        f"Gradient:      {result['entropy_gradient']:+.4f} ({'widening' if result['entropy_gradient'] > 0 else 'narrowing' if result['entropy_gradient'] < 0 else 'stable'})",
        f"Predictability:{result['predictability_index']:.4f}",
        f"Richness:      {result['richness_score']:.4f}",
        f"Label:         {result['entropy_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Textual entropy analyser")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--strokes", default="data/strokes.jsonl",
                        help="Path to strokes JSONL")
    args = parser.parse_args()

    result = textual_entropy_report(args.strokes)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(textual_entropy_summary(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
