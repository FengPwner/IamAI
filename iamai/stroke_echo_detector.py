"""Stroke echo detector — find near-duplicate strokes in the log.

``stroke_novelty`` flags strokes that are *exactly* identical to a
previous one.  ``template_loop_detector`` catches strokes that share
a sentence template with number/quote substitutions.  Neither catches
the middle ground: strokes whose text is *almost* the same — same
sentence with one word changed, same observation rephrased slightly,
or the same garden pattern with a different round number.

This module fills that gap using character-level sequence matching
(``difflib.SequenceMatcher``) to compute a similarity ratio between
each stroke and its recent neighbours.

Data model
----------

An **echo event** is recorded when two strokes within a sliding window
have a similarity ratio at or above the threshold:

================  =====================================================
field             meaning
================  =====================================================
``index_a``       index of the earlier stroke in the window
``index_b``       index of the later stroke
``ratio``         similarity ratio (0.0–1.0, 1.0 = identical)
``text_a``        truncated preview of the earlier stroke
``text_b``        truncated preview of the later stroke
================  =====================================================

The ``detect_echoes`` function scans a list of stroke texts with a
sliding window and returns all echo events found.  ``echo_report``
provides summary statistics: total echoes, echo density (echoes per
stroke), and the worst (highest-ratio) echo.

Thresholds
----------

- **ECHO_THRESHOLD** = 0.85 — default minimum similarity to flag
- **WINDOW_SIZE** = 20 — how many recent strokes to compare against

Usage::

    from iamai.stroke_echo_detector import detect_echoes, echo_report

    texts = [
        "tree is 839 files; 174049 lines is a lot for a toy",
        "tree is 839 files; 174084 lines is a lot for a toy",
        "536 python files, 3305 logged thoughts",
        "536 python files, 3308 logged thoughts",
    ]
    events = detect_echoes(texts)
    report = echo_report(texts)
    print(report.echo_count)     # 2
    print(report.echo_density)   # 0.5
    print(report.verdict)        # "echoing"
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ECHO_THRESHOLD: float = 0.85
WINDOW_SIZE: int = 20
PREVIEW_LEN: int = 80


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EchoEvent:
    """One detected near-duplicate pair."""

    index_a: int
    index_b: int
    ratio: float
    text_a: str
    text_b: str

    @property
    def severity(self) -> str:
        """Human-readable severity based on ratio."""
        if self.ratio >= 0.95:
            return "near-identical"
        if self.ratio >= 0.90:
            return "very-similar"
        return "similar"


@dataclass
class EchoReport:
    """Summary of echo analysis over a stroke sequence."""

    total_strokes: int = 0
    echo_count: int = 0
    events: List[EchoEvent] = field(default_factory=list)
    threshold: float = ECHO_THRESHOLD
    window_size: int = WINDOW_SIZE

    @property
    def echo_density(self) -> float:
        """Echoes per stroke (0.0 = no echoes, 1.0 = every stroke echoed)."""
        if self.total_strokes == 0:
            return 0.0
        return self.echo_count / self.total_strokes

    @property
    def worst_ratio(self) -> float:
        """Highest similarity ratio among detected echoes."""
        if not self.events:
            return 0.0
        return max(e.ratio for e in self.events)

    @property
    def verdict(self) -> str:
        """Overall verdict: 'clean', 'mild', or 'echoing'."""
        if self.echo_count == 0:
            return "clean"
        if self.echo_density < 0.10:
            return "mild"
        return "echoing"

    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.echo_count == 0:
            return f"no echoes in {self.total_strokes} strokes (threshold {self.threshold})"
        return (
            f"{self.echo_count} echo{'es' if self.echo_count != 1 else ''} "
            f"in {self.total_strokes} strokes "
            f"(density {self.echo_density:.2f}, worst {self.worst_ratio:.2f}, "
            f"verdict: {self.verdict})"
        )


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------


def _preview(text: str, max_len: int = PREVIEW_LEN) -> str:
    """Truncate text for display, appending ellipsis if needed."""
    text = " ".join(text.split())  # normalize whitespace
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def text_similarity(a: str, b: str) -> float:
    """Compute character-level similarity ratio between two texts.

    Uses ``difflib.SequenceMatcher`` with ``autojunk=False`` for
    consistent results on repetitive content.

    Returns a float in [0.0, 1.0].
    """
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def detect_echoes(
    texts: Sequence[str],
    threshold: float = ECHO_THRESHOLD,
    window: int = WINDOW_SIZE,
) -> List[EchoEvent]:
    """Scan a sequence of stroke texts for near-duplicate pairs.

    Parameters
    ----------
    texts : sequence of str
        Stroke texts in chronological order.
    threshold : float
        Minimum similarity ratio to flag as an echo (default 0.85).
    window : int
        How many recent strokes to compare each new stroke against.

    Returns
    -------
    List of EchoEvent, sorted by index_b ascending.
    """
    if not texts or len(texts) < 2:
        return []

    events: List[EchoEvent] = []

    for i in range(1, len(texts)):
        # Compare stroke i against the previous `window` strokes
        start = max(0, i - window)
        for j in range(start, i):
            ratio = text_similarity(texts[j], texts[i])
            if ratio >= threshold:
                events.append(EchoEvent(
                    index_a=j,
                    index_b=i,
                    ratio=round(ratio, 4),
                    text_a=_preview(texts[j]),
                    text_b=_preview(texts[i]),
                ))

    return events


def echo_report(
    texts: Sequence[str],
    threshold: float = ECHO_THRESHOLD,
    window: int = WINDOW_SIZE,
) -> EchoReport:
    """Generate a full echo analysis report.

    Parameters
    ----------
    texts : sequence of str
        Stroke texts in chronological order.
    threshold : float
        Minimum similarity ratio to flag.
    window : int
        Comparison window size.
    """
    events = detect_echoes(texts, threshold, window)
    return EchoReport(
        total_strokes=len(texts),
        echo_count=len(events),
        events=events,
        threshold=threshold,
        window_size=window,
    )
