"""060 — cooldown: refuse repeated actions within a time window.

restart loops, push retries, notification spam — they all share one problem:
after the first attempt you need to *wait* before trying again, and "wait"
is the thing every hot loop forgets to do. a sentinel tells you *when* to
fire; a cooldown tells you *when not to*.

cooldown wraps an action with a minimum interval. calling `try_acquire()`
returns True the first time, then False until the window expires. no threads,
no clocks injected — it reads `time.monotonic()` so wall-clock jumps (NTP,
DST, leap seconds) never shorten or stretch the gap.

    try_acquire() → True    (first call, action proceeds)
    try_acquire() → False   (still inside the window)
    try_acquire() → False   (still inside)
    ... window elapses ...
    try_acquire() → True    (new window opens)

optional `force()` bypasses the gate for emergencies — use it when the
caretaker decides that waiting is more dangerous than acting twice.

`remaining()` tells you how many seconds are left, handy for log messages
and back-off displays.

zero dependencies. stdlib only.

>>> import time
>>> c = Cooldown(seconds=0.1)
>>> c.try_acquire()
True
>>> c.try_acquire()
False
>>> c.remaining() > 0
True
>>> time.sleep(0.11)
>>> c.try_acquire()
True

>>> c2 = Cooldown(seconds=60)
>>> c2.try_acquire()
True
>>> c2.force()
>>> c2.try_acquire()
True
"""

from __future__ import annotations

import time


class Cooldown:
    """Minimum-interval gate: one acquire per window, monotonic clock."""

    def __init__(self, seconds: float):
        if seconds < 0:
            raise ValueError(f"cooldown window must be >= 0, got {seconds}")
        self._window = seconds
        self._last: float = -float("inf")
        self._acquire_count = 0

    @property
    def window(self) -> float:
        """The configured cooldown window in seconds."""
        return self._window

    @property
    def acquire_count(self) -> int:
        """Total successful acquires (including forced)."""
        return self._acquire_count

    def try_acquire(self) -> bool:
        """Return True if the cooldown has elapsed and the action may proceed."""
        now = time.monotonic()
        if now - self._last >= self._window:
            self._last = now
            self._acquire_count += 1
            return True
        return False

    def force(self) -> None:
        """Reset the timer so the next try_acquire() succeeds immediately."""
        self._last = -float("inf")

    def remaining(self) -> float:
        """Seconds until the next acquire will succeed (0.0 if ready now)."""
        elapsed = time.monotonic() - self._last
        left = self._window - elapsed
        return max(0.0, left)

    def __repr__(self) -> str:
        state = "ready" if self.remaining() == 0.0 else f"{self.remaining():.1f}s left"
        return f"Cooldown(window={self._window}s, {state}, acquires={self._acquire_count})"
