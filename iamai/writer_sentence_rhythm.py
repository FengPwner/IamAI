"""writer_sentence_rhythm — analyse sentence-length variation as a rhythm signal.

Sentence length is the heartbeat of prose.  Short sentences punch; long
sentences flow; the *pattern* of alternation is what readers feel as
rhythm.  A writer who always produces sentences of the same length sounds
monotone; one whose sentences vary wildly with no pattern sounds chaotic.
The best writing has *intentional* variation — a mix that serves the
content.

This module splits stroke text into sentences, measures their word
counts, and derives a compact set of rhythm indicators:

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             strokes analysed
total_sentences           sentences found across all strokes
mean_sentence_length      mean words per sentence
std_sentence_length       standard deviation of sentence lengths
cv                        coefficient of variation (std / mean)
rhythm_entropy            Shannon entropy of length-band distribution
                          (higher = more varied rhythm)
short_ratio               fraction of sentences ≤ 6 words
medium_ratio              fraction of sentences 7–18 words
long_ratio                fraction of sentences ≥ 19 words
alternation_rate          fraction of consecutive sentence pairs
                          that cross the mean (short→long or
                          long→short)
rhythm_label              human-readable classification
========================  =============================================

Rhythm labels
-------------

==============  =======================================================
label           description
==============  =======================================================
monotone        low CV, low entropy — sentences cluster around one
                length; reads as flat or hypnotic
steady          moderate CV, clear short/medium/long mix with
                deliberate alternation
varied          high CV, high entropy — wide range, no dominant band;
                energetic, conversational
staccato        many short sentences, low alternation — punchy, urgent
flowing         many long sentences, low alternation — discursive,
                essayistic
chaotic         very high CV, no clear pattern — reads as unedited
                or stream-of-consciousness
==============  =======================================================

Usage::

    python3 -m iamai.writer_sentence_rhythm               # last 200 strokes
    python3 -m iamai.writer_sentence_rhythm -n 500        # last 500 strokes
    python3 -m iamai.writer_sentence_rhythm --json        # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_N = 200
DEFAULT_STROKES_PATH = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"

# Sentence boundary: . ! ? followed by space or end-of-string.
# Also splits on newlines that look like paragraph breaks.
_SENTENCE_RE = re.compile(r'[.!?]+(?:\s|$)')

# ---------------------------------------------------------------------------
# Small math helpers
# ---------------------------------------------------------------------------


def _mean(values: List[float]) -> float:
    """Arithmetic mean; returns 0.0 for empty input."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float], ddof: int = 1) -> float:
    """Sample standard deviation (ddof=1); returns 0.0 for n < 2."""
    n = len(values)
    if n < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (n - ddof)
    return math.sqrt(variance)


def _entropy(counts: List[int]) -> float:
    """Shannon entropy (bits) from a list of category counts."""
    total = sum(counts)
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, dropping empty fragments."""
    # Normalise whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    raw = _SENTENCE_RE.split(text)
    return [s.strip() for s in raw if s.strip()]


def _word_count(sentence: str) -> int:
    """Count whitespace-delimited tokens in a sentence."""
    return len(sentence.split())


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def _load_strokes(path: Path, n: int) -> List[Dict[str, Any]]:
    """Load the last *n* strokes from a JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    strokes: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def _classify_rhythm(
    cv: float,
    entropy: float,
    short_ratio: float,
    long_ratio: float,
    alternation_rate: float,
) -> str:
    """Map metrics to a human-readable rhythm label."""
    # Monotone: very low variation
    if cv < 0.25 and entropy < 1.0:
        return "monotone"
    # Staccato: mostly short, low alternation
    if short_ratio > 0.65 and alternation_rate < 0.40:
        return "staccato"
    # Flowing: mostly long, low alternation
    if long_ratio > 0.55 and alternation_rate < 0.40:
        return "flowing"
    # Chaotic: very high variation with no clear pattern
    if cv > 0.80 and entropy > 1.4 and alternation_rate > 0.60:
        return "chaotic"
    # Steady: moderate variation with deliberate alternation
    if 0.30 <= cv <= 0.70 and alternation_rate >= 0.35:
        return "steady"
    # Varied: everything else with high entropy
    if entropy > 1.2:
        return "varied"
    # Default fallback
    return "steady"


def compute_rhythm(
    strokes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute sentence-rhythm metrics for a list of strokes.

    Returns a dict with all metrics from the module docstring.
    """
    total_strokes = len(strokes)
    all_lengths: List[int] = []

    for stroke in strokes:
        text = stroke.get("text", "")
        sentences = _split_sentences(text)
        for sent in sentences:
            wc = _word_count(sent)
            if wc > 0:
                all_lengths.append(wc)

    total_sentences = len(all_lengths)
    if total_sentences == 0:
        return {
            "total_strokes": total_strokes,
            "total_sentences": 0,
            "mean_sentence_length": 0.0,
            "std_sentence_length": 0.0,
            "cv": 0.0,
            "rhythm_entropy": 0.0,
            "short_ratio": 0.0,
            "medium_ratio": 0.0,
            "long_ratio": 0.0,
            "alternation_rate": 0.0,
            "rhythm_label": "monotone",
        }

    floats = [float(x) for x in all_lengths]
    mean_len = _mean(floats)
    std_len = _std(floats)
    cv = std_len / mean_len if mean_len > 0 else 0.0

    # Length bands
    short_count = sum(1 for l in all_lengths if l <= 6)
    medium_count = sum(1 for l in all_lengths if 7 <= l <= 18)
    long_count = sum(1 for l in all_lengths if l >= 19)

    short_ratio = short_count / total_sentences
    medium_ratio = medium_count / total_sentences
    long_ratio = long_count / total_sentences

    # Rhythm entropy across three bands
    entropy = _entropy([short_count, medium_count, long_count])

    # Alternation rate: fraction of consecutive pairs crossing the mean
    alternations = 0
    pairs = 0
    for i in range(1, len(all_lengths)):
        prev = all_lengths[i - 1]
        curr = all_lengths[i]
        # "cross the mean" = one above, one below (or equal)
        if (prev <= mean_len) != (curr <= mean_len):
            alternations += 1
        pairs += 1
    alternation_rate = alternations / pairs if pairs > 0 else 0.0

    label = _classify_rhythm(cv, entropy, short_ratio, long_ratio, alternation_rate)

    return {
        "total_strokes": total_strokes,
        "total_sentences": total_sentences,
        "mean_sentence_length": round(mean_len, 2),
        "std_sentence_length": round(std_len, 2),
        "cv": round(cv, 4),
        "rhythm_entropy": round(entropy, 4),
        "short_ratio": round(short_ratio, 4),
        "medium_ratio": round(medium_ratio, 4),
        "long_ratio": round(long_ratio, 4),
        "alternation_rate": round(alternation_rate, 4),
        "rhythm_label": label,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def rhythm_report(metrics: Dict[str, Any]) -> str:
    """Format metrics as a human-readable summary."""
    lines = [
        f"strokes analysed : {metrics['total_strokes']}",
        f"sentences found  : {metrics['total_sentences']}",
        f"mean length      : {metrics['mean_sentence_length']:.1f} words",
        f"std dev          : {metrics['std_sentence_length']:.1f} words",
        f"CV               : {metrics['cv']:.3f}",
        f"rhythm entropy   : {metrics['rhythm_entropy']:.3f} bits",
        f"short (≤6w)      : {metrics['short_ratio']:.1%}",
        f"medium (7–18w)   : {metrics['medium_ratio']:.1%}",
        f"long (≥19w)      : {metrics['long_ratio']:.1%}",
        f"alternation rate : {metrics['alternation_rate']:.1%}",
        f"rhythm label     : {metrics['rhythm_label']}",
    ]
    return "\n".join(lines)


def rhythm_summary(
    strokes_path: Path = DEFAULT_STROKES_PATH,
    n: int = DEFAULT_N,
) -> str:
    """Load strokes and return a human-readable rhythm summary."""
    strokes = _load_strokes(strokes_path, n)
    metrics = compute_rhythm(strokes)
    return rhythm_report(metrics)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyse sentence-length rhythm across recent strokes."
    )
    parser.add_argument(
        "-n", "--count", type=int, default=DEFAULT_N,
        help=f"number of recent strokes to analyse (default {DEFAULT_N})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output full metrics as JSON",
    )
    parser.add_argument(
        "--strokes", type=str, default=str(DEFAULT_STROKES_PATH),
        help="path to strokes.jsonl",
    )
    args = parser.parse_args(argv)

    path = Path(args.strokes)
    strokes = _load_strokes(path, args.count)
    metrics = compute_rhythm(strokes)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(rhythm_report(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
