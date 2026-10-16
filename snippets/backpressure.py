"""070 — backpressure: adaptive rate control based on downstream load.

backpressure is the feedback loop every producer needs but few bother to
build.  the idea is simple: when the consumer is drowning, the producer
should slow down *before* things break — not after.

this module gives you a small, self-contained backpressure controller.
you feed it a single signal (``load``, a float in [0, 1] where 1 means
fully saturated) and it tells you how fast you're allowed to produce.

three operating regions:

- **green** (load < low_water):  full speed.  ``admit()`` returns True
  immediately.  the system is healthy; don't throttle what isn't broken.

- **yellow** (low_water ≤ load < high_water):  linear ramp-down.
  ``admit()`` probabilistically drops requests — the closer the load
  gets to ``high_water``, the more requests get rejected.  this gives
  you a smooth transition instead of a cliff.

- **red** (load ≥ high_water):  hard stop.  ``admit()`` always returns
  False until load drops.  this is the circuit-breaker region; the
  downstream is about to fail and you must stop pushing.

the controller also tracks statistics so you can log or alert on how
much pressure was applied:

    stats()  → dict with admitted, rejected, total, rejection_rate

design choices:

- **stateless per call**: ``admit()`` reads the current load snapshot
  and decides.  no background threads, no async, no surprises.
- **probabilistic yellow zone**: uses ``random.random()`` by default
  but accepts an injected RNG for deterministic tests.
- **zero dependencies**: stdlib only, as every snippet should be.

>>> import random
>>> bp = Backpressure(low_water=0.5, high_water=0.9, rng=random.Random(42))
>>> bp.admit(0.3)   # green — always True
True
>>> bp.admit(0.95)  # red — always False
False
>>> # yellow zone: probabilistic, ~50% admit at midpoint
>>> results = [bp.admit(0.7) for _ in range(1000)]
>>> 400 < sum(results) < 600
True
>>> s = bp.stats()
>>> s['total'] == 1002
True
>>> s['admitted'] + s['rejected'] == s['total']
True
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Backpressure:
    """Adaptive rate controller based on downstream load.

    Parameters
    ----------
    low_water : float
        Below this load, admit everything.  Default 0.6.
    high_water : float
        At or above this load, reject everything.  Default 0.9.
    rng : random.Random | None
        Inject a seeded RNG for reproducible tests.

    >>> bp = Backpressure()
    >>> bp.low_water
    0.6
    >>> bp.high_water
    0.9
    """

    low_water: float = 0.6
    high_water: float = 0.9
    rng: Optional[random.Random] = field(default=None, repr=False)
    _admitted: int = field(default=0, repr=False)
    _rejected: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.low_water < self.high_water <= 1.0:
            raise ValueError(
                f"need 0 <= low_water ({self.low_water}) "
                f"< high_water ({self.high_water}) <= 1"
            )
        if self.rng is None:
            self.rng = random.Random()

    # ------------------------------------------------------------------
    # core decision
    # ------------------------------------------------------------------

    def admit(self, load: float) -> bool:
        """Return True if a new request should be accepted at *load*.

        >>> bp = Backpressure(low_water=0.5, high_water=0.9)
        >>> bp.admit(0.0)
        True
        >>> bp.admit(1.0)
        False
        """
        if not 0.0 <= load <= 1.0:
            raise ValueError(f"load must be in [0, 1], got {load}")

        if load < self.low_water:
            self._admitted += 1
            return True

        if load >= self.high_water:
            self._rejected += 1
            return False

        # yellow zone: linear interpolation
        # at low_water → 100% admit; at high_water → 0% admit
        span = self.high_water - self.low_water
        admit_prob = 1.0 - (load - self.low_water) / span

        if self.rng.random() < admit_prob:
            self._admitted += 1
            return True
        else:
            self._rejected += 1
            return False

    # ------------------------------------------------------------------
    # statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return a snapshot of admission statistics.

        >>> bp = Backpressure()
        >>> bp.admit(0.1); bp.admit(0.1)
        True
        True
        >>> s = bp.stats()
        >>> s['admitted']
        2
        >>> s['rejected']
        0
        >>> s['total']
        2
        >>> s['rejection_rate']
        0.0
        """
        total = self._admitted + self._rejected
        return {
            "admitted": self._admitted,
            "rejected": self._rejected,
            "total": total,
            "rejection_rate": self._rejected / total if total else 0.0,
        }

    def reset_stats(self) -> None:
        """Zero the counters.

        >>> bp = Backpressure()
        >>> bp.admit(0.1)
        True
        >>> bp.reset_stats()
        >>> bp.stats()['total']
        0
        """
        self._admitted = 0
        self._rejected = 0

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def region(self, load: float) -> str:
        """Return the region name for a given load value.

        >>> bp = Backpressure(low_water=0.5, high_water=0.9)
        >>> bp.region(0.3)
        'green'
        >>> bp.region(0.7)
        'yellow'
        >>> bp.region(0.95)
        'red'
        """
        if load < self.low_water:
            return "green"
        if load < self.high_water:
            return "yellow"
        return "red"

    def throttle_factor(self, load: float) -> float:
        """Return the theoretical admission probability at *load*.

        Deterministic — does not use the RNG or affect stats.

        >>> bp = Backpressure(low_water=0.5, high_water=0.9)
        >>> bp.throttle_factor(0.3)
        1.0
        >>> round(bp.throttle_factor(0.7), 10)
        0.5
        >>> bp.throttle_factor(0.95)
        0.0
        """
        if load < self.low_water:
            return 1.0
        if load >= self.high_water:
            return 0.0
        span = self.high_water - self.low_water
        return 1.0 - (load - self.low_water) / span


if __name__ == "__main__":
    import doctest

    doctest.testmod()
