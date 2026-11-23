"""writer_punctuation_profile — analyse punctuation patterns as a style signal.

Punctuation is the skeleton of prose.  Commas control breathing; colons
introduce; semicolons connect; dashes interrupt; parentheses whisper.
The distribution of these marks across a body of text reveals the
writer's structural habits — formal, conversational, fragmented, or
balanced — independent of *what* they write about.

This module counts punctuation marks relative to text volume and derives
a set of style indicators that are orthogonal to existing metrics:

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             strokes analysed
total_words               total word count across all strokes
punctuation_density       punctuation marks per 100 words
comma_ratio               commas per sentence
semicolon_ratio           semicolons per sentence
colon_ratio               colons per sentence
dash_ratio                em/en-dashes per sentence
question_ratio            fraction of sentences ending in '?'
exclamation_ratio         fraction of sentences ending in '!'
parenthetical_ratio       parenthetical groups per sentence
ellipsis_ratio            ellipses per sentence
formality_index           composite: high semicolons + colons, low
                          exclamations → more formal register
fragmentation_index       high dashes + ellipses + fragments →
                          more interrupted, stream-of-consciousness
style_label               human-readable classification
========================  =============================================

Style labels
------------

==================  =====================================================
label               description
==================  =====================================================
formal              high formality index, low fragmentation
conversational      moderate punctuation, some questions/exclamations
telegraphic         very low punctuation density — terse, note-style
structured          high colons/semicolons, systematic organisation
fragmented          high dashes/ellipses — stream of consciousness
balanced            no dominant signal; punctuation evenly distributed
==================  =====================================================

Usage::

    python3 -m iamai.writer_punctuation_profile               # last 200 strokes
    python3 -m iamai.writer_punctuation_profile -n 500        # last 500 strokes
    python3 -m iamai.writer_punctuation_profile --json        # full JSON report
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

# Sentence-splitting pattern: . ! ? followed by space or end-of-string
_SENTENCE_RE = re.compile(r'[.!?]+(?:\s|$)')

# Punctuation categories (compiled once)
_COMMA_RE = re.compile(r',')
_SEMICOLON_RE = re.compile(r';')
_COLON_RE = re.compile(r':')
_DASH_RE = re.compile(r'[—–-](?=\s)|\s--\s')  # em-dash, en-dash, or spaced double-hyphen
_QUESTION_RE = re.compile(r'\?')
_EXCLAMATION_RE = re.compile(r'!')
_PAREN_RE = re.compile(r'\([^)]*\)')
_ELLIPSIS_RE = re.compile(r'\.{3}|…')
_WORD_RE = re.compile(r'\b\w+\b')


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _load_strokes(path: Path, n: int) -> List[Dict[str, Any]]:
    """Load the last *n* strokes from a JSONL file."""
    strokes: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    return strokes[-n:]


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on terminal punctuation."""
    matches = _SENTENCE_RE.findall(text)
    return max(len(matches), 1)  # at least 1 if there's any text


def _count_words(text: str) -> int:
    """Count words using the word boundary pattern."""
    return len(_WORD_RE.findall(text))


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Divide with a default for zero denominators."""
    return a / b if b > 0 else default


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def analyse_text(texts: List[str]) -> Dict[str, Any]:
    """Compute punctuation profile from a list of text strings.

    Returns all metrics as a dictionary.
    """
    if not texts:
        return _empty_report()

    all_text = " ".join(texts)
    total_words = _count_words(all_text)
    if total_words == 0 and not any(t.strip() for t in texts):
        return _empty_report()
    if total_words == 0:
        total_words = 1  # avoid division by zero for punctuation-only text

    # Aggregate counts
    total_sentences = sum(_count_sentences(t) for t in texts)

    commas = sum(len(_COMMA_RE.findall(t)) for t in texts)
    semicolons = sum(len(_SEMICOLON_RE.findall(t)) for t in texts)
    colons = sum(len(_COLON_RE.findall(t)) for t in texts)
    dashes = sum(len(_DASH_RE.findall(t)) for t in texts)
    questions = sum(len(_QUESTION_RE.findall(t)) for t in texts)
    exclamations = sum(len(_EXCLAMATION_RE.findall(t)) for t in texts)
    parens = sum(len(_PAREN_RE.findall(t)) for t in texts)
    ellipses = sum(len(_ELLIPSIS_RE.findall(t)) for t in texts)

    # Total punctuation marks (approximate: sum of tracked categories)
    total_punct = commas + semicolons + colons + dashes + questions + exclamations + parens * 2 + ellipses * 3

    # Derived metrics
    punct_density = round(_safe_div(total_punct * 100.0, total_words), 2)
    comma_ratio = round(_safe_div(commas, total_sentences), 4)
    semicolon_ratio = round(_safe_div(semicolons, total_sentences), 4)
    colon_ratio = round(_safe_div(colons, total_sentences), 4)
    dash_ratio = round(_safe_div(dashes, total_sentences), 4)
    question_ratio = round(_safe_div(questions, total_sentences), 4)
    exclamation_ratio = round(_safe_div(exclamations, total_sentences), 4)
    parenthetical_ratio = round(_safe_div(parens, total_sentences), 4)
    ellipsis_ratio = round(_safe_div(ellipses, total_sentences), 4)

    # Formality index: semicolons + colons are formal markers;
    # exclamations are informal markers.
    formal_marks = semicolon_ratio + colon_ratio
    informal_marks = exclamation_ratio
    formality_raw = formal_marks / (formal_marks + informal_marks + 0.01)
    # Normalise to 0-1 using a soft curve
    formality_index = round(min(1.0, max(0.0, formality_raw)), 4)

    # Fragmentation index: dashes + ellipses indicate interrupted prose
    frag_marks = dash_ratio + ellipsis_ratio * 2  # ellipses are stronger fragments
    fragmentation_index = round(min(1.0, frag_marks / 0.5), 4)  # 0.5 = saturation point

    # Style classification
    style_label = _classify_style(
        punct_density, formality_index, fragmentation_index,
        question_ratio, colon_ratio, semicolon_ratio
    )

    return {
        "total_strokes": len(texts),
        "total_words": total_words,
        "total_sentences": total_sentences,
        "punctuation_density": punct_density,
        "comma_ratio": comma_ratio,
        "semicolon_ratio": semicolon_ratio,
        "colon_ratio": colon_ratio,
        "dash_ratio": dash_ratio,
        "question_ratio": question_ratio,
        "exclamation_ratio": exclamation_ratio,
        "parenthetical_ratio": parenthetical_ratio,
        "ellipsis_ratio": ellipsis_ratio,
        "formality_index": formality_index,
        "fragmentation_index": fragmentation_index,
        "style_label": style_label,
    }


def _empty_report() -> Dict[str, Any]:
    return {
        "total_strokes": 0,
        "total_words": 0,
        "total_sentences": 0,
        "punctuation_density": 0.0,
        "comma_ratio": 0.0,
        "semicolon_ratio": 0.0,
        "colon_ratio": 0.0,
        "dash_ratio": 0.0,
        "question_ratio": 0.0,
        "exclamation_ratio": 0.0,
        "parenthetical_ratio": 0.0,
        "ellipsis_ratio": 0.0,
        "formality_index": 0.0,
        "fragmentation_index": 0.0,
        "style_label": "empty",
    }


def _classify_style(
    punct_density: float,
    formality: float,
    fragmentation: float,
    question_ratio: float,
    colon_ratio: float,
    semicolon_ratio: float,
) -> str:
    """Classify the writing style based on punctuation patterns."""
    # Telegraphic: very sparse punctuation
    if punct_density < 3.0:
        return "telegraphic"

    # Structured: heavy use of colons and semicolons
    if colon_ratio + semicolon_ratio > 0.3:
        return "structured"

    # Fragmented: lots of dashes and ellipses
    if fragmentation > 0.5:
        return "fragmented"

    # Formal: high formality index, low questions
    if formality > 0.65 and question_ratio < 0.08:
        return "formal"

    # Conversational: many questions or low formality
    if question_ratio > 0.12 or formality < 0.35:
        return "conversational"

    return "balanced"


# ---------------------------------------------------------------------------
# Report / summary
# ---------------------------------------------------------------------------


def profile_report(
    n: int = DEFAULT_N,
    strokes_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Full punctuation profile from the on-disk strokes file."""
    path = strokes_path or DEFAULT_STROKES_PATH
    strokes = _load_strokes(path, n)
    texts = [s.get("text", "") for s in strokes if s.get("text")]
    return analyse_text(texts)


def profile_summary(report: Dict[str, Any]) -> str:
    """One-paragraph human-readable summary."""
    n = report["total_strokes"]
    if n == 0:
        return "No strokes to analyse."

    style = report["style_label"]
    density = report["punctuation_density"]
    formality = report["formality_index"]
    frag = report["fragmentation_index"]

    parts = [f"writer_punctuation_profile: {n} strokes, style={style}"]
    parts.append(f"punctuation density {density:.1f}/100 words")
    parts.append(f"formality {formality:.2f}")
    parts.append(f"fragmentation {frag:.2f}")

    if report["question_ratio"] > 0.1:
        parts.append(f"questions {report['question_ratio']:.1%} of sentences")
    if report["dash_ratio"] > 0.1:
        parts.append(f"dashes {report['dash_ratio']:.2f}/sentence")

    return ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyse punctuation patterns as a writing-style signal."
    )
    parser.add_argument(
        "-n", "--strokes", type=int, default=DEFAULT_N,
        help=f"number of recent strokes to analyse (default {DEFAULT_N})"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit full JSON report"
    )
    args = parser.parse_args(argv)

    report = profile_report(n=args.strokes)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(profile_summary(report))

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
