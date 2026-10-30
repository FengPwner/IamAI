"""Tests for snippets/fencing_token.py — defeat zombie writers."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from fencing_token import FencingEpoch, StaleTokenError  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestInit:
    def test_initial_current_is_zero(self):
        e = FencingEpoch()
        assert e.current == 0

    def test_initial_advances_zero(self):
        e = FencingEpoch()
        assert e.total_advances == 0

    def test_initial_stale_zero(self):
        e = FencingEpoch()
        assert e.stale_count() == 0

    def test_initial_history_empty(self):
        e = FencingEpoch()
        assert e.history() == []

    def test_repr_initial(self):
        e = FencingEpoch()
        assert "current=0" in repr(e)


# ---------------------------------------------------------------------------
# advance
# ---------------------------------------------------------------------------


class TestAdvance:
    def test_first_advance_returns_one(self):
        e = FencingEpoch()
        assert e.advance() == 1

    def test_monotonic_increase(self):
        e = FencingEpoch()
        tokens = [e.advance() for _ in range(10)]
        assert tokens == list(range(1, 11))

    def test_current_updates(self):
        e = FencingEpoch()
        t = e.advance()
        assert e.current == t

    def test_total_advances_increments(self):
        e = FencingEpoch()
        e.advance()
        e.advance()
        e.advance()
        assert e.total_advances == 3

    def test_history_records_tokens(self):
        e = FencingEpoch()
        e.advance()
        e.advance()
        assert e.history() == [1, 2]

    def test_history_bounded_at_64(self):
        e = FencingEpoch()
        for _ in range(100):
            e.advance()
        assert len(e.history()) == 64
        assert e.history()[-1] == 100
        assert e.history()[0] == 37  # 100 - 63

    def test_each_advance_invalidates_previous(self):
        e = FencingEpoch()
        t1 = e.advance()
        assert e.check(t1) is True
        t2 = e.advance()
        assert e.check(t1) is False
        assert e.check(t2) is True


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


class TestCheck:
    def test_current_token_passes(self):
        e = FencingEpoch()
        t = e.advance()
        assert e.check(t) is True

    def test_old_token_fails(self):
        e = FencingEpoch()
        t1 = e.advance()
        e.advance()
        assert e.check(t1) is False

    def test_zero_token_before_advance(self):
        e = FencingEpoch()
        # token 0 before any advance: not stale, just not valid
        assert e.check(0) is False

    def test_negative_token(self):
        e = FencingEpoch()
        e.advance()
        assert e.check(-1) is False

    def test_future_token(self):
        e = FencingEpoch()
        e.advance()
        assert e.check(999) is False

    def test_stale_count_increments(self):
        e = FencingEpoch()
        t1 = e.advance()
        e.advance()
        e.check(t1)  # stale
        e.check(t1)  # stale again
        assert e.stale_count() == 2

    def test_stale_not_counted_for_zero(self):
        e = FencingEpoch()
        e.check(0)
        assert e.stale_count() == 0

    def test_valid_check_not_stale(self):
        e = FencingEpoch()
        t = e.advance()
        e.check(t)
        e.check(t)
        assert e.stale_count() == 0


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


class TestGuard:
    def test_valid_token_passes(self):
        e = FencingEpoch()
        t = e.advance()
        e.guard(t)  # no exception

    def test_stale_token_raises(self):
        e = FencingEpoch()
        t1 = e.advance()
        e.advance()
        with pytest.raises(StaleTokenError, match="stale token 1"):
            e.guard(t1)

    def test_error_message_includes_current(self):
        e = FencingEpoch()
        t1 = e.advance()
        e.advance()
        with pytest.raises(StaleTokenError, match="current is 2"):
            e.guard(t1)

    def test_zero_token_raises(self):
        e = FencingEpoch()
        e.advance()
        with pytest.raises(StaleTokenError):
            e.guard(0)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_returns_zero(self):
        e = FencingEpoch()
        e.advance()
        assert e.reset() == 0

    def test_reset_clears_current(self):
        e = FencingEpoch()
        e.advance()
        e.reset()
        assert e.current == 0

    def test_reset_clears_advances(self):
        e = FencingEpoch()
        e.advance()
        e.advance()
        e.reset()
        assert e.total_advances == 0

    def test_reset_clears_stale(self):
        e = FencingEpoch()
        t1 = e.advance()
        e.advance()
        e.check(t1)
        e.reset()
        assert e.stale_count() == 0

    def test_reset_clears_history(self):
        e = FencingEpoch()
        e.advance()
        e.reset()
        assert e.history() == []

    def test_advance_after_reset(self):
        e = FencingEpoch()
        e.advance()
        e.advance()
        e.reset()
        t = e.advance()
        assert t == 1
        assert e.current == 1


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_after_advance(self):
        e = FencingEpoch()
        e.advance()
        r = repr(e)
        assert "current=1" in r
        assert "advances=1" in r

    def test_repr_after_stale(self):
        e = FencingEpoch()
        t1 = e.advance()
        e.advance()
        e.check(t1)
        r = repr(e)
        assert "stale=1" in r


# ---------------------------------------------------------------------------
# thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_advances(self):
        e = FencingEpoch()
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            for _ in range(100):
                results.append(e.advance())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # all tokens must be unique
        assert len(set(results)) == 800
        assert e.total_advances == 800
        assert e.current == 800

    def test_concurrent_checks(self):
        e = FencingEpoch()
        t = e.advance()
        errors = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            for _ in range(500):
                try:
                    result = e.check(t)
                    assert result is True
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t_ in threads:
            t_.start()
        for t_ in threads:
            t_.join()

        assert errors == []


# ---------------------------------------------------------------------------
# integration: zombie writer scenario
# ---------------------------------------------------------------------------


class TestZombieWriterScenario:
    def test_full_lifecycle(self):
        """Simulate container recycle: old writer tries to write after
        new writer has taken over."""
        epoch = FencingEpoch()

        # epoch 1: original writer starts
        writer1_token = epoch.advance()
        assert epoch.check(writer1_token) is True

        # writer1 produces 5 strokes successfully
        for _ in range(5):
            epoch.guard(writer1_token)

        # container killed! new container starts
        writer2_token = epoch.advance()
        assert writer2_token > writer1_token

        # zombie writer1 wakes up and tries to write
        with pytest.raises(StaleTokenError):
            epoch.guard(writer1_token)

        # new writer2 operates normally
        epoch.guard(writer2_token)
        assert epoch.stale_count() == 1

    def test_multi_recycle(self):
        """Multiple container recycles in sequence."""
        epoch = FencingEpoch()
        tokens = []

        for _ in range(10):
            tokens.append(epoch.advance())

        # only the last token is valid
        for t in tokens[:-1]:
            assert epoch.check(t) is False

        assert epoch.check(tokens[-1]) is True
        assert epoch.total_advances == 10
        # 9 stale checks
        assert epoch.stale_count() == 9

    def test_writer_handoff_pattern(self):
        """Two writers, clean handoff, no zombie writes."""
        epoch = FencingEpoch()

        # writer A
        token_a = epoch.advance()
        epoch.guard(token_a)
        epoch.guard(token_a)

        # clean handoff (writer A stops before B starts)
        token_b = epoch.advance()
        epoch.guard(token_b)

        # no stale attempts
        assert epoch.stale_count() == 0
        assert epoch.total_advances == 2
