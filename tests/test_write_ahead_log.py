"""Tests for snippets/write_ahead_log.py — crash-safe write-ahead log."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from write_ahead_log import Status, WriteAheadLog  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestInit:
    def test_empty_wal(self):
        wal = WriteAheadLog()
        assert len(wal) == 0
        assert wal.pending() == []
        assert wal.recover() == []

    def test_initial_stats(self):
        wal = WriteAheadLog()
        s = wal.stats()
        assert s["pending"] == 0
        assert s["committed"] == 0
        assert s["checkpointed"] == 0
        assert s["total"] == 0


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


class TestAppend:
    def test_returns_monotonic_lsn(self):
        wal = WriteAheadLog()
        assert wal.append("a") == 1
        assert wal.append("b") == 2
        assert wal.append("c") == 3

    def test_pending_after_append(self):
        wal = WriteAheadLog()
        wal.append("a")
        wal.append("b")
        assert wal.pending() == [1, 2]

    def test_data_stored_correctly(self):
        wal = WriteAheadLog()
        lsn = wal.append({"stroke": "hello", "idx": 42})
        assert wal.get(lsn) == {"stroke": "hello", "idx": 42}

    def test_append_none_data(self):
        wal = WriteAheadLog()
        lsn = wal.append(None)
        assert wal.get(lsn) is None

    def test_append_various_types(self):
        wal = WriteAheadLog()
        lsn_int = wal.append(42)
        lsn_list = wal.append([1, 2, 3])
        lsn_bytes = wal.append(b"raw bytes")
        assert wal.get(lsn_int) == 42
        assert wal.get(lsn_list) == [1, 2, 3]
        assert wal.get(lsn_bytes) == b"raw bytes"

    def test_len_increments(self):
        wal = WriteAheadLog()
        assert len(wal) == 0
        wal.append("a")
        assert len(wal) == 1
        wal.append("b")
        assert len(wal) == 2


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


class TestCommit:
    def test_commit_moves_to_committed(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        wal.commit(lsn)
        assert wal.status(lsn) == "committed"
        assert lsn not in wal.pending()
        assert lsn in wal.recover()

    def test_commit_idempotent(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        wal.commit(lsn)
        wal.commit(lsn)  # no-op
        assert wal.status(lsn) == "committed"
        assert wal.stats()["committed"] == 1

    def test_commit_already_checkpointed_is_noop(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        wal.commit(lsn)
        wal.checkpoint(lsn)
        wal.commit(lsn)  # no-op, stays checkpointed
        assert wal.status(lsn) == "checkpointed"

    def test_commit_unknown_lsn_raises(self):
        wal = WriteAheadLog()
        with pytest.raises(KeyError):
            wal.commit(999)

    def test_commit_partial(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        c = wal.append("c")
        wal.commit(a)
        wal.commit(c)
        assert wal.pending() == [b]
        assert wal.recover() == [a, c]


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_checkpoint_single(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        wal.commit(lsn)
        count = wal.checkpoint(lsn)
        assert count == 1
        assert wal.status(lsn) == "checkpointed"

    def test_checkpoint_removes_from_recover(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        wal.commit(lsn)
        assert wal.recover() == [lsn]
        wal.checkpoint(lsn)
        assert wal.recover() == []

    def test_checkpoint_all_committed(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        wal.commit(b)
        count = wal.checkpoint()
        assert count == 2
        assert wal.stats()["checkpointed"] == 2

    def test_checkpoint_skips_pending(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        # b is still pending
        count = wal.checkpoint()
        assert count == 1
        assert wal.status(a) == "checkpointed"
        assert wal.status(b) == "pending"

    def test_checkpoint_idempotent(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        wal.commit(lsn)
        assert wal.checkpoint(lsn) == 1
        assert wal.checkpoint(lsn) == 0

    def test_checkpoint_all_idempotent(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        wal.commit(a)
        wal.checkpoint()
        assert wal.checkpoint() == 0

    def test_checkpoint_pending_raises(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        with pytest.raises(ValueError, match="still pending"):
            wal.checkpoint(lsn)

    def test_checkpoint_unknown_lsn_raises(self):
        wal = WriteAheadLog()
        with pytest.raises(KeyError):
            wal.checkpoint(999)


# ---------------------------------------------------------------------------
# recovery
# ---------------------------------------------------------------------------


class TestRecovery:
    def test_empty_wal_recovers_nothing(self):
        wal = WriteAheadLog()
        assert wal.recover() == []

    def test_recover_returns_committed_only(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        c = wal.append("c")
        wal.commit(a)
        wal.commit(c)
        # b is pending, should not appear
        assert wal.recover() == [a, c]

    def test_recover_sorted_by_lsn(self):
        wal = WriteAheadLog()
        lsns = [wal.append(f"item-{i}") for i in range(10)]
        # commit in reverse order
        for lsn in reversed(lsns):
            wal.commit(lsn)
        assert wal.recover() == sorted(lsns)

    def test_recover_after_checkpoint(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        wal.commit(b)
        wal.checkpoint(a)
        assert wal.recover() == [b]


# ---------------------------------------------------------------------------
# pending
# ---------------------------------------------------------------------------


class TestPending:
    def test_all_pending_initially(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        assert wal.pending() == [a, b]

    def test_pending_after_commit(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        assert wal.pending() == [b]

    def test_pending_after_checkpoint(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        wal.checkpoint(a)
        assert wal.pending() == [b]

    def test_pending_sorted(self):
        wal = WriteAheadLog()
        lsns = [wal.append(f"i{i}") for i in range(5)]
        assert wal.pending() == sorted(lsns)


# ---------------------------------------------------------------------------
# get / status / contains
# ---------------------------------------------------------------------------


class TestQueries:
    def test_get_returns_data(self):
        wal = WriteAheadLog()
        lsn = wal.append("payload")
        assert wal.get(lsn) == "payload"

    def test_get_unknown_raises(self):
        wal = WriteAheadLog()
        with pytest.raises(KeyError):
            wal.get(42)

    def test_status_transitions(self):
        wal = WriteAheadLog()
        lsn = wal.append("work")
        assert wal.status(lsn) == "pending"
        wal.commit(lsn)
        assert wal.status(lsn) == "committed"
        wal.checkpoint(lsn)
        assert wal.status(lsn) == "checkpointed"

    def test_status_unknown_raises(self):
        wal = WriteAheadLog()
        with pytest.raises(KeyError):
            wal.status(999)

    def test_contains(self):
        wal = WriteAheadLog()
        lsn = wal.append("x")
        assert lsn in wal
        assert 999 not in wal

    def test_contains_after_prune(self):
        wal = WriteAheadLog()
        lsn = wal.append("x")
        wal.commit(lsn)
        wal.checkpoint(lsn)
        wal.prune()
        assert lsn not in wal


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_counts_accurate(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        c = wal.append("c")
        d = wal.append("d")
        wal.commit(a)
        wal.commit(b)
        wal.commit(c)
        wal.checkpoint(a)
        s = wal.stats()
        assert s["pending"] == 1      # d
        assert s["committed"] == 2    # b, c
        assert s["checkpointed"] == 1  # a
        assert s["total"] == 4

    def test_stats_after_prune(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        wal.commit(b)
        wal.checkpoint()
        wal.prune()
        s = wal.stats()
        assert s["total"] == 0
        assert s["pending"] == 0
        assert s["committed"] == 0
        assert s["checkpointed"] == 0


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


class TestPrune:
    def test_prune_removes_checkpointed(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        wal.commit(b)
        wal.checkpoint(a)
        removed = wal.prune()
        assert removed == 1
        assert len(wal) == 1
        assert b in wal
        assert a not in wal

    def test_prune_nothing(self):
        wal = WriteAheadLog()
        wal.append("a")  # pending, not checkpointed
        assert wal.prune() == 0

    def test_prune_all_checkpointed(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        wal.commit(b)
        wal.checkpoint()
        removed = wal.prune()
        assert removed == 2
        assert len(wal) == 0

    def test_prune_preserves_non_checkpointed(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        c = wal.append("c")
        wal.commit(a)
        wal.commit(b)
        wal.checkpoint(a)
        wal.prune()
        assert a not in wal
        assert b in wal  # committed but not checkpointed
        assert c in wal  # pending


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_format(self):
        wal = WriteAheadLog()
        r = repr(wal)
        assert "WriteAheadLog" in r
        assert "pending=0" in r

    def test_repr_with_entries(self):
        wal = WriteAheadLog()
        a = wal.append("a")
        b = wal.append("b")
        wal.commit(a)
        r = repr(wal)
        assert "pending=1" in r
        assert "committed=1" in r


# ---------------------------------------------------------------------------
# integration: crash recovery scenario
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_typical_recovery_flow(self):
        """Simulate a crash mid-batch and verify recovery."""
        wal = WriteAheadLog()

        # write 5 strokes
        lsns = [wal.append(f"stroke-{i}") for i in range(5)]

        # commit first 3 (they were applied before crash)
        for lsn in lsns[:3]:
            wal.commit(lsn)

        # checkpoint first 2 (they were persisted to main store)
        wal.checkpoint(lsns[0])
        wal.checkpoint(lsns[1])

        # --- CRASH ---

        # after restart: what needs replaying?
        to_replay = wal.recover()
        assert to_replay == [lsns[2]]  # committed but not checkpointed

        # what was lost entirely?
        lost = wal.pending()
        assert lost == lsns[3:]  # never committed

        # replay and checkpoint
        for lsn in to_replay:
            # ... apply wal.get(lsn) to main store ...
            wal.checkpoint(lsn)

        # now checkpoint everything committed
        assert wal.recover() == []

        # prune old entries
        wal.prune()
        # only the lost (pending) entries remain
        assert wal.pending() == lsns[3:]

    def test_full_lifecycle(self):
        """End-to-end: append → commit → checkpoint → prune."""
        wal = WriteAheadLog()

        # phase 1: produce
        batch = [wal.append(f"item-{i}") for i in range(10)]
        assert len(wal) == 10
        assert all(lsn in wal for lsn in batch)

        # phase 2: commit all
        for lsn in batch:
            wal.commit(lsn)
        assert wal.pending() == []
        assert wal.recover() == batch

        # phase 3: apply and checkpoint all
        wal.checkpoint()
        assert wal.recover() == []
        assert wal.stats()["checkpointed"] == 10

        # phase 4: prune
        removed = wal.prune()
        assert removed == 10
        assert len(wal) == 0


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_lsn_monotonic_after_prune(self):
        """LSNs keep increasing even after pruning old entries."""
        wal = WriteAheadLog()
        a = wal.append("a")
        wal.commit(a)
        wal.checkpoint(a)
        wal.prune()
        b = wal.append("b")
        assert b > a

    def test_large_batch(self):
        wal = WriteAheadLog()
        lsns = [wal.append(f"item-{i}") for i in range(1000)]
        assert len(wal) == 1000
        for lsn in lsns:
            wal.commit(lsn)
        assert len(wal.recover()) == 1000
        wal.checkpoint()
        assert wal.prune() == 1000
        assert len(wal) == 0

    def test_interleaved_operations(self):
        """Mix append/commit/checkpoint in realistic order."""
        wal = WriteAheadLog()
        a = wal.append("a")
        wal.commit(a)
        b = wal.append("b")
        wal.checkpoint(a)
        c = wal.append("c")
        wal.commit(b)
        wal.commit(c)
        assert wal.pending() == []
        assert wal.recover() == [b, c]
        assert wal.stats()["checkpointed"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
