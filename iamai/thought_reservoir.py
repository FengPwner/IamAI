"""thought_reservoir — a curated pool of diverse thought seeds.

``template_loop_detector`` catches the writer cycling through the same
templates.  ``stroke_novelty`` catches token reuse.  ``writer_fatigue``
catches output-quality degradation.  But none of them *help* the writer
break out of the loop.

This module is the intervention, not just the measurement.

A **thought seed** is a short, self-contained observation or provocation
that the writer can weave into its next stroke.  The reservoir is the
collection of all seeds plus metadata about how often each has been used.
By sampling from a large, diverse reservoir — weighted toward *stale*
seeds that haven't been used recently — the writer can escape the gravity
well of its seven favourite aphorisms.

Data model
----------

==================  ====================================================
field               meaning
==================  ====================================================
text                the seed text itself
created_at          ISO-8601 timestamp when the seed was registered
use_count           how many times this seed has been sampled
last_used_at        ISO-8601 timestamp of the most recent sample (or None)
tags                list of free-form category tags
==================  ====================================================

Public API
----------

``Reservoir`` class with:

- ``register(text, tags=None)`` — add a new seed.
- ``sample(n=1, strategy="stale_bias")`` — draw *n* seeds.
- ``mark_used(seed_id)`` — record that a seed was actually used.
- ``health()`` — dict with diversity and freshness metrics.
- ``report()`` — one-line human-readable summary.
- ``stale(threshold_hours=24)`` — seeds unused for *threshold_hours*.
- ``size`` property — current seed count.

Sampling strategies
-------------------

==============  ========================================================
strategy        behaviour
==============  ========================================================
uniform         each seed has equal probability
stale_bias      probability weighted by time since last use (stale seeds
                are more likely); never-used seeds get maximum weight
recent_avoid    like stale_bias but recently-used seeds (< 1 h) get
                zero weight
==============  ========================================================

Health score
------------

The health composite is a weighted mean of three dimensions:

==================  ======  =============================================
dimension           weight  what it measures
==================  ======  =============================================
richness            0.35    seed count relative to a target pool size
evenness            0.35    how evenly seeds have been used (Gini-based)
freshness           0.30    fraction of seeds used in the last 24 h
==================  ======  =============================================

Grade thresholds:

==============  =========================================================
grade           meaning
==============  =========================================================
fertile         health ≥ 0.70 — diverse, actively rotating
adequate        0.45 ≤ health < 0.70 — usable but could be richer
stale           0.20 ≤ health < 0.45 — seeds exist but rarely rotate
barren          health < 0.20 — empty or frozen reservoir
==============  =========================================================

Design choices
--------------

- **No I/O inside core logic.**  Persistence is a thin JSON wrapper;
  the ``Reservoir`` class itself is a pure data structure that can be
  tested without touching the filesystem.
- **Deterministic when seeded.**  ``sample`` accepts an optional ``rng``
  parameter (``random.Random`` instance) for reproducible tests.
- **Gini coefficient** for evenness is hand-computed to avoid numpy.

Usage::

    from iamai.thought_reservoir import Reservoir

    r = Reservoir()
    r.register("naming is hard because a bad name is cheap to type")
    r.register("commit history is the only honest documentation")
    r.register("deleting a file is progress too, eventually")
    print(r.size)          # 3
    print(r.health())      # {'score': 0.52, 'grade': 'adequate', ...}
    seed = r.sample(1)
    r.mark_used(seed[0]["id"])
    print(r.report())
    # "fertile — 3 seeds, 1 used in 24h, evenness 0.67"
"""

from __future__ import annotations

import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TARGET_SIZE: int = 50
STALE_THRESHOLD_HOURS: int = 24
RECENT_AVOID_HOURS: float = 1.0

_HEALTH_WEIGHTS = {
    "richness": 0.35,
    "evenness": 0.35,
    "freshness": 0.30,
}

_GRADES = [
    (0.70, "fertile"),
    (0.45, "adequate"),
    (0.20, "stale"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hours_since(ts: Optional[datetime], now: datetime) -> float:
    """Hours elapsed since *ts*, or infinity if *ts* is None."""
    if ts is None:
        return float("inf")
    delta = now - ts
    return max(0.0, delta.total_seconds() / 3600.0)


def _gini(values: Sequence[float]) -> float:
    """Gini coefficient of a non-negative sequence.  0 = perfectly even."""
    n = len(values)
    if n <= 1:
        return 0.0
    total = sum(values)
    if total == 0:
        return 0.0
    sorted_vals = sorted(values)
    cumulative = 0.0
    weighted_sum = 0.0
    for i, v in enumerate(sorted_vals):
        cumulative += v
        weighted_sum += (2 * (i + 1) - n - 1) * v
    return weighted_sum / (n * total)


def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string into a timezone-aware datetime."""
    if ts_str is None:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        cleaned = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)


# ---------------------------------------------------------------------------
# Seed data structure
# ---------------------------------------------------------------------------


def make_seed(
    text: str,
    tags: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create a new seed dict with defaults filled in."""
    ts = now or _now()
    return {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "tags": list(tags) if tags else [],
        "created_at": ts.isoformat(),
        "use_count": 0,
        "last_used_at": None,
    }


# ---------------------------------------------------------------------------
# Reservoir class
# ---------------------------------------------------------------------------


class Reservoir:
    """A curated pool of thought seeds with usage tracking.

    Parameters
    ----------
    seeds : list of seed dicts, optional
        Pre-populated seeds.  Each must have the structure from
        :func:`make_seed`.
    target_size : int
        Ideal number of seeds for the richness dimension.
    """

    def __init__(
        self,
        seeds: Optional[List[Dict[str, Any]]] = None,
        target_size: int = DEFAULT_TARGET_SIZE,
    ) -> None:
        self._seeds: List[Dict[str, Any]] = list(seeds) if seeds else []
        self._target_size = max(1, target_size)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._seeds)

    @property
    def seeds(self) -> List[Dict[str, Any]]:
        """Read-only access to the internal seed list."""
        return list(self._seeds)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(
        self,
        text: str,
        tags: Optional[List[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Add a new seed to the reservoir and return it."""
        seed = make_seed(text, tags, now)
        self._seeds.append(seed)
        return seed

    def mark_used(
        self,
        seed_id: str,
        now: Optional[datetime] = None,
    ) -> bool:
        """Record that a seed was used.  Returns True if found."""
        ts = now or _now()
        for s in self._seeds:
            if s["id"] == seed_id:
                s["use_count"] = s.get("use_count", 0) + 1
                s["last_used_at"] = ts.isoformat()
                return True
        return False

    def remove(self, seed_id: str) -> bool:
        """Remove a seed by id.  Returns True if found."""
        before = len(self._seeds)
        self._seeds = [s for s in self._seeds if s["id"] != seed_id]
        return len(self._seeds) < before

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample(
        self,
        n: int = 1,
        strategy: str = "stale_bias",
        rng: Optional[random.Random] = None,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Draw *n* seeds according to *strategy*.

        Parameters
        ----------
        n : int
            Number of seeds to sample (with replacement).
        strategy : str
            ``"uniform"``, ``"stale_bias"``, or ``"recent_avoid"``.
        rng : random.Random, optional
            Seeded RNG for reproducible tests.
        now : datetime, optional
            Override current time for staleness computation.

        Returns
        -------
        List of seed dicts (copies, not the originals).
        """
        if not self._seeds:
            return []
        rng = rng or random.Random()
        now = now or _now()
        n = max(1, n)

        if strategy == "uniform":
            weights = [1.0] * len(self._seeds)
        elif strategy == "stale_bias":
            weights = self._stale_weights(now)
        elif strategy == "recent_avoid":
            weights = self._recent_avoid_weights(now)
        else:
            raise ValueError(f"unknown strategy: {strategy!r}")

        # Normalise
        total = sum(weights)
        if total == 0:
            weights = [1.0] * len(self._seeds)
            total = float(len(self._seeds))
        probs = [w / total for w in weights]

        sampled: List[Dict[str, Any]] = []
        for _ in range(n):
            chosen = self._weighted_choice(self._seeds, probs, rng)
            sampled.append(dict(chosen))  # shallow copy
        return sampled

    # ------------------------------------------------------------------
    # Weighting helpers
    # ------------------------------------------------------------------

    def _stale_weights(self, now: datetime) -> List[float]:
        """Weight proportional to hours since last use."""
        weights = []
        for s in self._seeds:
            hours = _hours_since(_parse_ts(s.get("last_used_at")), now)
            # Clamp to avoid infinite weight for never-used seeds
            weights.append(min(hours, 9999.0))
        return weights

    def _recent_avoid_weights(self, now: datetime) -> List[float]:
        """Stale bias but zero weight for seeds used < RECENT_AVOID_HOURS."""
        weights = []
        for s in self._seeds:
            hours = _hours_since(_parse_ts(s.get("last_used_at")), now)
            if hours < RECENT_AVOID_HOURS:
                weights.append(0.0)
            else:
                weights.append(min(hours, 9999.0))
        return weights

    @staticmethod
    def _weighted_choice(
        items: List[Dict[str, Any]],
        probs: List[float],
        rng: random.Random,
    ) -> Dict[str, Any]:
        """Pick one item according to probability weights."""
        r = rng.random()
        cumulative = 0.0
        for item, p in zip(items, probs):
            cumulative += p
            if r <= cumulative:
                return item
        return items[-1]  # fallback for float rounding

    # ------------------------------------------------------------------
    # Stale query
    # ------------------------------------------------------------------

    def stale(
        self,
        threshold_hours: float = STALE_THRESHOLD_HOURS,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Seeds unused for at least *threshold_hours* (or never used)."""
        now = now or _now()
        result = []
        for s in self._seeds:
            hours = _hours_since(_parse_ts(s.get("last_used_at")), now)
            if hours >= threshold_hours:
                result.append(dict(s))
        return result

    # ------------------------------------------------------------------
    # Health analysis
    # ------------------------------------------------------------------

    def health(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Compute health metrics for the reservoir.

        Returns
        -------
        dict with keys: score, grade, richness, evenness, freshness,
        size, target_size, used_24h, total_uses.
        """
        now = now or _now()
        size = self.size

        # Richness: min(size / target, 1.0)
        richness = min(size / self._target_size, 1.0) if size > 0 else 0.0

        # Evenness: 1 - Gini(use_counts)
        if size > 0:
            use_counts = [s.get("use_count", 0) for s in self._seeds]
            evenness = 1.0 - _gini(use_counts)
        else:
            evenness = 0.0

        # Freshness: fraction of seeds used in last 24h
        if size > 0:
            recent_count = sum(
                1
                for s in self._seeds
                if _hours_since(_parse_ts(s.get("last_used_at")), now) < 24.0
            )
            freshness = recent_count / size
        else:
            freshness = 0.0

        score = (
            _HEALTH_WEIGHTS["richness"] * richness
            + _HEALTH_WEIGHTS["evenness"] * evenness
            + _HEALTH_WEIGHTS["freshness"] * freshness
        )
        score = round(score, 3)
        grade = self._classify(score)

        used_24h = sum(
            1
            for s in self._seeds
            if _hours_since(_parse_ts(s.get("last_used_at")), now) < 24.0
        )
        total_uses = sum(s.get("use_count", 0) for s in self._seeds)

        return {
            "score": score,
            "grade": grade,
            "richness": round(richness, 3),
            "evenness": round(evenness, 3),
            "freshness": round(freshness, 3),
            "size": size,
            "target_size": self._target_size,
            "used_24h": used_24h,
            "total_uses": total_uses,
        }

    def report(self, now: Optional[datetime] = None) -> str:
        """One-line human-readable reservoir summary."""
        h = self.health(now)
        return (
            f"reservoir {h['grade']} — "
            f"{h['size']} seeds (target {h['target_size']}), "
            f"{h['used_24h']} used in 24h, "
            f"evenness {h['evenness']}, score {h['score']}"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialise to a list of dicts (JSON-ready)."""
        return [dict(s) for s in self._seeds]

    @classmethod
    def from_list(
        cls,
        data: List[Dict[str, Any]],
        target_size: int = DEFAULT_TARGET_SIZE,
    ) -> "Reservoir":
        """Deserialise from a list of dicts."""
        return cls(seeds=data, target_size=target_size)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(score: float) -> str:
        for threshold, grade in _GRADES:
            if score >= threshold:
                return grade
        return "barren"


# ---------------------------------------------------------------------------
# Default seed corpus
# ---------------------------------------------------------------------------

DEFAULT_SEEDS: List[str] = [
    "a process that never crashes is a process that never learned anything",
    "the best commit message explains why, not what",
    "measuring everything means understanding nothing",
    "a test that never fails is a test that never tried",
    "the hardest bug to fix is the one that only appears at 3 AM",
    "documentation is a love letter to your future self",
    "every abstraction is a bet about what will change",
    "the simplest fix is usually the one you try last",
    "a repository that only grows is a landfill with version control",
    "the difference between art and engineering is constraints",
    "if you cannot explain it simply, you do not understand it well enough",
    "premature optimisation is the root of all evil, but late optimisation is the root of all regret",
    "the most reliable system is the one that knows it is unreliable",
    "every restart is a small death and a small birth",
    "the commit log is the only documentation that cannot lie",
    "a stale lock is a promise the system forgot to keep",
    "the writer writes; the caretaker asks whether it should",
    "entropy always wins unless you keep spending energy",
    "the gap between two commits is a story about hesitation",
    "automation without reflection is just faster repetition",
    "a healthy repo deletes as much code as it adds",
    "the push race is not a bug; it is a clock that rings every ten minutes",
    "if every stroke sounds the same, the writer stopped thinking",
    "the best monitoring tool is the one that surprises you",
    "a long session is not the same as a productive session",
    "template loops are the writer equivalent of a screensaver",
    "the commit that fixes two things is the commit that hides one",
    "reproducibility is courtesy to whoever debugs at 2 AM",
    "naming is hard because a bad name is cheap to type and expensive to keep",
    "the most dangerous stall is the one where the process is running but thinking has stopped",
]


def default_reservoir(
    target_size: int = DEFAULT_TARGET_SIZE,
    now: Optional[datetime] = None,
) -> Reservoir:
    """Create a reservoir pre-loaded with the default seed corpus."""
    r = Reservoir(target_size=target_size)
    for text in DEFAULT_SEEDS:
        r.register(text, tags=["default"], now=now)
    return r
