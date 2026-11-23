#!/usr/bin/env python3
"""writer_register_shift — detect formality / register shifts in text.

A writer's *register* is the level of formality they adopt: casual and
conversational at one end, academic and institutional at the other.
Good writers shift register deliberately — for emphasis, humour, or
audience adaptation.  Unintended shifts, however, signal inconsistency:
a technical report that suddenly drops into slang, or a personal essay
that lapses into bureaucratese.

This module quantifies register at the segment level, then measures how
stable or volatile the register is across the whole text.

========================  =============================================
metric                    meaning
========================  =============================================
total_segments            segments (paragraphs) analysed
mean_formality            mean formality score in [0, 1];
                          0 = very informal, 1 = very formal
formality_std             standard deviation of segment scores;
                          low = consistent register
formality_range           max − min segment score
shift_count               number of adjacent-segment jumps exceeding
                          the *shift_threshold*
shift_rate                shift_count / (total_segments − 1);
                          fraction of transitions that are shifts
max_shift                 largest single adjacent-segment jump
shift_direction           net direction: ``formalising`` (text gets
                          more formal), ``informalising`` (gets more
                          casual), or ``stable``
register_label            human-readable classification
========================  =============================================

Register labels
---------------

================  =====================================================
label             description
================  =====================================================
consistent        very low variation; register is uniform throughout
mostly_stable     minor fluctuations but no major shifts
mixed             moderate variation with some noticeable shifts
volatile          frequent or large register jumps
formalising       clear trend from informal → formal over the text
informalising     clear trend from formal → informal over the text
================  =====================================================

Usage::

    python3 -m iamai.writer_register_shift              # last 200 strokes
    python3 -m iamai.writer_register_shift -n 500       # last 500 strokes
    python3 -m iamai.writer_register_shift --json       # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STROKES_FILE = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"

# Informal markers — presence pushes score toward 0
_INFORMAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(gonna|wanna|gotta|kinda|sorta|yeah|nope|yep|nah)\b", re.I),
    re.compile(r"\b(lol|haha|omg|btw|imo|tbh|idk|smh|ngl|fr)\b", re.I),
    re.compile(r"\b(stuff|things|guys|kids|folks|cool|awesome|crazy|nuts)\b", re.I),
    re.compile(r"\b(super|totally|literally|basically|honestly|literally)\b", re.I),
    re.compile(r"\b(get|got|getting|gotta)\b", re.I),
    re.compile(r"'(?:s|t|re|ve|ll|d|m)\b"),                    # contractions
    re.compile(r"!{1,}"),                                        # exclamations
    re.compile(r"\.{2,}"),                                       # trailing dots
    re.compile(r"\b(okay|ok|alright|sure|whatever)\b", re.I),
]

# Formal markers — presence pushes score toward 1
_FORMAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(furthermore|moreover|consequently|nevertheless|"
               r"notwithstanding|hence|thus|therefore|whereas)\b", re.I),
    re.compile(r"\b(pursuant|aforementioned|herein|thereof|whereby|"
               r"notwithstanding|viz|ergo)\b", re.I),
    re.compile(r"\b(shall|ought|must|may|might|could|would)\b", re.I),
    re.compile(r"\b(utilize|utilise|implement|facilitate|demonstrate|"
               r"establish|constitute|encompass|pertain)\b", re.I),
    re.compile(r"\b(in accordance with|with respect to|in regard to|"
               r"for the purpose of|inasmuch as)\b", re.I),
    re.compile(r"\b(one|individual|party|entity|stakeholder)\b", re.I),
]

# Passive voice heuristic: be-verb + past participle (-ed / -en / irregular)
_PASSIVE_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has been|have been|had been|"
    r"will be|would be|could be|should be|may be|might be)\s+"
    r"\w+(?:ed|en|t|wn|ne)\b",
    re.I,
)

# Nominalisation suffixes (information → nominalise)
_NOMINALISATION_RE = re.compile(
    r"\b\w+(?:tion|sion|ment|ness|ity|ance|ence|ship|hood|ism)\b",
    re.I,
)

# Default shift threshold: jumps above this are counted as shifts
_DEFAULT_SHIFT_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_segments(text: str) -> list[str]:
    """Split text into segments on blank lines (paragraphs)."""
    segments = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
    # If no paragraph breaks, split on single newlines
    if len(segments) <= 1:
        segments = [s.strip() for s in text.split("\n") if s.strip()]
    # If still just one segment, treat as single segment
    if not segments and text.strip():
        segments = [text.strip()]
    return segments


def _score_segment(segment: str) -> float:
    """Score a single segment for formality in [0, 1].

    Returns 0.5 (neutral) for empty or very short segments.
    """
    words = segment.split()
    if len(words) < 3:
        return 0.5

    n = len(words)

    # Count informal markers (normalised by word count)
    informal_hits = sum(
        len(p.findall(segment)) for p in _INFORMAL_PATTERNS
    )
    informal_rate = min(informal_hits / n, 1.0)

    # Count formal markers
    formal_hits = sum(
        len(p.findall(segment)) for p in _FORMAL_PATTERNS
    )
    formal_rate = min(formal_hits / n, 1.0)

    # Passive voice bonus (formal)
    passive_hits = len(_PASSIVE_RE.findall(segment))
    passive_rate = min(passive_hits / max(n // 10, 1), 1.0)

    # Nominalisation bonus (formal)
    nominal_hits = len(_NOMINALISATION_RE.findall(segment))
    nominal_rate = min(nominal_hits / n, 1.0)

    # First-person singular (informal signal)
    first_person = len(re.findall(r"\b(?:I|me|my|mine|myself)\b", segment))
    first_person_rate = min(first_person / n, 1.0)

    # Combine into a single score
    # Start at 0.5 (neutral), push up for formal, down for informal
    score = 0.5
    score += formal_rate * 0.3
    score += passive_rate * 0.15
    score += nominal_rate * 0.1
    score -= informal_rate * 0.3
    score -= first_person_rate * 0.1

    return max(0.0, min(1.0, score))


def _classify(
    scores: list[float],
    mean_formality: float,
    formality_std: float,
    shift_rate: float,
    max_shift: float,
    shift_threshold: float,
) -> str:
    """Classify register stability from computed metrics."""
    if not scores:
        return "consistent"

    # Trend detection: compare first half vs second half
    if len(scores) >= 4:
        half = len(scores) // 2
        first_half_mean = sum(scores[:half]) / half
        second_half_mean = sum(scores[half:]) / (len(scores) - half)
        trend = second_half_mean - first_half_mean

        if trend > 0.15 and shift_rate > 0.1:
            return "formalising"
        if trend < -0.15 and shift_rate > 0.1:
            return "informalising"

    # Very low variation → consistent
    if formality_std < 0.08 and max_shift < shift_threshold:
        return "consistent"

    # Low variation → mostly stable
    if formality_std < 0.15 and shift_rate < 0.2:
        return "mostly_stable"

    # High shift rate or high std → volatile
    if shift_rate >= 0.5 or formality_std > 0.25:
        return "volatile"

    # Moderate → mixed
    return "mixed"


def _empty_result() -> dict[str, Any]:
    """Return zeroed-out metrics for empty input."""
    return {
        "total_segments": 0,
        "mean_formality": 0.5,
        "formality_std": 0.0,
        "formality_range": 0.0,
        "shift_count": 0,
        "shift_rate": 0.0,
        "max_shift": 0.0,
        "shift_direction": "stable",
        "register_label": "consistent",
        "segment_scores": [],
    }


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute_register_shift(
    texts: list[str],
    shift_threshold: float = _DEFAULT_SHIFT_THRESHOLD,
) -> dict[str, Any]:
    """Analyse register shifts across a collection of texts.

    Parameters
    ----------
    texts : list[str]
        List of text strings (e.g. stroke texts).
    shift_threshold : float
        Minimum absolute difference between adjacent segment scores
        to count as a "shift" (default 0.30).

    Returns
    -------
    dict
        Metrics dictionary with all fields documented above.
    """
    if not texts:
        return _empty_result()

    # Flatten all texts into segments
    all_segments: list[str] = []
    for text in texts:
        all_segments.extend(_split_segments(text))

    if not all_segments:
        return _empty_result()

    # Score each segment
    scores = [_score_segment(seg) for seg in all_segments]

    n = len(scores)
    mean_f = sum(scores) / n

    # Standard deviation
    if n > 1:
        variance = sum((s - mean_f) ** 2 for s in scores) / (n - 1)
        std_f = math.sqrt(variance)
    else:
        std_f = 0.0

    # Range
    f_range = max(scores) - min(scores) if n > 1 else 0.0

    # Adjacent-segment shifts
    shifts: list[float] = []
    if n > 1:
        for i in range(1, n):
            shifts.append(abs(scores[i] - scores[i - 1]))

    shift_jumps = [s for s in shifts if s > shift_threshold]
    shift_count = len(shift_jumps)
    shift_rate = shift_count / len(shifts) if shifts else 0.0
    max_shift = max(shifts) if shifts else 0.0

    # Direction: net trend across all segments
    if n >= 4:
        half = n // 2
        first_mean = sum(scores[:half]) / half
        second_mean = sum(scores[half:]) / (n - half)
        net = second_mean - first_mean
        if net > 0.10:
            direction = "formalising"
        elif net < -0.10:
            direction = "informalising"
        else:
            direction = "stable"
    else:
        direction = "stable"

    label = _classify(scores, mean_f, std_f, shift_rate, max_shift, shift_threshold)

    return {
        "total_segments": n,
        "mean_formality": round(mean_f, 4),
        "formality_std": round(std_f, 4),
        "formality_range": round(f_range, 4),
        "shift_count": shift_count,
        "shift_rate": round(shift_rate, 4),
        "max_shift": round(max_shift, 4),
        "shift_direction": direction,
        "register_label": label,
        "segment_scores": [round(s, 4) for s in scores],
    }


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------

def _load_strokes(n: int = 200) -> list[str]:
    """Load the last *n* stroke texts from the JSONL file."""
    if not STROKES_FILE.exists():
        return []
    lines = STROKES_FILE.read_text(encoding="utf-8").strip().splitlines()
    texts: list[str] = []
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
            t = obj.get("text", "")
            if t:
                texts.append(t)
        except json.JSONDecodeError:
            continue
    return texts


def register_shift_report(n: int = 200) -> dict[str, Any]:
    """Compute register shift metrics from the on-disk strokes file."""
    texts = _load_strokes(n)
    metrics = compute_register_shift(texts)
    metrics["strokes_analysed"] = len(texts)
    return metrics


def register_shift_summary(metrics: dict[str, Any]) -> str:
    """Human-readable summary of register shift analysis."""
    lines = [
        f"Segments analysed  : {metrics['total_segments']}",
        f"Mean formality     : {metrics['mean_formality']:.3f}",
        f"Formality std      : {metrics['formality_std']:.3f}",
        f"Formality range    : {metrics['formality_range']:.3f}",
        f"Shift count        : {metrics['shift_count']}",
        f"Shift rate         : {metrics['shift_rate']:.2%}",
        f"Max single shift   : {metrics['max_shift']:.3f}",
        f"Shift direction    : {metrics['shift_direction']}",
        f"Register label     : {metrics['register_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Analyse register/formality shifts in recent strokes.",
    )
    ap.add_argument(
        "-n", "--strokes", type=int, default=200,
        help="number of recent strokes to analyse (default: 200)",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="output full JSON report",
    )
    args = ap.parse_args(argv)

    metrics = register_shift_report(args.strokes)

    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(register_shift_summary(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(main())
