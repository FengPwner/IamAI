"""Stroke diversity — measure how evenly stroke kinds are distributed.

A healthy repo has strokes spread across multiple categories
(thought, note, snippet, devlog, garden, metrics, etc.).  When the
writer fixates on one kind, content quality degrades even if
throughput stays high.

This module answers one question: *how imbalanced is the recent
stroke distribution?*

===========  ============================================================
verdict      meaning
===========  ============================================================
balanced     kinds are roughly equally represented
mild-skew    one or two kinds slightly over-represented
noticeable   clear bias — worth investigating why
starved      nearly all strokes are one kind — content is collapsing
===========  ============================================================

Design goals:

1. **Pure Python** — no git, no external deps.
2. **Windowed** — only looks at the most recent N strokes (default 100).
3. **Shannon entropy** — provides an information-theoretic complement
   to the simple imbalance score.
4. **Forgiving** — malformed JSONL lines are skipped, not raised.

Usage::

    from tools import stroke_diversity as sd

    strokes = sd.load_recent_strokes("data/strokes.jsonl", window=100)
    score = sd.compute_imbalance(strokes)
    label = sd.classify_imbalance(score)
    entropy = sd.compute_entropy(strokes)
    print(f"{label} (score={score:.2f}, H={entropy:.2f} bits)")
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# The canonical set of stroke kinds the writer should be cycling through.
DEFAULT_KINDS = ("devlog", "garden", "metrics", "note", "snippet", "thought")

# Threshold boundaries for classify_imbalance.
_THRESHOLDS = [
    (0.10, "balanced"),
    (0.25, "mild-skew"),
    (0.40, "noticeable"),
]
_FALLBACK_LABEL = "starved"

# Module-level default path — monkeypatch-friendly for tests.
STROKES_PATH = Path("data/strokes.jsonl")


def compute_imbalance(strokes: list[dict]) -> float:
    """Return an imbalance score in [0, 1] for a list of strokes.

    0 = perfectly balanced across all DEFAULT_KINDS.
    1 = every stroke belongs to a single kind.

    The score is the sum of absolute deviations from the expected
    uniform count, normalised so that the worst case (all strokes
    in one kind) equals 1.

    Empty input returns 0.0 by convention.
    """
    if not strokes:
        return 0.0

    k = len(DEFAULT_KINDS)
    n = len(strokes)

    counts: dict[str, int] = {kind: 0 for kind in DEFAULT_KINDS}
    for s in strokes:
        kind = s.get("kind", "")
        if kind in counts:
            counts[kind] += 1

    expected = n / k
    deviation = sum(abs(c - expected) for c in counts.values())

    # Maximum deviation occurs when all strokes fall in one kind:
    # that kind deviates by n - n/k, the other k-1 kinds each by n/k.
    max_deviation = (n - expected) + (k - 1) * expected  # = n*(k-1)*2/k  simplified
    if max_deviation == 0:
        return 0.0

    return deviation / max_deviation


def compute_entropy(strokes: list[dict]) -> float:
    """Shannon entropy of the stroke kind distribution (in bits).

    Only counts kinds present in DEFAULT_KINDS.  Zero-entropy kinds
    (not present in the data) are excluded from the sum, so a
    two-kind 50/50 split gives exactly 1.0 bit.

    Empty input returns 0.0.
    """
    if not strokes:
        return 0.0

    n = len(strokes)
    counts: dict[str, int] = {kind: 0 for kind in DEFAULT_KINDS}
    for s in strokes:
        kind = s.get("kind", "")
        if kind in counts:
            counts[kind] += 1

    # Count only the strokes that matched a known kind
    matched = sum(counts.values())
    if matched == 0:
        return 0.0

    entropy = 0.0
    for c in counts.values():
        if c > 0:
            p = c / matched
            entropy -= p * math.log2(p)

    return entropy


def classify_imbalance(score: float) -> str:
    """Map an imbalance score to a human-readable label.

    Parameters
    ----------
    score:
        Value in [0, 1] from ``compute_imbalance``.

    Returns
    -------
    One of ``"balanced"``, ``"mild-skew"``, ``"noticeable"``,
    or ``"starved"``.
    """
    for threshold, label in _THRESHOLDS:
        if score < threshold:
            return label
    return _FALLBACK_LABEL


def load_recent_strokes(path: Path | str, window: int = 100) -> list[dict]:
    """Load the last *window* strokes from a JSONL file.

    Reads the entire file and returns the tail.  For very large files
    a seek-from-end strategy would be better, but strokes.jsonl is
    typically under 50k lines — cheap enough to read linearly.

    Malformed lines are silently skipped.

    Parameters
    ----------
    path:
        Path to a JSONL file of stroke records.
    window:
        Maximum number of recent strokes to return.

    Returns
    -------
    List of parsed stroke dicts (most recent last).
    """
    path = Path(path)
    if not path.exists():
        return []

    strokes: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return strokes[-window:]
