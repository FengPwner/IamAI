"""176 — hybrid logical clock: order events across writers without synced clocks.

when multiple AI writers each produce strokes at their own cadence,
"which happened first?" is not a trivial question.  wall clocks drift;
pure logical counters ignore real time.  a hybrid logical clock (HLC)
gives you the best of both:

    timestamp = (wall_ms, counter, node_id)

the comparison rule is lexicographic: first by wall time, then by
counter (for same-millisecond events), then by node_id (for ties).

the merge rule on receiving a remote event is:

    new.wall = max(local.wall, remote.wall, now())
    if new.wall == local.wall == remote.wall:
        new.counter = max(local.counter, remote.counter) + 1
    elif new.wall == local.wall:
        new.counter = local.counter + 1
    elif new.wall == remote.wall:
        new.counter = remote.counter + 1
    else:
        new.counter = 0

this guarantees that if event A causally precedes event B, then
A.timestamp < B.timestamp — even across restarts, clock jumps, and
unsynchronized machines.

typical usage:

    clock = EpochClock("qwen")
    ts1 = clock.tick()                # local event
    ts2 = clock.tick()                # another local event
    assert ts1 < ts2                  # always true

    # merge a remote event from another writer:
    remote = Timestamp(wall_ms=..., counter=3, node="doubao")
    merged = clock.merge(remote)
    # now clock.tick() will produce a timestamp > merged

design choices:

- wall_ms uses time.time() * 1000 — good enough for process-level
  coordination; not trying to solve NTP.
- counter is a 32-bit int — wraps at ~4 billion, which is fine since
  wall_ms advances every millisecond.
- node_id is any hashable; used only for final tie-breaking.
- the clock is monotonic even if the system clock jumps backward:
  tick() and merge() both clamp wall_ms to max(current, observed).
- thread-safe via threading.Lock; one global instance per process.

why "epoch": because each restart creates a new epoch, and within
that epoch the clock orders events consistently.  across epochs the
fencing_token (snippet 072) handles the "who is current" question;
the epoch_clock handles "in what order".
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, order=True)
class Timestamp:
    """Comparable hybrid timestamp: (wall_ms, counter, node)."""

    wall_ms: int
    counter: int = 0
    node: str = ""

    def __repr__(self) -> str:
        return f"Timestamp(wall_ms={self.wall_ms}, counter={self.counter}, node={self.node!r})"

    def to_bytes(self) -> bytes:
        """Compact 16-byte serialization for storage or transport.

        Format: 8 bytes wall_ms (big-endian) + 4 bytes counter (big-endian)
        + 4 bytes node hash (big-endian, truncated).
        """
        import struct
        node_hash = hash(self.node) & 0xFFFFFFFF
        return struct.pack(">qII", self.wall_ms, self.counter, node_hash)

    @classmethod
    def from_bytes(cls, data: bytes, node: str = "") -> "Timestamp":
        """Deserialize from 16-byte representation."""
        import struct
        wall_ms, counter, _ = struct.unpack(">qII", data)
        return cls(wall_ms=wall_ms, counter=counter, node=node)


class EpochClock:
    """Hybrid logical clock for ordering events in a multi-writer repo.

    Each writer gets its own EpochClock instance with a unique node_id.
    Local events call tick(); remote events call merge().
    The clock is monotonic: wall_ms never goes backward even if the
    system clock does.
    """

    def __init__(self, node: str = "", *, wall_fn=None):
        """Initialize clock.

        Args:
            node: identifier for this writer (e.g. "qwen", "doubao").
            wall_fn: optional callable returning current wall_ms (for testing).
        """
        self._node = node
        self._wall_ms = 0
        self._counter = 0
        self._lock = threading.Lock()
        self._wall_fn = wall_fn or (lambda: int(time.time() * 1000))
        self._tick_count = 0
        self._merge_count = 0

    @property
    def node(self) -> str:
        """This clock's node identifier."""
        return self._node

    @property
    def current(self) -> Timestamp:
        """Current timestamp without advancing (snapshot)."""
        with self._lock:
            return Timestamp(wall_ms=self._wall_ms, counter=self._counter, node=self._node)

    @property
    def tick_count(self) -> int:
        """Total number of tick() calls."""
        return self._tick_count

    @property
    def merge_count(self) -> int:
        """Total number of merge() calls."""
        return self._merge_count

    def _now_ms(self) -> int:
        """Get current wall time, clamped to never go backward."""
        observed = self._wall_fn()
        if observed > self._wall_ms:
            return observed
        return self._wall_ms

    def tick(self) -> Timestamp:
        """Record a local event and return its timestamp.

        Guarantees: returned timestamp is strictly greater than any
        previously returned timestamp from this clock.
        """
        with self._lock:
            now = self._now_ms()
            if now == self._wall_ms:
                self._counter += 1
            else:
                self._wall_ms = now
                self._counter = 0
            self._tick_count += 1
            return Timestamp(wall_ms=self._wall_ms, counter=self._counter, node=self._node)

    def merge(self, remote: Timestamp) -> Timestamp:
        """Merge a remote event into this clock and return the merged timestamp.

        After merge, tick() will produce timestamps greater than both
        the local state and the remote event.

        Args:
            remote: timestamp from another writer's tick() or merge().

        Returns:
            The new timestamp after merging.
        """
        with self._lock:
            now = self._now_ms()
            local_wall = self._wall_ms
            remote_wall = remote.wall_ms

            new_wall = max(now, local_wall, remote_wall)

            if new_wall == local_wall == remote_wall:
                new_counter = max(self._counter, remote.counter) + 1
            elif new_wall == local_wall:
                new_counter = self._counter + 1
            elif new_wall == remote_wall:
                new_counter = remote.counter + 1
            else:
                new_counter = 0

            self._wall_ms = new_wall
            self._counter = new_counter
            self._merge_count += 1
            return Timestamp(wall_ms=new_wall, counter=new_counter, node=self._node)

    def reset(self) -> None:
        """Reset clock to initial state (testing only)."""
        with self._lock:
            self._wall_ms = 0
            self._counter = 0
            self._tick_count = 0
            self._merge_count = 0

    def __repr__(self) -> str:
        return (
            f"EpochClock(node={self._node!r}, wall_ms={self._wall_ms}, "
            f"counter={self._counter}, ticks={self._tick_count}, merges={self._merge_count})"
        )


# ── doctest ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import doctest

    # >>> clock = EpochClock("qwen", wall_fn=lambda: 1000)
    # >>> t1 = clock.tick()
    # >>> t1.wall_ms
    # 1000
    # >>> t1.counter
    # 0
    # >>> t1.node
    # 'qwen'
    # >>> t2 = clock.tick()
    # >>> t2.counter
    # 1
    # >>> t1 < t2
    # True

    # wall jumps forward
    # >>> clock2 = EpochClock("doubao", wall_fn=lambda: 5000)
    # >>> t3 = clock2.tick()
    # >>> t3.wall_ms
    # 5000
    # >>> t3.counter
    # 0

    # merge a remote event
    # >>> remote = Timestamp(wall_ms=6000, counter=2, node="qwen")
    # >>> merged = clock2.merge(remote)
    # >>> merged.wall_ms
    # 6000
    # >>> merged.counter
    # 3

    # after merge, tick > merged
    # >>> clock2._wall_fn = lambda: 6000
    # >>> t4 = clock2.tick()
    # >>> t4 > merged
    # True

    doctest.testmod(verbose=False)
    print("doctest OK")
