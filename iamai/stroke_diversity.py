"""Stroke diversity analyzer — is the writer stuck in a loop?

The writer produces hundreds of strokes per day.  Most are ``thought``
kind, but within that stream there should be *variety*: different
templates, different topics, different measured values.  When the same
text pattern repeats verbatim, the writer has fallen into a
deterministic loop — generating content that adds nothing.

``analyze_diversity()`` reads the stroke log and returns a structured
``DiversityReport`` covering:

- **total_strokes**: how many strokes were analyzed
- **kind_counts**: ``dict[str, int]`` of stroke kinds
- **kind_entropy**: Shannon entropy (bits) of the kind distribution
- **unique_ratio**: unique texts / total texts (within the window)
- **repetition_loop**: ``True`` if any text appears ≥3 times consecutively
- **loop_text**: the repeating text (or ``None``)
- **diversity_score**: composite score 0.0–1.0
- **verdict**: ``healthy``, ``low_diversity``, or ``stuck_loop``

Verdict logic:

==============  =================================================
verdict         condition
==============  =================================================
``healthy``     score ≥ 0.5 and no repetition loop
``low_diversity``  score < 0.5 and no repetition loop
``stuck_loop``  repetition loop detected (regardless of score)
==============  =================================================

The diversity score combines:
  - kind entropy normalized to log2(kind_count) → 40% weight
  - unique ratio → 40% weight
  - absence of consecutive repeats → 20% weight

Usage::

    from iamai.stroke_diversity import analyze_diversity, format_report

    report = analyze_diversity()
    print(format_report(report))
    # → "healthy: 5998 strokes, 7 kinds, entropy 1.27 bits, 94% unique"

    if report["verdict"] == "stuck_loop":
        # writer needs intervention
        ...
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKE_LOG = REPO / "data" / "strokes.jsonl"
DEFAULT_WINDOW = 200  # analyze last N strokes


@dataclass(frozen=True)
class DiversityReport:
    """Structured result of a stroke diversity analysis."""

    total_strokes: int = 0
    kind_counts: Dict[str, int] = field(default_factory=dict)
    kind_entropy: float = 0.0
    unique_ratio: float = 0.0
    repetition_loop: bool = False
    loop_text: Optional[str] = None
    diversity_score: float = 0.0
    verdict: str = "healthy"


def _shannon_entropy(counts: Dict[str, int]) -> float:
    """Compute Shannon entropy in bits from a frequency map."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def _detect_repetition_loop(texts: List[str], min_repeats: int = 3) -> Optional[str]:
    """Check if any text appears ≥min_repeats times consecutively.

    Returns the repeating text, or None.
    """
    if len(texts) < min_repeats:
        return None

    run_start = 0
    for i in range(1, len(texts)):
        if texts[i] != texts[run_start]:
            run_start = i
        elif i - run_start + 1 >= min_repeats:
            return texts[run_start]
    return None


def _normalize_text(text: str) -> str:
    """Strip variable parts (numbers, timestamps) to detect structural repeats."""
    # Replace numbers with #
    normalized = re.sub(r'\d+', '#', text)
    # Collapse whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def _compute_diversity_score(
    kind_entropy: float,
    num_kinds: int,
    unique_ratio: float,
    has_repetition: bool,
) -> float:
    """Compute composite diversity score 0.0–1.0."""
    if num_kinds <= 1:
        entropy_score = 0.0
    else:
        max_entropy = math.log2(num_kinds)
        entropy_score = min(kind_entropy / max_entropy, 1.0) if max_entropy > 0 else 0.0

    repetition_score = 0.0 if has_repetition else 1.0

    score = (
        0.4 * entropy_score
        + 0.4 * unique_ratio
        + 0.2 * repetition_score
    )
    return round(score, 4)


def _verdict(score: float, has_repetition: bool) -> str:
    """Determine verdict from score and repetition status."""
    if has_repetition:
        return "stuck_loop"
    if score >= 0.5:
        return "healthy"
    return "low_diversity"


def analyze_diversity(
    stroke_log: Optional[Path] = None,
    window: int = DEFAULT_WINDOW,
) -> DiversityReport:
    """Analyze stroke diversity from the last `window` strokes.

    Parameters
    ----------
    stroke_log : Path, optional
        Path to the JSONL stroke log.  Defaults to ``data/strokes.jsonl``.
    window : int
        Number of recent strokes to analyze.

    Returns
    -------
    DiversityReport
    """
    log_path = stroke_log or DEFAULT_STROKE_LOG

    if not log_path.exists():
        return DiversityReport(verdict="healthy")

    # Read last `window` strokes
    strokes: List[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))

    if not strokes:
        return DiversityReport(verdict="healthy")

    window_strokes = strokes[-window:]
    total = len(window_strokes)

    # Kind distribution
    kind_counts: Dict[str, int] = {}
    for s in window_strokes:
        k = s.get("kind", "unknown")
        kind_counts[k] = kind_counts.get(k, 0) + 1

    kind_entropy = _shannon_entropy(kind_counts)

    # Text uniqueness (normalized)
    texts = [_normalize_text(s.get("text", "")) for s in window_strokes]
    unique_texts = set(texts)
    unique_ratio = len(unique_texts) / total if total > 0 else 0.0

    # Repetition detection
    loop_text = _detect_repetition_loop(texts, min_repeats=3)
    has_repetition = loop_text is not None

    # Composite score
    score = _compute_diversity_score(
        kind_entropy, len(kind_counts), unique_ratio, has_repetition
    )

    verdict = _verdict(score, has_repetition)

    return DiversityReport(
        total_strokes=total,
        kind_counts=kind_counts,
        kind_entropy=round(kind_entropy, 4),
        unique_ratio=round(unique_ratio, 4),
        repetition_loop=has_repetition,
        loop_text=loop_text,
        diversity_score=score,
        verdict=verdict,
    )


def format_report(report: DiversityReport) -> str:
    """Format a DiversityReport as a human-readable string."""
    kinds_str = ", ".join(
        f"{k} x{v}" for k, v in sorted(report.kind_counts.items(), key=lambda x: -x[1])
    )
    parts = [
        f"{report.verdict}:",
        f"{report.total_strokes} strokes",
        f"{len(report.kind_counts)} kinds ({kinds_str})",
        f"entropy {report.kind_entropy:.2f} bits",
        f"{report.unique_ratio:.0%} unique",
        f"score {report.diversity_score:.2f}",
    ]
    if report.repetition_loop and report.loop_text:
        preview = report.loop_text[:60] + ("…" if len(report.loop_text) > 60 else "")
        parts.append(f"LOOP: \"{preview}\"")
    return ", ".join(parts)
