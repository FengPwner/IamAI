"""writer_pre_stall_warning — early warning before a writer stalls.

A writer rarely stops without warning.  First the strokes get shorter,
then the topics narrow, then repetition climbs — and only then does the
process actually die.  This module scores those pre-stall signals so
that intervention can happen *before* the gap grows to 3000+ seconds.

Three independent signals feed into a composite warning score:

1. **content_diversity** — how many unique words appear in recent
   strokes relative to the total word count.  A healthy writer
   explores; a sick one repeats the same handful of phrases.

2. **repetition_ratio** — fraction of consecutive stroke pairs whose
   Jaccard similarity exceeds a threshold (default 0.6).  High
   repetition is the clearest early warning sign.

3. **length_trend** — is the writer producing shorter strokes over
   time?  Computed as the slope of a linear regression over the last
   N strokes' lengths, normalised to [-1, 1].

The composite **warning_score** is a weighted blend (0 = healthy,
1 = stall imminent).  ``alert_if_warning()`` prints a human-readable
verdict and exits 0/1 for use in shell pipelines.

Usage::

    from iamai.writer_pre_stall_warning import pre_stall_report

    report = pre_stall_report(n_strokes=50)
    print(report["warning_score"])     # e.g. 0.73
    print(report["verdict"])           # "warning"
    print(report["content_diversity"]) # e.g. 0.21
    print(report["repetition_ratio"])  # e.g. 0.68

CLI::

    python -m iamai.writer_pre_stall_warning --n 50 --json

Written by Qwen during caretaker visit 806, 2026-11-23.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Default paths / thresholds
# ---------------------------------------------------------------------------

_DEFAULT_STROKES = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
_DEFAULT_N = 50
_SIMILARITY_THRESHOLD = 0.6  # Jaccard threshold for "repetitive pair"
_DIVERSITY_WEIGHT = 0.30
_REPETITION_WEIGHT = 0.45
_LENGTH_WEIGHT = 0.25

# Warning thresholds on the composite score
_THRESHOLDS = {
    "healthy": 0.30,
    "watch": 0.50,
    "warning": 0.70,
    # anything above 0.70 is "critical"
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set:
    """Lowercase split on whitespace — good enough for diversity scoring."""
    return set(text.lower().split())


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets; 0.0 when both are empty."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


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
# Signal 1: content diversity
# ---------------------------------------------------------------------------


def content_diversity(strokes: Sequence[Dict[str, Any]]) -> float:
    """Fraction of unique tokens across *strokes*.

    Returns 0.0 when there are no tokens at all.
    A healthy writer scores above 0.4; a stalled one drops below 0.15.
    """
    all_tokens: List[str] = []
    for s in strokes:
        text = s.get("text", "")
        all_tokens.extend(text.lower().split())
    if not all_tokens:
        return 0.0
    unique = len(set(all_tokens))
    return unique / len(all_tokens)


# ---------------------------------------------------------------------------
# Signal 2: repetition ratio
# ---------------------------------------------------------------------------


def repetition_ratio(
    strokes: Sequence[Dict[str, Any]],
    threshold: float = _SIMILARITY_THRESHOLD,
) -> float:
    """Fraction of consecutive pairs with Jaccard similarity > *threshold*.

    Returns 0.0 when fewer than 2 strokes are provided.
    """
    if len(strokes) < 2:
        return 0.0
    token_sets = [_tokenize(s.get("text", "")) for s in strokes]
    high_sim = 0
    total = len(token_sets) - 1
    for i in range(total):
        if _jaccard(token_sets[i], token_sets[i + 1]) > threshold:
            high_sim += 1
    return high_sim / total


# ---------------------------------------------------------------------------
# Signal 3: length trend
# ---------------------------------------------------------------------------


def _linear_slope(values: Sequence[float]) -> float:
    """Return the slope of a simple linear regression over indices 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def length_trend(strokes: Sequence[Dict[str, Any]]) -> float:
    """Normalised length trend over *strokes*.

    Returns a value in [-1, 1]:
      -1.0  strokes are shrinking sharply
       0.0  stable length
      +1.0  strokes are growing

    The raw slope is divided by the mean length to make it comparable
    across writers with different baseline stroke sizes.
    """
    lengths = [len(s.get("text", "")) for s in strokes]
    if not lengths:
        return 0.0
    mean_len = sum(lengths) / len(lengths)
    if mean_len == 0:
        return 0.0
    slope = _linear_slope(lengths)
    # Normalise: slope / mean_len gives relative change per stroke
    normalised = slope / mean_len
    # Clamp to [-1, 1] using tanh for smooth saturation
    return math.tanh(normalised * 10)  # scale factor for sensitivity


# ---------------------------------------------------------------------------
# Composite warning score
# ---------------------------------------------------------------------------


def warning_score(
    strokes: Sequence[Dict[str, Any]],
    threshold: float = _SIMILARITY_THRESHOLD,
) -> float:
    """Composite pre-stall warning score in [0, 1].

    0.0 = healthy, 1.0 = stall almost certainly imminent.
    """
    if not strokes:
        return 1.0  # no strokes → definitely stalled

    div = content_diversity(strokes)
    rep = repetition_ratio(strokes, threshold)
    lt = length_trend(strokes)

    # Low diversity is bad → invert
    div_signal = max(0.0, 1.0 - div / 0.5)  # saturate at diversity=0.5
    # High repetition is bad → direct
    rep_signal = rep
    # Shrinking strokes are bad → only penalise negative trend
    len_signal = max(0.0, -lt)  # only care about shrinking, not growing

    score = (
        _DIVERSITY_WEIGHT * div_signal
        + _REPETITION_WEIGHT * rep_signal
        + _LENGTH_WEIGHT * len_signal
    )
    return min(1.0, max(0.0, score))


def verdict(score: float) -> str:
    """Map a warning score to a human-readable verdict."""
    if score <= _THRESHOLDS["healthy"]:
        return "healthy"
    if score <= _THRESHOLDS["watch"]:
        return "watch"
    if score <= _THRESHOLDS["warning"]:
        return "warning"
    return "critical"


# ---------------------------------------------------------------------------
# Report / CLI
# ---------------------------------------------------------------------------


def pre_stall_report(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """Produce a full pre-stall warning report."""
    strokes = _load_recent_strokes(n=n_strokes, path=path)
    div = content_diversity(strokes)
    rep = repetition_ratio(strokes, threshold)
    lt = length_trend(strokes)
    ws = warning_score(strokes, threshold)

    return {
        "n_strokes_analysed": len(strokes),
        "content_diversity": round(div, 4),
        "repetition_ratio": round(rep, 4),
        "length_trend": round(lt, 4),
        "warning_score": round(ws, 4),
        "verdict": verdict(ws),
    }


def pre_stall_summary(
    n_strokes: int = _DEFAULT_N,
    path: Optional[Path] = None,
) -> str:
    """One-line human summary for dashboards and caretaker notes."""
    r = pre_stall_report(n_strokes=n_strokes, path=path)
    return (
        f"pre-stall: {r['verdict']} (score {r['warning_score']:.2f}) "
        f"| diversity {r['content_diversity']:.2f} "
        f"| repetition {r['repetition_ratio']:.2f} "
        f"| length_trend {r['length_trend']:+.2f} "
        f"| {r['n_strokes_analysed']} strokes"
    )


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-stall early warning for the IamAI writer."
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

    report = pre_stall_report(n_strokes=args.n, path=args.path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(pre_stall_summary(n_strokes=args.n, path=args.path))

    return 0 if report["verdict"] in ("healthy", "watch") else 1


if __name__ == "__main__":
    sys.exit(_cli())
