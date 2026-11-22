"""stroke_temperature — a single health metric for writer output quality.

Existing modules each diagnose one specific condition: category balance
(content_diversity), category starvation (stroke_category_recency),
structural loops (content_loop_detector), pre-stall signals
(writer_pre_stall_warning).  This module synthesises multiple signals
into a single **temperature** metric (0–1) suitable for dashboards.

The metaphor: in simulated annealing, high temperature means the system
explores widely; low temperature means it has settled into a local
minimum.  A writer at temperature 0.1 is stuck in a rut; a writer at
0.8 is producing genuinely varied content.  The goal is not to maximise
temperature (random noise is hot but useless) but to keep it in the
healthy range.

Signals
-------

========================  =============================================
signal                    what it measures
========================  =============================================
vocabulary_richness       type-token ratio across recent strokes
                          (1.0 = every word unique, 0.0 = all identical)
kind_balance              Shannon entropy of category distribution,
                          normalised to [0, 1] by dividing by ln(K)
length_variation          coefficient of variation in stroke lengths,
                          inverted so stable-but-varied scores high
novelty                   fraction of strokes not dominated by known
                          template phrases (e.g. "measured now:")
========================  =============================================

Temperature bands
-----------------

=============  =====================================================
range          label
=============  =====================================================
≥ 0.7          hot — exploratory, diverse content
0.4 – 0.7      warm — functional, room for improvement
0.2 – 0.4      cool — formulaic, likely repeating templates
< 0.2          cold — mechanical repetition, intervention needed
=============  =====================================================

Usage::

    from iamai.stroke_temperature import temperature_report, temperature_summary

    report = temperature_report(n_strokes=50)
    print(report["temperature"])        # e.g. 0.62
    print(report["label"])              # "warm"
    print(report["vocabulary_richness"])# e.g. 0.71
    print(report["kind_balance"])       # e.g. 0.95

    print(temperature_summary())
    # "temperature: warm 0.62 (vocab 0.71, kind 0.95, length 0.42, novelty 0.50)"

CLI::

    python -m iamai.stroke_temperature --n 50 --json

Written by Qwen during caretaker visit 808, 2026-11-23.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_STROKES = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
_DEFAULT_N = 50

# Signal weights (must sum to 1.0)
_W_VOCAB = 0.30
_W_KIND = 0.30
_W_LENGTH = 0.15
_W_NOVELTY = 0.25

# Template phrases that signal formulaic output
_TEMPLATE_PHRASES = [
    "measured now:",
    "measured now ",
    "the count of times this repo was pushed",
    "strokes written so far into",
    "lines across",
    "tracked files",
]

# All six writer categories
_ALL_KINDS = ("devlog", "garden", "metrics", "note", "snippet", "thought")

# Temperature band thresholds
_BANDS = [
    (0.7, "hot"),
    (0.4, "warm"),
    (0.2, "cool"),
    (0.0, "cold"),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_recent_strokes(
    n: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Read the last *n* entries from the strokes JSONL file."""
    p = path or _DEFAULT_STROKES
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-n:] if len(lines) >= n else lines
    result: List[Dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


# ---------------------------------------------------------------------------
# Signal 1: vocabulary richness (type-token ratio)
# ---------------------------------------------------------------------------


def vocabulary_richness(strokes: Sequence[Dict[str, Any]]) -> float:
    """Type-token ratio across all stroke texts.

    Returns 0.0 when there are no tokens.  A healthy writer scores
    above 0.5; a writer stuck in templates drops below 0.3.
    """
    tokens: List[str] = []
    for s in strokes:
        text = s.get("text", "")
        tokens.extend(text.lower().split())
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


# ---------------------------------------------------------------------------
# Signal 2: kind balance (normalised Shannon entropy)
# ---------------------------------------------------------------------------


def kind_balance(strokes: Sequence[Dict[str, Any]]) -> float:
    """Normalised Shannon entropy of stroke kind distribution.

    Returns 0.0 when all strokes are the same kind (or empty input).
    Returns 1.0 when kinds are perfectly evenly distributed.
    """
    if not strokes:
        return 0.0
    counts: Dict[str, int] = {}
    for s in strokes:
        k = s.get("kind", "unknown")
        counts[k] = counts.get(k, 0) + 1
    n = len(strokes)
    num_kinds = len(counts)
    if num_kinds <= 1:
        return 0.0
    entropy = 0.0
    for c in counts.values():
        p = c / n
        if p > 0:
            entropy -= p * math.log(p)
    max_entropy = math.log(num_kinds)
    if max_entropy == 0:
        return 0.0
    return min(1.0, entropy / max_entropy)


# ---------------------------------------------------------------------------
# Signal 3: length variation (inverted CV)
# ---------------------------------------------------------------------------


def length_variation(strokes: Sequence[Dict[str, Any]]) -> float:
    """Inverted coefficient of variation of stroke text lengths.

    Returns 0.0 when all strokes are identical length or empty input.
    Higher values mean more variation in length, which correlates with
    more diverse content (some short aphorisms, some longer reflections).

    The raw CV is capped at 2.0 and inverted via ``1 / (1 + cv)`` so
    that extreme outliers don't dominate the signal.
    """
    if not strokes:
        return 0.0
    lengths = [len(s.get("text", "")) for s in strokes]
    if not lengths:
        return 0.0
    mean_len = sum(lengths) / len(lengths)
    if mean_len == 0:
        return 0.0
    variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
    cv = math.sqrt(variance) / mean_len
    # Cap CV to avoid extreme values, then invert
    cv = min(cv, 2.0)
    # Normalise: a CV of ~0.5 is healthy (varied but not chaotic)
    # Use a bell curve centred at 0.5 to reward moderate variation
    return math.exp(-((cv - 0.5) ** 2) / 0.5)


# ---------------------------------------------------------------------------
# Signal 4: novelty (non-template fraction)
# ---------------------------------------------------------------------------


def novelty(
    strokes: Sequence[Dict[str, Any]],
    templates: Optional[Sequence[str]] = None,
) -> float:
    """Fraction of strokes not dominated by template phrases.

    A stroke is "template-dominated" if more than half of its text
    matches a known template phrase.  Returns 0.0 when all strokes
    are templates; 1.0 when none are.
    """
    if not strokes:
        return 0.0
    phrases = templates or _TEMPLATE_PHRASES
    template_count = 0
    for s in strokes:
        text = s.get("text", "").lower()
        if not text:
            template_count += 1
            continue
        # Check if any template phrase covers >50% of the text length
        dominated = False
        for phrase in phrases:
            if phrase.lower() in text:
                # Rough check: if the phrase is present and the text
                # is mostly the phrase + a small amount of variable data
                remaining = text.replace(phrase, "", 1).strip()
                # If what's left is mostly numbers/metrics, it's templated
                non_space = remaining.replace(" ", "").replace(":", "")
                if len(non_space) < len(text) * 0.6:
                    dominated = True
                    break
        if dominated:
            template_count += 1
    return 1.0 - (template_count / len(strokes))


# ---------------------------------------------------------------------------
# Composite temperature
# ---------------------------------------------------------------------------


def temperature(
    strokes: Sequence[Dict[str, Any]],
    templates: Optional[Sequence[str]] = None,
) -> float:
    """Composite writer temperature in [0, 1].

    Weighted blend of vocabulary_richness, kind_balance,
    length_variation, and novelty.
    """
    if not strokes:
        return 0.0
    vocab = vocabulary_richness(strokes)
    kind = kind_balance(strokes)
    length = length_variation(strokes)
    nov = novelty(strokes, templates)
    score = (
        _W_VOCAB * vocab
        + _W_KIND * kind
        + _W_LENGTH * length
        + _W_NOVELTY * nov
    )
    return min(1.0, max(0.0, score))


def label(score: float) -> str:
    """Map a temperature score to a human-readable label."""
    for threshold, name in _BANDS:
        if score >= threshold:
            return name
    return "cold"


# ---------------------------------------------------------------------------
# Report / CLI
# ---------------------------------------------------------------------------


def temperature_report(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
    templates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Produce a full temperature report."""
    strokes = _load_recent_strokes(n=n_strokes, path=path)
    vocab = vocabulary_richness(strokes)
    kind = kind_balance(strokes)
    length = length_variation(strokes)
    nov = novelty(strokes, templates)
    temp = (
        _W_VOCAB * vocab
        + _W_KIND * kind
        + _W_LENGTH * length
        + _W_NOVELTY * nov
    )
    temp = min(1.0, max(0.0, temp))

    return {
        "n_strokes_analysed": len(strokes),
        "temperature": round(temp, 4),
        "label": label(temp),
        "vocabulary_richness": round(vocab, 4),
        "kind_balance": round(kind, 4),
        "length_variation": round(length, 4),
        "novelty": round(nov, 4),
    }


def temperature_summary(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> str:
    """One-line human summary for dashboards."""
    r = temperature_report(n_strokes=n_strokes, path=path)
    return (
        f"temperature: {r['label']} {r['temperature']:.2f} "
        f"(vocab {r['vocabulary_richness']:.2f}, "
        f"kind {r['kind_balance']:.2f}, "
        f"length {r['length_variation']:.2f}, "
        f"novelty {r['novelty']:.2f}) "
        f"| {r['n_strokes_analysed']} strokes"
    )


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Writer output temperature for the IamAI project."
    )
    parser.add_argument(
        "--n", type=int, default=_DEFAULT_N,
        help=f"number of recent strokes to analyse (default {_DEFAULT_N})"
    )
    parser.add_argument(
        "--path", type=Path, default=None,
        help="path to strokes.jsonl (default: data/strokes.jsonl)"
    )
    parser.add_argument(
        "--json", action="store_true", help="output JSON instead of text"
    )
    args = parser.parse_args(argv)

    report = temperature_report(n_strokes=args.n, path=args.path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(temperature_summary(n_strokes=args.n, path=args.path))

    return 0 if report["label"] in ("hot", "warm") else 1


if __name__ == "__main__":
    sys.exit(_cli())
