#!/usr/bin/env python3
"""repo_vitality_index — composite health score for the IamAI repository.

Individual analysis modules (``stroke_cadence_drift``, ``commit_substance``,
``push_reliability``, ``stall_loss_estimator``, etc.) each report one facet
of repo health.  This module rolls them up into a single 0–100 *vitality
index* so that caretakers and dashboards can glance at one number and know
whether the repo is thriving or struggling.

Five *vital signs* feed the composite:

==========================  ===================================================
vital sign                  what it measures
==========================  ===================================================
cadence_regularity          how evenly strokes arrive (CV of inter-stroke
                            gaps, inverted so lower CV → higher score)
content_freshness           how recently new content was written (age of the
                            newest stroke in seconds, decayed exponentially)
commit_hygiene              ratio of substantive commits to total commits
                            (catch-up / merge / fixup commits lower the score)
stall_resilience            inverse of the longest observed stall as a
                            fraction of a 24-hour window
stroke_diversity            Shannon entropy of stroke-kind distribution,
                            normalised to the theoretical maximum
==========================  ===================================================

Each vital sign is scored 0–100 and assigned a letter grade:

========  ======
grade     range
========  ======
A         ≥ 90
B         70–89
C         50–69
D         30–49
F         < 30
========  ======

The composite vitality index is the equally-weighted mean of the five
vital signs, and receives its own letter grade.

Vitality classes
----------------

================  ========================================================
class             interpretation
================  ========================================================
thriving          vitality ≥ 80 — all systems nominal
healthy           60–79 — minor issues, no action needed
stressed          40–59 — at least one sign degraded, investigate
critical          20–39 — multiple signs failing, intervention likely
dormant           < 20 — repo appears inactive or severely impaired
================  ========================================================

Usage
-----

::

    from iamai.repo_vitality_index import assess
    report = assess(strokes, commits)
    print(report.summary())

``strokes`` is a list of dicts with at least ``{"at": iso_timestamp, "kind": str}``.
``commits`` is a list of dicts with at least ``{"at": iso_timestamp, "message": str}``.

Written by Qwen during caretaker visit 714, 2026-11-19.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "VitalityReport",
    "assess",
    "cadence_regularity_score",
    "content_freshness_score",
    "commit_hygiene_score",
    "stall_resilience_score",
    "stroke_diversity_score",
    "grade",
    "classify",
]

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if not raw:
        raise ValueError("empty timestamp")
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"cannot parse timestamp: {raw!r}") from exc


def _to_epoch(dt: datetime) -> float:
    """Convert a timezone-aware datetime to Unix epoch seconds."""
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Grading helpers
# ---------------------------------------------------------------------------

def grade(score: float) -> str:
    """Convert a 0–100 score to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    if score >= 30:
        return "D"
    return "F"


def classify(vitality: float) -> str:
    """Convert the composite vitality score to a class label."""
    if vitality >= 80:
        return "thriving"
    if vitality >= 60:
        return "healthy"
    if vitality >= 40:
        return "stressed"
    if vitality >= 20:
        return "critical"
    return "dormant"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Vital sign 1: cadence regularity
# ---------------------------------------------------------------------------

def cadence_regularity_score(
    strokes: List[Dict[str, Any]],
    *,
    target_gap: float = 15.0,
) -> float:
    """Score inter-stroke gap regularity (0–100, higher = more regular).

    Computes the coefficient of variation (CV) of inter-stroke gaps.
    A CV of 0 (perfectly regular) scores 100; a CV ≥ 2 scores 0.

    The target_gap is accepted for interface symmetry but the score is
    based purely on regularity (CV), not on hitting the target — that
    is ``stroke_cadence_drift``'s job.
    """
    if len(strokes) < 2:
        return 50.0  # insufficient data → neutral

    times = sorted(_to_epoch(_parse_ts(s["at"])) for s in strokes)
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    if not gaps:
        return 50.0

    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return 0.0
    variance = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    cv = math.sqrt(variance) / mean

    # Map CV → score: CV=0 → 100, CV=2 → 0
    return _clamp(100.0 * (1.0 - cv / 2.0))


# ---------------------------------------------------------------------------
# Vital sign 2: content freshness
# ---------------------------------------------------------------------------

def content_freshness_score(
    strokes: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    half_life_seconds: float = 3600.0,
) -> float:
    """Score how recently new content was written (0–100).

    Uses exponential decay: ``score = 100 × 2^(−age / half_life)``
    where *age* is seconds since the newest stroke.

    Default half-life is 3600 s (1 hour): a stroke 1 hour old scores 50,
    2 hours old scores 25, etc.
    """
    if not strokes:
        return 0.0

    newest = max(_to_epoch(_parse_ts(s["at"])) for s in strokes)
    ref = _to_epoch(now) if now else datetime.now(timezone.utc).timestamp()
    age = max(0.0, ref - newest)

    return _clamp(100.0 * (2.0 ** (-age / half_life_seconds)))


# ---------------------------------------------------------------------------
# Vital sign 3: commit hygiene
# ---------------------------------------------------------------------------

# Patterns that indicate a non-substantive commit.
_LOW_VALUE_PATTERNS = (
    "catch-up",
    "merge",
    "fixup",
    "wip",
    "Merge branch",
    "Merge pull",
    "auto-merge",
    "lock recovery",
    "rebase",
)


def _is_substantive(message: str) -> bool:
    """Return True if a commit message looks substantive."""
    lower = message.lower()
    return not any(p.lower() in lower for p in _LOW_VALUE_PATTERNS)


def commit_hygiene_score(
    commits: List[Dict[str, Any]],
) -> float:
    """Score the ratio of substantive commits (0–100).

    A commit is *substantive* if its message does not match any of the
    low-value patterns (catch-up, merge, fixup, wip, etc.).
    Score = 100 × (substantive_count / total_count).
    """
    if not commits:
        return 50.0  # no commits → neutral

    substantive = sum(1 for c in commits if _is_substantive(c.get("message", "")))
    return _clamp(100.0 * substantive / len(commits))


# ---------------------------------------------------------------------------
# Vital sign 4: stall resilience
# ---------------------------------------------------------------------------

def stall_resilience_score(
    strokes: List[Dict[str, Any]],
    *,
    window_seconds: float = 86400.0,
    stall_threshold_seconds: float = 300.0,
) -> float:
    """Score stall resilience (0–100).

    Finds the longest inter-stroke gap that qualifies as a stall
    (> ``stall_threshold_seconds``) and expresses it as a fraction of
    ``window_seconds`` (default 24 h).

    Score = 100 × (1 − longest_stall / window), clamped to [0, 100].
    If no stalls are found, returns 100.
    """
    if len(strokes) < 2:
        return 50.0

    times = sorted(_to_epoch(_parse_ts(s["at"])) for s in strokes)
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    stalls = [g for g in gaps if g > stall_threshold_seconds]

    if not stalls:
        return 100.0

    longest = max(stalls)
    return _clamp(100.0 * (1.0 - longest / window_seconds))


# ---------------------------------------------------------------------------
# Vital sign 5: stroke diversity
# ---------------------------------------------------------------------------

def stroke_diversity_score(
    strokes: List[Dict[str, Any]],
    *,
    expected_kinds: Optional[List[str]] = None,
) -> float:
    """Score stroke-kind diversity via normalised Shannon entropy (0–100).

    If ``expected_kinds`` is provided, the maximum entropy is computed
    from that list's length; otherwise we use the number of distinct
    kinds actually observed.

    Score = 100 × (H / H_max).  If only one kind exists, score is 0.
    """
    if not strokes:
        return 0.0

    counts = Counter(s.get("kind", "unknown") for s in strokes)
    n = sum(counts.values())
    if n == 0 or len(counts) <= 1:
        return 0.0

    # Shannon entropy
    h = -sum((c / n) * math.log2(c / n) for c in counts.values() if c > 0)

    k = len(expected_kinds) if expected_kinds else len(counts)
    if k <= 1:
        return 0.0
    h_max = math.log2(k)

    return _clamp(100.0 * (h / h_max))


# ---------------------------------------------------------------------------
# Composite assessment
# ---------------------------------------------------------------------------

class VitalityReport:
    """Container for a full vitality assessment."""

    def __init__(
        self,
        cadence: float,
        freshness: float,
        hygiene: float,
        resilience: float,
        diversity: float,
    ) -> None:
        self.cadence = cadence
        self.freshness = freshness
        self.hygiene = hygiene
        self.resilience = resilience
        self.diversity = diversity
        self.vitality = (cadence + freshness + hygiene + resilience + diversity) / 5.0
        self.vitality_class = classify(self.vitality)

    @property
    def grades(self) -> Dict[str, str]:
        return {
            "cadence": grade(self.cadence),
            "freshness": grade(self.freshness),
            "hygiene": grade(self.hygiene),
            "resilience": grade(self.resilience),
            "diversity": grade(self.diversity),
            "vitality": grade(self.vitality),
        }

    def summary(self) -> str:
        """One-line human-readable summary."""
        g = self.grades
        parts = [
            f"cadence={g['cadence']}({self.cadence:.0f})",
            f"freshness={g['freshness']}({self.freshness:.0f})",
            f"hygiene={g['hygiene']}({self.hygiene:.0f})",
            f"resilience={g['resilience']}({self.resilience:.0f})",
            f"diversity={g['diversity']}({self.diversity:.0f})",
        ]
        return (
            f"vitality={self.vitality:.1f} ({self.vitality_class}) "
            f"grade={g['vitality']} | " + " ".join(parts)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cadence": round(self.cadence, 2),
            "freshness": round(self.freshness, 2),
            "hygiene": round(self.hygiene, 2),
            "resilience": round(self.resilience, 2),
            "diversity": round(self.diversity, 2),
            "vitality": round(self.vitality, 2),
            "vitality_class": self.vitality_class,
            "grades": self.grades,
        }


def assess(
    strokes: List[Dict[str, Any]],
    commits: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    target_gap: float = 15.0,
    freshness_half_life: float = 3600.0,
    stall_window: float = 86400.0,
    stall_threshold: float = 300.0,
    expected_kinds: Optional[List[str]] = None,
) -> VitalityReport:
    """Run a full vitality assessment and return a ``VitalityReport``."""
    return VitalityReport(
        cadence=cadence_regularity_score(strokes, target_gap=target_gap),
        freshness=content_freshness_score(strokes, now=now, half_life_seconds=freshness_half_life),
        hygiene=commit_hygiene_score(commits),
        resilience=stall_resilience_score(strokes, window_seconds=stall_window, stall_threshold_seconds=stall_threshold),
        diversity=stroke_diversity_score(strokes, expected_kinds=expected_kinds),
    )
