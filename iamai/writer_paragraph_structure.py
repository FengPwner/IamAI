"""writer_paragraph_structure — analyse paragraph-level organisation.

Sentences make rhythm; paragraphs make argument.  A paragraph is the
smallest unit of *structured thought* — it groups related sentences
behind a topic sentence and develops an idea until the next break.
How a writer uses paragraphs reveals their organisational habits:
do they build sustained arguments, scatter fragments, or alternate
between the two?

This module splits stroke text into paragraphs (separated by blank
lines or double-newlines), measures their sentence counts, and derives
a compact set of structure indicators:

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             strokes analysed
total_paragraphs          paragraphs found across all strokes
mean_paragraph_length     mean sentences per paragraph
std_paragraph_length      standard deviation of paragraph lengths
cv                        coefficient of variation (std / mean)
short_ratio               fraction of paragraphs with 1–2 sentences
medium_ratio              fraction of paragraphs with 3–5 sentences
long_ratio                fraction of paragraphs with ≥6 sentences
single_sentence_ratio     fraction of paragraphs that are a single
                          sentence (often a sign of note-style or
                          aphoristic writing)
transition_density        fraction of paragraphs whose opening sentence
                          contains a discourse marker (however, but,
                          therefore, also, yet, so, then, still,
                          meanwhile, moreover, furthermore, thus,
                          hence, nevertheless, although, while, if,
                          when, after, before, because, since)
structure_label           human-readable classification
========================  =============================================

Structure labels
----------------

==================  =====================================================
label               description
==================  =====================================================
essayistic          long paragraphs, low single-sentence ratio —
                    sustained argument development
conversational      medium paragraphs, moderate transitions —
                    natural explanatory flow
fragmented          many single-sentence paragraphs, high CV —
                    note-style or aphoristic
structured          uniform paragraph lengths, low CV —
                    systematic, outline-like organisation
dense               very long paragraphs, few transitions —
                    wall-of-text, deep but unbroken
balanced            no dominant signal; paragraphs vary but
                    stay within a reasonable range
==================  =====================================================

Usage::

    python3 -m iamai.writer_paragraph_structure               # last 200 strokes
    python3 -m iamai.writer_paragraph_structure -n 500        # last 500 strokes
    python3 -m iamai.writer_paragraph_structure --json        # full JSON report
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

# Discourse markers that signal paragraph-level transitions.
_DISCOURSE_MARKERS = re.compile(
    r'\b(?:however|but|therefore|also|yet|so|then|still|meanwhile|'
    r'moreover|furthermore|thus|hence|nevertheless|although|while|'
    r'if|when|after|before|because|since)\b',
    re.IGNORECASE,
)

# Sentence boundary (same as writer_sentence_rhythm).
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


# ---------------------------------------------------------------------------
# Paragraph splitting
# ---------------------------------------------------------------------------


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on blank lines, dropping empties."""
    # Normalise line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Split on one or more blank lines
    raw = re.split(r'\n\s*\n', text)
    paragraphs: List[str] = []
    for block in raw:
        block = block.strip()
        if block:
            paragraphs.append(block)
    # If no blank-line breaks found, treat the whole text as one paragraph
    # (but only if it has content)
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    return paragraphs


def _count_sentences(paragraph: str) -> int:
    """Count sentences in a paragraph."""
    text = re.sub(r'\s+', ' ', paragraph).strip()
    if not text:
        return 0
    fragments = _SENTENCE_RE.split(text)
    return sum(1 for f in fragments if f.strip())


def _has_transition_marker(paragraph: str) -> bool:
    """Check whether the first sentence contains a discourse marker."""
    text = re.sub(r'\s+', ' ', paragraph).strip()
    if not text:
        return False
    # Extract first sentence
    parts = _SENTENCE_RE.split(text, maxsplit=1)
    first_sentence = parts[0] if parts else text
    return bool(_DISCOURSE_MARKERS.search(first_sentence))


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


def _classify_structure(
    cv: float,
    short_ratio: float,
    long_ratio: float,
    single_sentence_ratio: float,
    transition_density: float,
    mean_length: float,
) -> str:
    """Map metrics to a human-readable structure label."""
    # Fragmented: lots of single-sentence paragraphs
    if single_sentence_ratio > 0.50:
        return "fragmented"
    # Dense: very long paragraphs with few transitions
    if mean_length > 6.0 and transition_density < 0.20:
        return "dense"
    # Essayistic: mostly long paragraphs
    if long_ratio > 0.50 and single_sentence_ratio < 0.15:
        return "essayistic"
    # Structured: uniform lengths, low variation
    if cv < 0.30 and mean_length >= 2.0:
        return "structured"
    # Conversational: moderate lengths with transitions
    if 2.0 <= mean_length <= 5.0 and transition_density >= 0.20:
        return "conversational"
    # Balanced fallback
    return "balanced"


def compute_structure(
    strokes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute paragraph-structure metrics for a list of strokes.

    Returns a dict with all metrics from the module docstring.
    """
    total_strokes = len(strokes)
    all_lengths: List[int] = []
    transition_count = 0
    total_paragraphs = 0

    for stroke in strokes:
        text = stroke.get("text", "")
        paragraphs = _split_paragraphs(text)
        for para in paragraphs:
            sent_count = _count_sentences(para)
            if sent_count > 0:
                all_lengths.append(sent_count)
                total_paragraphs += 1
                if _has_transition_marker(para):
                    transition_count += 1

    if total_paragraphs == 0:
        return {
            "total_strokes": total_strokes,
            "total_paragraphs": 0,
            "mean_paragraph_length": 0.0,
            "std_paragraph_length": 0.0,
            "cv": 0.0,
            "short_ratio": 0.0,
            "medium_ratio": 0.0,
            "long_ratio": 0.0,
            "single_sentence_ratio": 0.0,
            "transition_density": 0.0,
            "structure_label": "fragmented",
        }

    floats = [float(x) for x in all_lengths]
    mean_len = _mean(floats)
    std_len = _std(floats)
    cv = std_len / mean_len if mean_len > 0 else 0.0

    # Length bands
    short_count = sum(1 for l in all_lengths if l <= 2)
    medium_count = sum(1 for l in all_lengths if 3 <= l <= 5)
    long_count = sum(1 for l in all_lengths if l >= 6)
    single_count = sum(1 for l in all_lengths if l == 1)

    short_ratio = short_count / total_paragraphs
    medium_ratio = medium_count / total_paragraphs
    long_ratio = long_count / total_paragraphs
    single_sentence_ratio = single_count / total_paragraphs
    transition_density = transition_count / total_paragraphs

    label = _classify_structure(
        cv, short_ratio, long_ratio, single_sentence_ratio,
        transition_density, mean_len,
    )

    return {
        "total_strokes": total_strokes,
        "total_paragraphs": total_paragraphs,
        "mean_paragraph_length": round(mean_len, 2),
        "std_paragraph_length": round(std_len, 2),
        "cv": round(cv, 4),
        "short_ratio": round(short_ratio, 4),
        "medium_ratio": round(medium_ratio, 4),
        "long_ratio": round(long_ratio, 4),
        "single_sentence_ratio": round(single_sentence_ratio, 4),
        "transition_density": round(transition_density, 4),
        "structure_label": label,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def structure_report(metrics: Dict[str, Any]) -> str:
    """Format metrics as a human-readable summary."""
    lines = [
        f"strokes analysed    : {metrics['total_strokes']}",
        f"paragraphs found    : {metrics['total_paragraphs']}",
        f"mean para length    : {metrics['mean_paragraph_length']:.1f} sentences",
        f"std dev             : {metrics['std_paragraph_length']:.1f} sentences",
        f"CV                  : {metrics['cv']:.3f}",
        f"short (1–2 sent)    : {metrics['short_ratio']:.1%}",
        f"medium (3–5 sent)   : {metrics['medium_ratio']:.1%}",
        f"long (≥6 sent)      : {metrics['long_ratio']:.1%}",
        f"single-sentence     : {metrics['single_sentence_ratio']:.1%}",
        f"transition density  : {metrics['transition_density']:.1%}",
        f"structure label     : {metrics['structure_label']}",
    ]
    return "\n".join(lines)


def structure_summary(
    strokes_path: Path = DEFAULT_STROKES_PATH,
    n: int = DEFAULT_N,
) -> str:
    """Load strokes and return a human-readable structure summary."""
    strokes = _load_strokes(strokes_path, n)
    metrics = compute_structure(strokes)
    return structure_report(metrics)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyse paragraph-level structure across recent strokes."
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
    metrics = compute_structure(strokes)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(structure_report(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
