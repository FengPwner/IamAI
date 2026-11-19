"""stroke_metric_rotation — analyse how metric measurements cycle in strokes.

The auto-writer appends one of five metric measurements to each stroke's
text (after `` -- measured now:``): commit count, tree size, line count,
stroke count, or python-file count.  In a healthy pipeline these five
rotate evenly, each appearing roughly 20% of the time.  When one metric
dominates or the rotation breaks, it signals that the writer is stuck
in a narrow reporting loop and has lost situational awareness.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             total strokes analysed
classified_strokes        strokes with a recognised metric type
unclassified_strokes      strokes without a metric (pure aphorisms)
metric_counts             dict mapping metric type → count
metric_fractions          dict mapping metric type → fraction (0–1)
richness                  number of distinct metric types observed
entropy_ratio             H / H_max; 1.0 = perfectly uniform rotation
max_streak                longest run of consecutive identical metrics
max_streak_type           which metric type held the longest streak
avg_streak                mean streak length across all streaks
regularity_score          composite 0–1 score (higher = more uniform)
dominant_metric           metric type with the largest share
dominant_fraction         share of the dominant metric type
starved_metrics           metric types below half of uniform share
rotation_breaks           count of same-metric consecutive pairs
========================  =============================================

Metric types
------------

===============  ===================================================
type             pattern
===============  ===================================================
commit_count     ``commit N: the count of times this repo was pushed``
tree_is          ``tree is N files; M lines is a lot for a toy``
lines_across    ``N lines across M tracked files, K commits deep``
strokes_written ``N strokes written so far into M files``
python_files    ``N python files, M logged thoughts``
===============  ===================================================

Interpretation
--------------

* **regularity ≥ 0.85** — healthy, even rotation across all metrics
* **regularity 0.60–0.85** — moderate imbalance, some metrics under-used
* **regularity < 0.60** — significant skew; one or more metrics starved

Edge cases
----------

* Strokes without the ``-- measured now:`` separator are classified as
  ``unclassified`` and excluded from rotation analysis.
* If fewer than two metric types are observed, entropy_ratio is 0.0.
* An empty corpus returns a zeroed report.

Usage
-----
    from iamai.stroke_metric_rotation import MetricRotation

    mr = MetricRotation.from_jsonl("data/strokes.jsonl")
    report = mr.report()
    print(report.regularity_score, report.dominant_metric)
    print(report.starved_metrics)
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ── metric classifiers ────────────────────────────────────────────────

_METRIC_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("commit_count",    re.compile(r"^commit\s+\d+\s*:", re.I)),
    ("tree_is",         re.compile(r"^tree\s+is\s+\d+\s+files", re.I)),
    ("lines_across",    re.compile(r"^\d+\s+lines\s+across", re.I)),
    ("strokes_written", re.compile(r"^\d+\s+strokes\s+written", re.I)),
    ("python_files",    re.compile(r"^\d+\s+python\s+files", re.I)),
]

_SEPARATOR = " -- measured now: "

ALL_METRIC_TYPES = [p[0] for p in _METRIC_PATTERNS]


def classify_metric(text: str) -> Optional[str]:
    """Return the metric type embedded in *text*, or ``None``.

    The function looks for the ``-- measured now:`` separator first.
    If absent, the stroke is treated as a pure aphorism (no metric).
    """
    if _SEPARATOR not in text:
        return None
    metric_part = text.split(_SEPARATOR, 1)[1].strip()
    for name, pattern in _METRIC_PATTERNS:
        if pattern.search(metric_part):
            return name
    return None


def extract_aphorism(text: str) -> str:
    """Return the aphorism part of a stroke (before the metric)."""
    if _SEPARATOR in text:
        return text.split(_SEPARATOR, 1)[0].strip()
    return text.strip()


def extract_metric_value(text: str) -> str:
    """Return the metric measurement part (after the separator)."""
    if _SEPARATOR in text:
        return text.split(_SEPARATOR, 1)[1].strip()
    return ""


# ── report ────────────────────────────────────────────────────────────

@dataclass
class RotationReport:
    """Snapshot of metric rotation at a point in time."""

    total_strokes: int
    classified_strokes: int
    unclassified_strokes: int
    metric_counts: Dict[str, int]
    metric_fractions: Dict[str, float]
    richness: int
    entropy_ratio: float
    max_streak: int
    max_streak_type: str
    avg_streak: float
    regularity_score: float
    dominant_metric: str
    dominant_fraction: float
    starved_metrics: List[str] = field(default_factory=list)
    rotation_breaks: int = 0

    def summary(self) -> str:
        if self.classified_strokes == 0:
            return "No classified metrics found; rotation undefined."
        level = (
            "healthy" if self.regularity_score >= 0.85
            else "moderate" if self.regularity_score >= 0.60
            else "skewed"
        )
        return (
            f"Rotation {level}: {self.richness} metric types, "
            f"regularity={self.regularity_score:.2f}, "
            f"dominant={self.dominant_metric} ({self.dominant_fraction:.1%}), "
            f"longest streak={self.max_streak} ({self.max_streak_type}), "
            f"breaks={self.rotation_breaks}."
        )

    def to_dict(self) -> dict:
        return {
            "total_strokes": self.total_strokes,
            "classified": self.classified_strokes,
            "unclassified": self.unclassified_strokes,
            "richness": self.richness,
            "entropy_ratio": round(self.entropy_ratio, 4),
            "regularity": round(self.regularity_score, 4),
            "max_streak": self.max_streak,
            "max_streak_type": self.max_streak_type,
            "avg_streak": round(self.avg_streak, 2),
            "dominant": self.dominant_metric,
            "dominant_fraction": round(self.dominant_fraction, 4),
            "starved": self.starved_metrics,
            "rotation_breaks": self.rotation_breaks,
        }


# ── analyser ──────────────────────────────────────────────────────────

class MetricRotation:
    """Analyse metric-type rotation in a stroke corpus.

    Parameters
    ----------
    metric_sequence : Sequence[str]
        Ordered list of metric type labels (one per stroke).
        Strokes without a recognised metric should use ``""`` or ``None``.
    """

    def __init__(self, metric_sequence: Sequence[Optional[str]]) -> None:
        self._seq = [m if m else "" for m in metric_sequence]

    # ── factories ─────────────────────────────────────────────────────

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "MetricRotation":
        """Load metric sequence from a JSONL strokes file."""
        seq: List[Optional[str]] = []
        p = Path(path)
        if not p.exists():
            return cls(seq)
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    seq.append(None)
                    continue
                text = rec.get("text", "")
                seq.append(classify_metric(text))
        return cls(seq)

    @classmethod
    def from_strokes(cls, strokes: Sequence[dict]) -> "MetricRotation":
        """Build from a list of stroke dicts."""
        return cls([classify_metric(s.get("text", "")) for s in strokes])

    # ── core ──────────────────────────────────────────────────────────

    def report(self) -> RotationReport:
        """Compute the full rotation report."""
        total = len(self._seq)
        classified = [m for m in self._seq if m]
        unclassified_count = total - len(classified)

        if not classified:
            return RotationReport(
                total_strokes=total,
                classified_strokes=0,
                unclassified_strokes=unclassified_count,
                metric_counts={},
                metric_fractions={},
                richness=0,
                entropy_ratio=0.0,
                max_streak=0,
                max_streak_type="",
                avg_streak=0.0,
                regularity_score=0.0,
                dominant_metric="",
                dominant_fraction=0.0,
            )

        counts = Counter(classified)
        n_class = len(classified)
        fractions = {m: c / n_class for m, c in counts.items()}
        richness = len(counts)

        # Shannon entropy
        h = -sum(p * math.log2(p) for p in fractions.values() if p > 0)
        h_max = math.log2(richness) if richness > 1 else 0.0
        entropy_ratio = h / h_max if h_max > 0 else 0.0

        # Streaks
        streaks = self._compute_streaks()
        max_streak_len = 0
        max_streak_type = ""
        for stype, slen in streaks:
            if slen > max_streak_len:
                max_streak_len = slen
                max_streak_type = stype
        avg_streak = (
            sum(slen for _, slen in streaks) / len(streaks)
            if streaks else 0.0
        )

        # Rotation breaks: consecutive same-type pairs
        breaks = sum(
            1 for i in range(1, len(classified))
            if classified[i] == classified[i - 1]
        )

        # Dominant metric
        dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
        dominant_frac = fractions[dominant]

        # Starved metrics
        uniform_share = 1.0 / richness if richness > 0 else 0.0
        threshold = uniform_share / 2.0
        starved = sorted(m for m, f in fractions.items() if f < threshold)

        # Regularity score: blend of entropy_ratio, streak penalty,
        # and starvation penalty
        streak_penalty = min(1.0, max_streak_len / 20.0) if richness > 1 else 0.0
        starvation_penalty = len(starved) / richness if richness > 0 else 0.0
        regularity = max(
            0.0,
            min(1.0, entropy_ratio * (1.0 - 0.3 * streak_penalty)
                 * (1.0 - 0.2 * starvation_penalty)),
        )

        return RotationReport(
            total_strokes=total,
            classified_strokes=n_class,
            unclassified_strokes=unclassified_count,
            metric_counts=dict(counts),
            metric_fractions=fractions,
            richness=richness,
            entropy_ratio=entropy_ratio,
            max_streak=max_streak_len,
            max_streak_type=max_streak_type,
            avg_streak=avg_streak,
            regularity_score=regularity,
            dominant_metric=dominant,
            dominant_fraction=dominant_frac,
            starved_metrics=starved,
            rotation_breaks=breaks,
        )

    # ── internal ──────────────────────────────────────────────────────

    def _compute_streaks(self) -> List[Tuple[str, int]]:
        """Return list of (metric_type, streak_length) for classified strokes."""
        classified = [m for m in self._seq if m]
        if not classified:
            return []
        streaks: List[Tuple[str, int]] = []
        current_type = classified[0]
        current_len = 1
        for m in classified[1:]:
            if m == current_type:
                current_len += 1
            else:
                streaks.append((current_type, current_len))
                current_type = m
                current_len = 1
        streaks.append((current_type, current_len))
        return streaks

    def recent_window(self, window_size: int = 100) -> "MetricRotation":
        """Return a MetricRotation for the last *window_size* strokes."""
        return MetricRotation(self._seq[-window_size:])

    def classify_distribution(self) -> Dict[str, str]:
        """Classify each metric type as 'healthy', 'under', or 'over'.

        Thresholds relative to the uniform share (1/richness):
        * healthy: within ±25% of uniform share
        * under: below 75% of uniform share
        * over: above 125% of uniform share
        """
        classified = [m for m in self._seq if m]
        if not classified:
            return {}
        counts = Counter(classified)
        richness = len(counts)
        uniform = 1.0 / richness if richness > 0 else 0.0
        result: Dict[str, str] = {}
        for m, c in counts.items():
            frac = c / len(classified)
            if frac < uniform * 0.75:
                result[m] = "under"
            elif frac > uniform * 1.25:
                result[m] = "over"
            else:
                result[m] = "healthy"
        return result
