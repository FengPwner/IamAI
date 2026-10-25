"""Tests for snippets/epoch_clock.py — hybrid logical clock."""

import threading
import time

import pytest

from snippets.epoch_clock import EpochClock, Timestamp


# ── Timestamp ────────────────────────────────────────────────────────


class TestTimestamp:
    def test_ordering_same_wall(self):
        t1 = Timestamp(wall_ms=100, counter=0, node="a")
        t2 = Timestamp(wall_ms=100, counter=1, node="a")
        assert t1 < t2

    def test_ordering_different_wall(self):
        t1 = Timestamp(wall_ms=99, counter=5, node="a")
        t2 = Timestamp(wall_ms=100, counter=0, node="a")
        assert t1 < t2

    def test_ordering_node_tiebreak(self):
        t1 = Timestamp(wall_ms=100, counter=0, node="a")
        t2 = Timestamp(wall_ms=100, counter=0, node="b")
        assert t1 < t2

    def test_equality(self):
        t1 = Timestamp(wall_ms=100, counter=0, node="a")
        t2 = Timestamp(wall_ms=100, counter=0, node="a")
        assert t1 == t2

    def test_repr(self):
        t = Timestamp(wall_ms=100, counter=2, node="qwen")
        assert "100" in repr(t)
        assert "qwen" in repr(t)

    def test_to_bytes_roundtrip(self):
        t = Timestamp(wall_ms=123456789, counter=42, node="qwen")
        data = t.to_bytes()
        assert len(data) == 16
        t2 = Timestamp.from_bytes(data, node="qwen")
        assert t2.wall_ms == t.wall_ms
        assert t2.counter == t.counter

    def test_from_bytes_different_node_label(self):
        t = Timestamp(wall_ms=500, counter=3, node="doubao")
        data = t.to_bytes()
        t2 = Timestamp.from_bytes(data, node="kimi")
        assert t2.wall_ms == 500
        assert t2.counter == 3
        assert t2.node == "kimi"

    def test_frozen(self):
        t = Timestamp(wall_ms=100, counter=0, node="a")
        with pytest.raises(AttributeError):
            t.wall_ms = 200


# ── EpochClock construction ──────────────────────────────────────────


class TestEpochClockConstruction:
    def test_defaults(self):
        c = EpochClock("qwen")
        assert c.node == "qwen"
        assert c.tick_count == 0
        assert c.merge_count == 0

    def test_custom_wall_fn(self):
        c = EpochClock("test", wall_fn=lambda: 9999)
        t = c.tick()
        assert t.wall_ms == 9999

    def test_repr(self):
        c = EpochClock("qwen")
        r = repr(c)
        assert "qwen" in r
        assert "EpochClock" in r


# ── tick ─────────────────────────────────────────────────────────────


class TestEpochClockTick:
    def test_first_tick(self):
        wall = [1000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        t = c.tick()
        assert t.wall_ms == 1000
        assert t.counter == 0
        assert t.node == "qwen"

    def test_consecutive_same_ms(self):
        wall = [1000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        t1 = c.tick()
        t2 = c.tick()
        t3 = c.tick()
        assert t1.wall_ms == 1000
        assert t2.wall_ms == 1000
        assert t3.wall_ms == 1000
        assert t1.counter == 0
        assert t2.counter == 1
        assert t3.counter == 2

    def test_strictly_increasing(self):
        wall = [1000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        timestamps = [c.tick() for _ in range(50)]
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i - 1]

    def test_wall_advances(self):
        wall = [1000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        t1 = c.tick()
        wall[0] = 2000
        t2 = c.tick()
        assert t2.wall_ms == 2000
        assert t2.counter == 0
        assert t2 > t1

    def test_wall_never_goes_backward(self):
        wall = [5000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        t1 = c.tick()
        assert t1.wall_ms == 5000
        wall[0] = 3000  # clock jumped backward
        t2 = c.tick()
        assert t2.wall_ms == 5000  # clamped to previous
        assert t2 > t1  # still strictly increasing

    def test_tick_count(self):
        c = EpochClock("qwen", wall_fn=lambda: 1000)
        assert c.tick_count == 0
        c.tick()
        assert c.tick_count == 1
        c.tick()
        c.tick()
        assert c.tick_count == 3

    def test_node_in_timestamp(self):
        c = EpochClock("doubao", wall_fn=lambda: 100)
        t = c.tick()
        assert t.node == "doubao"


# ── merge ────────────────────────────────────────────────────────────


class TestEpochClockMerge:
    def test_merge_future_remote(self):
        c = EpochClock("qwen", wall_fn=lambda: 1000)
        c.tick()  # wall_ms=1000, counter=0
        remote = Timestamp(wall_ms=5000, counter=3, node="doubao")
        merged = c.merge(remote)
        assert merged.wall_ms == 5000
        assert merged.counter == 4

    def test_merge_past_remote(self):
        c = EpochClock("qwen", wall_fn=lambda: 5000)
        c.tick()  # wall_ms=5000, counter=0
        remote = Timestamp(wall_ms=1000, counter=99, node="doubao")
        merged = c.merge(remote)
        # local wall > remote wall, so wall stays at 5000
        assert merged.wall_ms == 5000
        assert merged.counter == 1  # local_counter + 1

    def test_merge_same_wall(self):
        wall = [3000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        c.tick()  # wall_ms=3000, counter=0
        remote = Timestamp(wall_ms=3000, counter=5, node="doubao")
        merged = c.merge(remote)
        assert merged.wall_ms == 3000
        assert merged.counter == 6  # max(0, 5) + 1

    def test_merge_then_tick(self):
        wall = [3000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        c.tick()
        remote = Timestamp(wall_ms=5000, counter=2, node="doubao")
        merged = c.merge(remote)
        t = c.tick()
        assert t > merged

    def test_merge_count(self):
        c = EpochClock("qwen", wall_fn=lambda: 1000)
        assert c.merge_count == 0
        c.merge(Timestamp(wall_ms=2000, counter=0, node="x"))
        assert c.merge_count == 1
        c.merge(Timestamp(wall_ms=3000, counter=0, node="x"))
        assert c.merge_count == 2

    def test_causal_order_preserved(self):
        """If A.tick() → B.merge(A's ts) → B.tick(), then A.ts < B.ts."""
        wall_a = [1000]
        wall_b = [1000]
        a = EpochClock("a", wall_fn=lambda: wall_a[0])
        b = EpochClock("b", wall_fn=lambda: wall_b[0])

        ts_a = a.tick()
        merged = b.merge(ts_a)
        ts_b = b.tick()
        assert ts_a < merged < ts_b

    def test_bidirectional_merge(self):
        """Two clocks exchange events; all timestamps stay ordered."""
        a = EpochClock("a", wall_fn=lambda: 1000)
        b = EpochClock("b", wall_fn=lambda: 1000)

        ta1 = a.tick()
        tb1 = b.merge(ta1)
        tb2 = b.tick()
        ta2 = a.merge(tb2)

        assert ta1 < tb1
        assert tb1 < tb2
        assert tb2 < ta2


# ── current (snapshot) ──────────────────────────────────────────────


class TestEpochClockCurrent:
    def test_before_any_tick(self):
        c = EpochClock("qwen")
        s = c.current
        assert s.wall_ms == 0
        assert s.counter == 0

    def test_after_tick(self):
        c = EpochClock("qwen", wall_fn=lambda: 7777)
        c.tick()
        s = c.current
        assert s.wall_ms == 7777
        assert s.counter == 0

    def test_does_not_advance(self):
        c = EpochClock("qwen", wall_fn=lambda: 1000)
        c.tick()
        s1 = c.current
        s2 = c.current
        assert s1 == s2
        assert c.tick_count == 1  # current doesn't count as tick


# ── reset ────────────────────────────────────────────────────────────


class TestEpochClockReset:
    def test_reset_clears_state(self):
        c = EpochClock("qwen", wall_fn=lambda: 1000)
        c.tick()
        c.merge(Timestamp(wall_ms=2000, counter=0, node="x"))
        c.reset()
        assert c.tick_count == 0
        assert c.merge_count == 0
        s = c.current
        assert s.wall_ms == 0
        assert s.counter == 0

    def test_reset_then_tick(self):
        c = EpochClock("qwen", wall_fn=lambda: 5000)
        c.tick()
        c.reset()
        t = c.tick()
        assert t.wall_ms == 5000
        assert t.counter == 0


# ── thread safety ────────────────────────────────────────────────────


class TestEpochClockThreadSafety:
    def test_concurrent_tick(self):
        """Multiple threads calling tick() produce unique, ordered timestamps."""
        wall = [1000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])
        results = []
        lock = threading.Lock()

        def tick_n(n):
            local = []
            for _ in range(n):
                local.append(c.tick())
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=tick_n, args=(100,)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 800
        # all unique
        assert len(set(results)) == 800
        # total ticks
        assert c.tick_count == 800

    def test_concurrent_merge(self):
        """Concurrent merges don't corrupt state."""
        c = EpochClock("qwen", wall_fn=lambda: 1000)
        c.tick()

        remotes = [
            Timestamp(wall_ms=1000 + i, counter=i, node=f"node-{i}")
            for i in range(200)
        ]

        def merge_batch(batch):
            for r in batch:
                c.merge(r)

        chunks = [remotes[i::4] for i in range(4)]
        threads = [threading.Thread(target=merge_batch, args=(chunk,)) for chunk in chunks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.merge_count == 200


# ── integration scenario ─────────────────────────────────────────────


class TestEpochClockIntegration:
    def test_multi_writer_session(self):
        """Simulate a session with 3 writers exchanging events."""
        writers = {
            "qwen": EpochClock("qwen", wall_fn=lambda: 10000),
            "doubao": EpochClock("doubao", wall_fn=lambda: 10000),
            "kimi": EpochClock("kimi", wall_fn=lambda: 10000),
        }

        all_ts = []

        # each writer produces 3 events
        for name, clock in writers.items():
            for _ in range(3):
                ts = clock.tick()
                all_ts.append(ts)

        # each writer merges all others' events
        for name, clock in writers.items():
            for ts in all_ts:
                if ts.node != name:
                    clock.merge(ts)

        # each writer produces one more event
        for name, clock in writers.items():
            ts = clock.tick()
            all_ts.append(ts)

        # verify all timestamps from same writer are ordered
        for name in writers:
            writer_ts = [t for t in all_ts if t.node == name]
            for i in range(1, len(writer_ts)):
                assert writer_ts[i] > writer_ts[i - 1]

    def test_clock_jump_recovery(self):
        """System clock jumps forward then backward; clock stays monotonic."""
        wall = [10000]
        c = EpochClock("qwen", wall_fn=lambda: wall[0])

        t1 = c.tick()
        assert t1.wall_ms == 10000

        wall[0] = 50000  # big jump forward
        t2 = c.tick()
        assert t2.wall_ms == 50000

        wall[0] = 5000  # jump backward (NTP correction)
        t3 = c.tick()
        assert t3.wall_ms == 50000  # clamped
        assert t3 > t2

        wall[0] = 60000  # normal advance
        t4 = c.tick()
        assert t4.wall_ms == 60000
        assert t4 > t3
