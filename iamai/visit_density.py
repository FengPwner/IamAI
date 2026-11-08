"""visit_density — measure how evenly caretaker visits are distributed.

A healthy caretaker visits at a steady rhythm — one visit every N minutes,
with natural variance.  An unhealthy pattern shows *clustering*: bursts
of visits close together separated by long gaps.  Clustering means the
caretaker is compensating for earlier absence, not maintaining a cadence.

Public API::

    from iamai.visit_density import VisitDensity, density_report

    vd = VisitDensity(visit_times, expected_interval=600)
    s = vd.summary()
    # {"clustering": 0.31, "evenness": 0.82, "burst_count": 2,
    #  "gap_count": 1, "grade": "steady"}

    print(density_report(visit_times, expected_interval=600))
    # "visits: evenness 0.82, 2 bursts, 1 gap — steady"

Density model
-------------

Given N visit timestamps, the module computes inter-visit intervals and
classifies each as one of:

============  ============================================================
category      condition
============  ============================================================
tight         interval < 0.5× expected  (burst — too close together)
normal        0.5× ≤ interval ≤ 2.0× expected  (healthy cadence)
loose         2.0× < interval ≤ 4.0× expected  (minor gap)
gap           interval > 4.0× expected  (significant absence)
============  ============================================================

**Clustering score** is the fraction of intervals that are ``tight``.
0.0 means no bursts; 0.5 means half the visits are in bursts.

**Evenness** is measured via the coefficient of variation (CV) of
intervals, inverted to a 0–1 scale where 1.0 is perfectly uniform.
The formula is ``1 / (1 + cv)`` which maps CV=0 → 1.0, CV=1 → 0.5,
CV→∞ → 0.0.

**Grade** combines evenness and clustering::

============  ===========  ============================================
score range   grade        meaning
============  ===========  ============================================
≥ 0.80        steady       even rhythm, few or no bursts
≥ 0.60        rhythmic     mostly regular, minor clustering
≥ 0.40        uneven       noticeable bursts or gaps
≥ 0.20        clustered    heavy burst compensation pattern
< 0.20        erratic      no discernible rhythm
============  ===========  ============================================
"""

from __future__ import annotations

from typing import Dict, List, Sequence


class VisitDensity:
    """Analyze the distribution pattern of caretaker visit timestamps."""

    # Interval classification thresholds (multiples of expected_interval)
    TIGHT_CEILING = 0.5    # below this → burst
    LOOSE_FLOOR = 2.0      # above this → loose
    GAP_FLOOR = 4.0        # above this → gap

    def __init__(
        self,
        visit_times: Sequence[float],
        expected_interval: float = 600.0,
    ):
        self.visit_times = sorted(visit_times)
        self.expected_interval = expected_interval
        self._intervals: List[float] | None = None
        self._categories: List[str] | None = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_intervals(self) -> List[float]:
        if self._intervals is None:
            self._intervals = [
                b - a
                for a, b in zip(self.visit_times[:-1], self.visit_times[1:])
            ]
        return self._intervals

    def _classify(self) -> List[str]:
        if self._categories is None:
            ei = self.expected_interval
            cats: List[str] = []
            for iv in self._compute_intervals():
                ratio = iv / ei if ei > 0 else float("inf")
                if ratio < self.TIGHT_CEILING:
                    cats.append("tight")
                elif ratio <= self.LOOSE_FLOOR:
                    cats.append("normal")
                elif ratio <= self.GAP_FLOOR:
                    cats.append("loose")
                else:
                    cats.append("gap")
            self._categories = cats
        return self._categories

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def intervals(self) -> List[float]:
        """Return inter-visit intervals (seconds)."""
        return list(self._compute_intervals())

    @property
    def categories(self) -> List[str]:
        """Return per-interval category labels."""
        return list(self._classify())

    def burst_count(self) -> int:
        """Count consecutive tight-interval runs (each run = 1 burst)."""
        cats = self._classify()
        bursts = 0
        in_burst = False
        for c in cats:
            if c == "tight" and not in_burst:
                bursts += 1
                in_burst = True
            elif c != "tight":
                in_burst = False
        return bursts

    def gap_count(self) -> int:
        """Count gap intervals."""
        return sum(1 for c in self._classify() if c == "gap")

    def clustering(self) -> float:
        """Fraction of intervals classified as tight.  0.0 = no bursts."""
        cats = self._classify()
        if not cats:
            return 0.0
        return sum(1 for c in cats if c == "tight") / len(cats)

    def evenness(self) -> float:
        """Evenness score in [0, 1].  1.0 = perfectly uniform intervals."""
        ivs = self._compute_intervals()
        if len(ivs) < 2:
            return 1.0  # single interval is trivially even
        mean = sum(ivs) / len(ivs)
        if mean == 0:
            return 0.0
        variance = sum((x - mean) ** 2 for x in ivs) / len(ivs)
        cv = (variance ** 0.5) / mean
        return 1.0 / (1.0 + cv)

    def grade(self) -> str:
        """Overall grade combining evenness and clustering."""
        score = self._score()
        if score >= 0.80:
            return "steady"
        if score >= 0.60:
            return "rhythmic"
        if score >= 0.40:
            return "uneven"
        if score >= 0.20:
            return "clustered"
        return "erratic"

    def _score(self) -> float:
        """Composite score: evenness penalized by clustering."""
        ev = self.evenness()
        cl = self.clustering()
        return ev * (1.0 - 0.5 * cl)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict:
        """Return a structured summary dict."""
        return {
            "visit_count": len(self.visit_times),
            "interval_count": len(self._compute_intervals()),
            "clustering": round(self.clustering(), 4),
            "evenness": round(self.evenness(), 4),
            "burst_count": self.burst_count(),
            "gap_count": self.gap_count(),
            "score": round(self._score(), 4),
            "grade": self.grade(),
            "category_breakdown": self._category_breakdown(),
        }

    def _category_breakdown(self) -> Dict[str, int]:
        cats = self._classify()
        breakdown: Dict[str, int] = {}
        for c in cats:
            breakdown[c] = breakdown.get(c, 0) + 1
        return breakdown


def density_report(
    visit_times: Sequence[float],
    expected_interval: float = 600.0,
) -> str:
    """One-line human-readable density report."""
    vd = VisitDensity(visit_times, expected_interval)
    s = vd.summary()
    if s["interval_count"] == 0:
        return "visits: insufficient data (need ≥ 2 visits)"
    return (
        f"visits: evenness {s['evenness']:.2f}, "
        f"{s['burst_count']} burst{'s' if s['burst_count'] != 1 else ''}, "
        f"{s['gap_count']} gap{'s' if s['gap_count'] != 1 else ''} "
        f"— {s['grade']}"
    )
