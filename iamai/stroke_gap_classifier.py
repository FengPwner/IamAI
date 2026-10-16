"""stroke_gap_classifier — classify inter-stroke gaps by severity.

The writer emits strokes at a configured cadence (default 15 s).
Real-world gaps are noisy: a 17 s gap is fine, a 90 s gap is a
micro-stall worth logging, and a 2700 s gap almost certainly means
the sandbox reclaimed the process.

This module provides a pure-data classifier that maps a gap duration
(in seconds) to a severity band.  It also keeps a running histogram
so the caretaker can ask "how many micro-stalls have we seen today?"

Design decisions:

1. **Stateless classify(gap_s)** — the function is a pure function;
   safe to call from monitoring scripts that just need a label.
2. **Stateful StrokeGapHistogram** — accumulates gap observations and
   exposes counts per band, total count, and a ``summarize()`` method
   that returns a dict suitable for JSON serialization.
3. **Configurable thresholds** — the defaults match a 15 s cadence,
   but callers can override for writers with different rhythms.

Bands (default thresholds for 15 s cadence):

==========  ==================  =====================================
Band        Range (multiples)   Meaning
==========  ==================  =====================================
normal      < 2× cadence        Healthy jitter
stretched   2× – 5× cadence     Noticeable pause, worth a glance
micro_stall 5× – 30× cadence    Something interrupted the writer
stall       30× – 120× cadence  Process likely suspended / throttled
reclaimed   > 120× cadence      Sandbox killed and restarted
==========  ==================  =====================================

Usage::

    from iamai.stroke_gap_classifier import classify, StrokeGapHistogram

    classify(20)             # "normal"
    classify(90)             # "micro_stall"
    classify(3600)           # "reclaimed"

    h = StrokeGapHistogram(cadence_s=15)
    h.record(16)
    h.record(85)
    h.record(2700)
    h.counts()               # {"normal": 1, "micro_stall": 1, "reclaimed": 1}
    h.summarize()            # {"total": 3, "bands": {...}, "worst": "reclaimed"}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Severity bands in ascending order.
BAND_ORDER = ["normal", "stretched", "micro_stall", "stall", "reclaimed"]


def classify(
    gap_s: float,
    cadence_s: float = 15.0,
) -> str:
    """Classify a single inter-stroke gap.

    Args:
        gap_s:     observed gap in seconds (must be >= 0).
        cadence_s: expected seconds between strokes (default 15).

    Returns:
        One of: normal, stretched, micro_stall, stall, reclaimed.

    Raises:
        ValueError: if gap_s < 0 or cadence_s <= 0.
    """
    if gap_s < 0:
        raise ValueError(f"gap_s must be >= 0, got {gap_s}")
    if cadence_s <= 0:
        raise ValueError(f"cadence_s must be > 0, got {cadence_s}")

    ratio = gap_s / cadence_s
    if ratio < 2:
        return "normal"
    if ratio < 5:
        return "stretched"
    if ratio < 30:
        return "micro_stall"
    if ratio < 120:
        return "stall"
    return "reclaimed"


def worst_band(gaps: List[float], cadence_s: float = 15.0) -> str:
    """Return the worst severity band across a list of gaps.

    Returns "normal" if the list is empty.
    """
    if not gaps:
        return "normal"
    worst_idx = 0
    for g in gaps:
        band = classify(g, cadence_s)
        idx = BAND_ORDER.index(band)
        if idx > worst_idx:
            worst_idx = idx
    return BAND_ORDER[worst_idx]


@dataclass
class StrokeGapHistogram:
    """Accumulate gap observations and query band distribution."""

    cadence_s: float = 15.0
    _counts: Dict[str, int] = field(default_factory=lambda: {b: 0 for b in BAND_ORDER})
    _total_gaps: float = 0.0
    _max_gap: float = 0.0
    _min_gap: Optional[float] = None

    def record(self, gap_s: float) -> str:
        """Record a gap observation.  Returns the band it fell into."""
        if gap_s < 0:
            raise ValueError(f"gap_s must be >= 0, got {gap_s}")
        band = classify(gap_s, self.cadence_s)
        self._counts[band] += 1
        self._total_gaps += gap_s
        if gap_s > self._max_gap:
            self._max_gap = gap_s
        if self._min_gap is None or gap_s < self._min_gap:
            self._min_gap = gap_s
        return band

    def counts(self) -> Dict[str, int]:
        """Return a copy of the band counts."""
        return dict(self._counts)

    @property
    def total(self) -> int:
        """Total number of recorded observations."""
        return sum(self._counts.values())

    @property
    def worst(self) -> str:
        """The worst (most severe) band that has at least one observation."""
        for band in reversed(BAND_ORDER):
            if self._counts[band] > 0:
                return band
        return "normal"

    def summarize(self) -> dict:
        """Return a JSON-serializable summary dict."""
        result: dict = {
            "total": self.total,
            "cadence_s": self.cadence_s,
            "bands": self.counts(),
            "worst": self.worst,
            "max_gap_s": self._max_gap,
            "min_gap_s": self._min_gap,
        }
        if self.total > 0:
            result["mean_gap_s"] = round(self._total_gaps / self.total, 2)
        else:
            result["mean_gap_s"] = None
        return result

    def reset(self) -> None:
        """Clear all accumulated data."""
        self._counts = {b: 0 for b in BAND_ORDER}
        self._total_gaps = 0.0
        self._max_gap = 0.0
        self._min_gap = None
