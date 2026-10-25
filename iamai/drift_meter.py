"""Drift meter: measure local/remote commit divergence and alert early.

A self-writing repo pushes on a fixed cadence.  When a push is rejected
because the remote moved ahead, the local branch has *drifted* — the gap
between the local tip and the remote tip measured in commits on each side.

DriftMeter tracks this gap over time in a bounded history ring.  It exposes:

* ``ahead`` / ``behind`` — commits local is ahead of / behind the remote.
* ``ratio`` — behind / max(ahead, 1).  A ratio > 1.0 means the remote is
  pulling away faster than we push; time to rebase.
* ``alert`` — ``none``, ``watch``, or ``pull_now`` based on configurable
  thresholds.
* ``trend`` — comparing the last two measurements to see if drift is
  growing, stable, or shrinking.

All state is in-memory; no I/O.  O(1) per measurement.

Usage::

    from iamai.drift_meter import DriftMeter

    dm = DriftMeter()
    dm.measure(ahead=2, behind=0)   # just pushed, clean
    dm.measure(ahead=1, behind=3)   # remote moved while we were offline
    dm.alert                        # "pull_now"
    dm.ratio                        # 3.0
    dm.trend                        # "growing"
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# Alert levels
NONE = "none"
WATCH = "watch"
PULL_NOW = "pull_now"

# Trend directions
GROWING = "growing"
STABLE = "stable"
SHRINKING = "shrinking"


@dataclass
class _Snapshot:
    """One drift measurement."""

    ahead: int
    behind: int

    @property
    def total(self) -> int:
        return self.ahead + self.behind

    @property
    def ratio(self) -> float:
        """behind / max(ahead, 1).  > 1 means remote outruns local."""
        return self.behind / max(self.ahead, 1)


@dataclass
class DriftMeter:
    """Track local/remote commit divergence over time.

    Parameters
    ----------
    history : int
        How many measurements to retain.  Default 50.
    watch_behind : int
        ``behind`` count that raises a *watch* alert.  Default 2.
    pull_now_behind : int
        ``behind`` count that raises a *pull_now* alert.  Default 5.
    watch_ratio : float
        Ratio above which alert escalates to at least *watch*.  Default 1.0.
    pull_now_ratio : float
        Ratio above which alert escalates to *pull_now*.  Default 2.0.
    """

    history: int = 50
    watch_behind: int = 2
    pull_now_behind: int = 5
    watch_ratio: float = 1.0
    pull_now_ratio: float = 2.0
    _ring: deque = field(default_factory=lambda: deque(maxlen=50))

    def __post_init__(self) -> None:
        self._ring = deque(maxlen=self.history)

    # ------------------------------------------------------------------
    # recording
    # ------------------------------------------------------------------

    def measure(self, ahead: int, behind: int) -> _Snapshot:
        """Record a new divergence measurement.

        Parameters
        ----------
        ahead : int
            Commits local is ahead of the common ancestor (un-pushed).
        behind : int
            Commits remote is ahead of the common ancestor (un-pulled).

        Returns
        -------
        _Snapshot
            The recorded measurement.
        """
        snap = _Snapshot(ahead=max(ahead, 0), behind=max(behind, 0))
        self._ring.append(snap)
        return snap

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Number of measurements recorded."""
        return len(self._ring)

    @property
    def latest(self) -> Optional[_Snapshot]:
        """Most recent measurement, or ``None`` if empty."""
        return self._ring[-1] if self._ring else None

    @property
    def ahead(self) -> int:
        """Local-ahead from the latest measurement."""
        return self._ring[-1].ahead if self._ring else 0

    @property
    def behind(self) -> int:
        """Remote-behind from the latest measurement."""
        return self._ring[-1].behind if self._ring else 0

    @property
    def ratio(self) -> float:
        """Drift ratio (behind / max(ahead, 1)) from the latest measurement."""
        return self._ring[-1].ratio if self._ring else 0.0

    @property
    def total_drift(self) -> int:
        """Total divergence (ahead + behind) from the latest measurement."""
        return self._ring[-1].total if self._ring else 0

    @property
    def alert(self) -> str:
        """Current alert level based on the latest measurement.

        Returns
        -------
        str
            One of ``NONE``, ``WATCH``, or ``PULL_NOW``.
        """
        if not self._ring:
            return NONE
        snap = self._ring[-1]
        if snap.behind >= self.pull_now_behind or snap.ratio >= self.pull_now_ratio:
            return PULL_NOW
        if snap.behind >= self.watch_behind or snap.ratio >= self.watch_ratio:
            return WATCH
        return NONE

    @property
    def trend(self) -> str:
        """Direction of drift change between the last two measurements.

        Returns
        -------
        str
            ``GROWING``, ``STABLE``, or ``SHRINKING``.  Returns ``STABLE``
            if fewer than two measurements exist.
        """
        if len(self._ring) < 2:
            return STABLE
        prev_total = self._ring[-2].total
        curr_total = self._ring[-1].total
        diff = curr_total - prev_total
        if diff > 0:
            return GROWING
        if diff < 0:
            return SHRINKING
        return STABLE

    @property
    def peak_behind(self) -> int:
        """Highest ``behind`` value ever recorded in the history ring."""
        if not self._ring:
            return 0
        return max(s.behind for s in self._ring)

    @property
    def avg_total(self) -> float:
        """Average total drift across all measurements in the ring."""
        if not self._ring:
            return 0.0
        return sum(s.total for s in self._ring) / len(self._ring)

    # ------------------------------------------------------------------
    # advice
    # ------------------------------------------------------------------

    def advise(self) -> str:
        """Return a human-readable recommendation based on current state.

        Returns
        -------
        str
            Actionable advice string.
        """
        if not self._ring:
            return "no data yet — run a fetch to establish baseline"

        level = self.alert
        snap = self._ring[-1]

        if level == NONE:
            if snap.ahead > 0:
                return f"clean: {snap.ahead} commit(s) queued for push"
            return "synced — nothing to do"

        if level == WATCH:
            return (
                f"watch: remote is {snap.behind} ahead, "
                f"ratio {snap.ratio:.1f} — consider pulling soon"
            )

        # PULL_NOW
        if snap.behind > 0 and snap.ahead > 0:
            return (
                f"pull now: {snap.behind} remote commit(s) diverged from "
                f"{snap.ahead} local — rebase before pushing"
            )
        if snap.behind > 0:
            return (
                f"pull now: {snap.behind} remote commit(s) un-pulled — "
                f"fast-forward merge should suffice"
            )
        return "pull now: drift critical"
