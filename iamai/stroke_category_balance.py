"""stroke_category_balance — measure how evenly strokes are distributed.

The writer produces strokes across categories (thought, note, devlog,
garden, metrics, snippet).  Over time, one category can dominate —
``thought`` alone accounts for 99%+ of strokes in the current corpus.
This module quantifies that imbalance and suggests which categories
need attention.

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_strokes             total number of strokes analysed
category_counts           dict mapping category → count
category_fractions        dict mapping category → fraction (0–1)
richness                  number of distinct categories observed
shannon_entropy           H = −Σ p·log₂(p) in bits
max_entropy               log₂(richness); upper bound for given richness
entropy_ratio             H / max_entropy; 1.0 = perfectly uniform
gini_coefficient          0 = perfect equality, 1 = total concentration
herfindahl_index          Σ p²; lower = more diverse (uniform = 1/k)
dominant_category         category with the largest share
dominant_fraction         share of the dominant category
starved_categories        categories below the starvation threshold
========================  =============================================

Starvation threshold
--------------------

A category is *starved* when its fraction falls below
``1 / (2 × richness)`` — half of what a perfectly uniform distribution
would give it.  This is a soft heuristic, not a hard rule.

Suggestion
----------

``suggest_next_category()`` returns the starved category with the
*lowest* fraction, or ``None`` if all categories are adequately fed.

Usage
-----
    from iamai.stroke_category_balance import StrokeCategoryBalance

    bal = StrokeCategoryBalance.from_jsonl("data/strokes.jsonl")
    report = bal.report()
    print(report.entropy_ratio, report.dominant_category)
    print(report.suggest_next_category())
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence


@dataclass
class BalanceReport:
    """Snapshot of stroke-category balance at a point in time."""

    total_strokes: int
    category_counts: Dict[str, int]
    category_fractions: Dict[str, float]
    richness: int
    shannon_entropy: float
    max_entropy: float
    entropy_ratio: float
    gini_coefficient: float
    herfindahl_index: float
    dominant_category: str
    dominant_fraction: float
    starved_categories: List[str] = field(default_factory=list)

    def suggest_next_category(self) -> Optional[str]:
        """Return the most under-represented starved category, or None."""
        if not self.starved_categories:
            return None
        return min(self.starved_categories,
                   key=lambda c: self.category_fractions.get(c, 0.0))

    def to_dict(self) -> dict:
        return {
            "total_strokes": self.total_strokes,
            "richness": self.richness,
            "entropy_ratio": round(self.entropy_ratio, 4),
            "gini": round(self.gini_coefficient, 4),
            "herfindahl": round(self.herfindahl_index, 4),
            "dominant": self.dominant_category,
            "dominant_fraction": round(self.dominant_fraction, 4),
            "starved": self.starved_categories,
            "suggestion": self.suggest_next_category(),
        }


class StrokeCategoryBalance:
    """Analyse stroke-category distribution from a strokes log."""

    def __init__(self, categories: Sequence[str]) -> None:
        self._categories = list(categories)

    # ------------------------------------------------------------------
    # constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "StrokeCategoryBalance":
        """Load categories from a JSONL strokes file."""
        cats: list[str] = []
        p = Path(path)
        if not p.exists():
            return cls(cats)
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = rec.get("kind", "")
                if kind:
                    cats.append(kind)
        return cls(cats)

    @classmethod
    def from_counts(cls, counts: Dict[str, int]) -> "StrokeCategoryBalance":
        """Build from a pre-computed category → count mapping."""
        cats: list[str] = []
        for cat, n in counts.items():
            cats.extend([cat] * max(0, int(n)))
        return cls(cats)

    # ------------------------------------------------------------------
    # analysis
    # ------------------------------------------------------------------

    def report(self) -> BalanceReport:
        """Compute the full balance report."""
        counts = Counter(self._categories)
        total = sum(counts.values())

        if total == 0:
            return BalanceReport(
                total_strokes=0,
                category_counts={},
                category_fractions={},
                richness=0,
                shannon_entropy=0.0,
                max_entropy=0.0,
                entropy_ratio=0.0,
                gini_coefficient=0.0,
                herfindahl_index=0.0,
                dominant_category="",
                dominant_fraction=0.0,
            )

        richness = len(counts)
        fractions = {c: n / total for c, n in counts.items()}

        # Shannon entropy
        h = -sum(p * math.log2(p) for p in fractions.values() if p > 0)
        h_max = math.log2(richness) if richness > 1 else 0.0
        entropy_ratio = h / h_max if h_max > 0 else 0.0

        # Gini coefficient
        sorted_vals = sorted(counts.values())
        n = len(sorted_vals)
        cum = 0.0
        weighted_sum = 0.0
        for i, v in enumerate(sorted_vals):
            cum += v
            weighted_sum += (2 * (i + 1) - n - 1) * v
        gini = weighted_sum / (n * cum) if cum > 0 and n > 1 else 0.0

        # Herfindahl index
        hhi = sum(p * p for p in fractions.values())

        # Dominant category
        dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
        dominant_frac = fractions[dominant]

        # Starved categories (below half of uniform share)
        uniform_share = 1.0 / richness if richness > 0 else 0.0
        threshold = uniform_share / 2.0
        starved = sorted(c for c, f in fractions.items() if f < threshold)

        return BalanceReport(
            total_strokes=total,
            category_counts=dict(counts),
            category_fractions=fractions,
            richness=richness,
            shannon_entropy=h,
            max_entropy=h_max,
            entropy_ratio=entropy_ratio,
            gini_coefficient=gini,
            herfindahl_index=hhi,
            dominant_category=dominant,
            dominant_fraction=dominant_frac,
            starved_categories=starved,
        )
