"""content_loop_detector — detect periodic patterns in writer output.

The writer sometimes falls into a *structural loop*: cycling through the
same sequence of stroke kinds, file targets, or text templates in a
fixed order.  This is different from low diversity (similar texts) — a
writer can produce diverse text while still being stuck in a structural
cycle (e.g. thought → devlog → garden → note → metrics → snippet → repeat).

This module analyses a sequence of categorical labels extracted from
strokes and answers:

1. **Is there a repeating cycle?**  (periodicity detection)
2. **How long is the cycle?**  (period length in strokes)
3. **How confident are we?**  (fraction of sequence explained by cycle)
4. **What are the repeating elements?**  (the cycle body)

Algorithm:
    For each candidate period *p* from 2 to len(seq)//2, slide a window
    across the sequence and count how many positions match
    ``seq[i] == candidate[i % p]`` for each starting offset.
    The period with the highest match ratio wins; if its ratio exceeds
    ``min_confidence``, we report a loop.

Public API
----------
- ``detect_loop(labels, min_confidence=0.6) -> LoopReport``
- ``extract_kind_labels(strokes) -> list[str]``
- ``extract_file_labels(strokes) -> list[str]``

Usage::

    from iamai.content_loop_detector import detect_loop, extract_kind_labels

    labels = extract_kind_labels(strokes)
    report = detect_loop(labels)
    print(report.has_loop)      # True
    print(report.period)        # 6
    print(report.confidence)    # 0.97
    print(report.cycle)         # ('thought', 'devlog', 'garden', 'note', 'metrics', 'snippet')
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopReport:
    """Immutable result of a loop detection analysis."""

    has_loop: bool
    period: int
    confidence: float
    cycle: tuple[str, ...]
    total_labels: int
    explained: int  # how many positions match the cycle

    @property
    def severity(self) -> str:
        """Human-readable severity grade.

        =========  ====================================================
        grade      meaning
        =========  ====================================================
        NONE       no periodic pattern detected
        MILD       weak cycle (confidence 0.6–0.8)
        MODERATE   clear cycle (confidence 0.8–0.95)
        SEVERE     near-perfect cycle (confidence >= 0.95)
        =========  ====================================================
        """
        if not self.has_loop:
            return "NONE"
        if self.confidence >= 0.95:
            return "SEVERE"
        if self.confidence >= 0.80:
            return "MODERATE"
        return "MILD"

    def summary(self) -> str:
        if not self.has_loop:
            return f"no loop detected in {self.total_labels} labels"
        body = " → ".join(self.cycle[:8])
        if len(self.cycle) > 8:
            body += f" … (+{len(self.cycle) - 8} more)"
        return (
            f"loop detected: period={self.period}, "
            f"confidence={self.confidence:.2f} ({self.severity}), "
            f"cycle=[{body}]"
        )


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _score_period(labels: Sequence[str], period: int) -> tuple[int, int, int]:
    """Return (match_count, total_positions, best_offset) for a candidate period.

    Tries all starting offsets and picks the one that maximises matches.
    """
    n = len(labels)
    if period < 2 or n < period * 2:
        return (0, n, 0)

    best_match = 0
    best_offset = 0
    for offset in range(n - period + 1):
        candidate = labels[offset: offset + period]
        match = sum(
            1 for i in range(n) if labels[i] == candidate[i % period]
        )
        if match > best_match:
            best_match = match
            best_offset = offset

    return (best_match, n, best_offset)


def detect_loop(
    labels: Sequence[str],
    min_confidence: float = 0.6,
    max_period: int | None = None,
) -> LoopReport:
    """Detect the dominant periodic pattern in *labels*.

    Parameters
    ----------
    labels:
        Sequence of categorical labels (e.g. stroke kinds, file names).
    min_confidence:
        Minimum match ratio to declare a loop.  Default 0.6 (60%).
    max_period:
        Upper bound on cycle length to test.  Defaults to len(labels) // 2.

    Returns
    -------
    LoopReport with the best detected cycle (or ``has_loop=False``).
    """
    n = len(labels)
    if n < 4:
        return LoopReport(
            has_loop=False, period=0, confidence=0.0,
            cycle=(), total_labels=n, explained=0,
        )

    upper = max_period if max_period else n // 2
    upper = min(upper, n // 2)

    best_period = 0
    best_confidence = 0.0
    best_match = 0
    best_offset = 0

    for p in range(2, upper + 1):
        match, total, offset = _score_period(labels, p)
        conf = match / total if total else 0.0
        if conf > best_confidence:
            best_confidence = conf
            best_period = p
            best_match = match
            best_offset = offset

    if best_confidence < min_confidence or best_period == 0:
        return LoopReport(
            has_loop=False, period=0, confidence=best_confidence,
            cycle=(), total_labels=n, explained=0,
        )

    cycle_body = tuple(labels[best_offset: best_offset + best_period])

    return LoopReport(
        has_loop=True,
        period=best_period,
        confidence=best_confidence,
        cycle=cycle_body,
        total_labels=n,
        explained=best_match,
    )


# ---------------------------------------------------------------------------
# Label extractors
# ---------------------------------------------------------------------------

def load_strokes(path: str | Path | None = None, tail: int = 0) -> list[dict]:
    """Load strokes from JSONL file.

    Parameters
    ----------
    path:
        Path to strokes JSONL.  Defaults to ``data/strokes.jsonl``.
    tail:
        If > 0, only load the last *tail* lines.
    """
    p = Path(path) if path else STROKES_FILE
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    if tail > 0:
        lines = lines[-tail:]
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def extract_kind_labels(strokes: Sequence[dict]) -> list[str]:
    """Extract stroke kind from each stroke dict."""
    return [s.get("kind", "unknown") for s in strokes]


def extract_file_labels(strokes: Sequence[dict]) -> list[str]:
    """Extract target file path from each stroke dict."""
    return [s.get("path", "unknown") for s in strokes]


def extract_text_prefix_labels(
    strokes: Sequence[dict], max_len: int = 40,
) -> list[str]:
    """Extract truncated text body as label (for detecting text loops)."""
    labels = []
    for s in strokes:
        text = s.get("text", "")
        # strip metric suffix
        idx = text.find(" -- measured now")
        if idx > 0:
            text = text[:idx]
        labels.append(text[:max_len].strip())
    return labels
