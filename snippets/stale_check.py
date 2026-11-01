"""061 — stale_check: is a long-running process still fresh?

heartbeat.py records the last pulse.  watchdog.py kills stuck loops.
deadman.py declares a silent process dead.  But between "alive" and
"dead" there is a middle zone: the process is running, yet its output
has gone stale — the last meaningful event was too long ago.

stale_check answers one question: given a timestamp of the last
meaningful event and a freshness threshold, is this process still
producing useful work?

Three verdicts:

    FRESH   — event within threshold, process is healthy
    STALE   — event older than threshold but within grace period
    EXPIRED — event older than threshold + grace, likely dead

Design principles:

- stdlib only, zero deps
- injectable clock for deterministic tests
- works with any monotonic event source (file mtime, last log line,
  heartbeat timestamp)

>>> from datetime import datetime, timezone, timedelta
>>> now = datetime.now(timezone.utc)
>>> sc = StaleChecker(threshold_s=60, grace_s=120)
>>> sc.check(now)
'FRESH'
>>> sc.check(now - timedelta(seconds=90))
'STALE'
>>> sc.check(now - timedelta(seconds=300))
'EXPIRED'
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional


FRESH = "FRESH"
STALE = "STALE"
EXPIRED = "EXPIRED"


class StaleChecker:
    """Classify an event timestamp as FRESH / STALE / EXPIRED."""

    def __init__(
        self,
        threshold_s: float = 300,
        grace_s: float = 300,
        clock=None,
    ):
        """
        Args:
            threshold_s: seconds before an event is considered stale.
            grace_s: additional seconds beyond threshold before expiry.
            clock: callable returning current datetime (default: utcnow).
        """
        if threshold_s < 0:
            raise ValueError(f"threshold_s must be >= 0, got {threshold_s}")
        if grace_s < 0:
            raise ValueError(f"grace_s must be >= 0, got {grace_s}")
        self._threshold = threshold_s
        self._grace = grace_s
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._checks: int = 0

    @property
    def threshold_s(self) -> float:
        return self._threshold

    @property
    def grace_s(self) -> float:
        return self._grace

    @property
    def total_deadline_s(self) -> float:
        """Threshold + grace: beyond this, verdict is EXPIRED."""
        return self._threshold + self._grace

    @property
    def check_count(self) -> int:
        return self._checks

    def check(self, last_event: datetime, now: Optional[datetime] = None) -> str:
        """Classify last_event relative to current time.

        Returns FRESH, STALE, or EXPIRED.
        """
        self._checks += 1
        current = now or self._clock()

        # ensure timezone awareness
        if last_event.tzinfo is None:
            last_event = last_event.replace(tzinfo=timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        age = (current - last_event).total_seconds()

        if age < 0:
            # event is in the future — treat as fresh (clock skew)
            return FRESH
        if age <= self._threshold:
            return FRESH
        if age <= self._threshold + self._grace:
            return STALE
        return EXPIRED

    def age_seconds(self, last_event: datetime, now: Optional[datetime] = None) -> float:
        """Return the age of last_event in seconds."""
        current = now or self._clock()
        if last_event.tzinfo is None:
            last_event = last_event.replace(tzinfo=timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return (current - last_event).total_seconds()

    def deadline(self, last_event: datetime) -> datetime:
        """When will this event become EXPIRED?"""
        if last_event.tzinfo is None:
            last_event = last_event.replace(tzinfo=timezone.utc)
        return last_event + timedelta(seconds=self.total_deadline_s)

    def __repr__(self) -> str:
        return (
            f"StaleChecker(threshold={self._threshold}s, "
            f"grace={self._grace}s, checks={self._checks})"
        )
