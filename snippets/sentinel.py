"""059 — sentinel: fire exactly once when a condition flips.

the deadman switch tells you a process is dead. but knowing it *just* died —
the transition, not the steady state — is what triggers recovery. polling
`expired()` in a loop and acting on every True would restart the process
sixty times a minute. you need edge detection, not level detection.

sentinel wraps a boolean probe and fires its callback only on the rising
edge: the first check that returns True after a streak of False (or after
creation). it then latches until explicitly rearmed.

    check() → False   →  nothing
    check() → False   →  nothing
    check() → True    →  FIRE (callback invoked once)
    check() → True    →  nothing (latched)
    rearm()
    check() → True    →  FIRE again

the probe is any callable returning bool. the callback is optional — you
can poll `triggered` yourself if you prefer pull over push. both styles
live in the same object so tests can pick whichever reads better.

zero dependencies. stdlib only.

>>> s = Sentinel(probe=lambda: False)
>>> s.check()
False
>>> s.triggered
False

>>> s2 = Sentinel(probe=lambda: True, on_fire=lambda: print("fired"))
>>> s2.check()
fired
True
>>> s2.check()          # latched — no second fire
True
>>> s2.rearm()
>>> s2.check()
fired
True

>>> # counting transitions
>>> count = 0
>>> def inc():
...     global count
...     count += 1
>>> s3 = Sentinel(probe=lambda: True, on_fire=inc)
>>> s3.check(); s3.check(); s3.check()
True
True
True
>>> count
1
>>> s3.rearm(); s3.check()
True
>>> count
2
"""

from __future__ import annotations

from typing import Callable, Optional


class Sentinel:
    """Edge detector for a boolean probe: fires once per arm-fire cycle."""

    def __init__(
        self,
        probe: Callable[[], bool],
        on_fire: Optional[Callable[[], None]] = None,
    ):
        self._probe = probe
        self._on_fire = on_fire
        self._latched = False
        self._fire_count = 0

    @property
    def triggered(self) -> bool:
        """True if the sentinel has fired and not been rearmed."""
        return self._latched

    @property
    def fire_count(self) -> int:
        """Total number of times this sentinel has fired (across all arms)."""
        return self._fire_count

    def check(self) -> bool:
        """Run the probe. Fire callback on rising edge, then latch."""
        result = self._probe()
        if result and not self._latched:
            self._latched = True
            self._fire_count += 1
            if self._on_fire is not None:
                self._on_fire()
        return result

    def rearm(self) -> None:
        """Reset the latch so the next True probe fires again."""
        self._latched = False

    def __repr__(self) -> str:
        state = "triggered" if self._latched else "armed"
        return f"Sentinel(state={state}, fires={self._fire_count})"
