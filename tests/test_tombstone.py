"""Tests for snippets/tombstone.py — deletion markers for replication."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from tombstone import Tombstone, TombstoneStore  # noqa: E402


# ---------------------------------------------------------------------------
# Tombstone dataclass
# ---------------------------------------------------------------------------


def test_tombstone_deleted_is_true():
    t = Tombstone(key="k", deleted_at=1.0)
    assert t.deleted is True


def test_tombstone_age_increases():
    t = Tombstone(key="k", deleted_at=time.monotonic() - 5.0)
    assert t.age >= 5.0


def test_tombstone_immutable():
    t = Tombstone(key="k", deleted_at=1.0)
    with pytest.raises(AttributeError):
        t.key = "other"  # type: ignore[misc]


def test_tombstone_reason_default_empty():
    t = Tombstone(key="k", deleted_at=1.0)
    assert t.reason == ""


# ---------------------------------------------------------------------------
# TombstoneStore — mark & check
# ---------------------------------------------------------------------------


def test_empty_store_check_false():
    s = TombstoneStore()
    assert s.check("anything") is False


def test_mark_and_check():
    s = TombstoneStore()
    s.mark("user:1")
    assert s.check("user:1") is True


def test_mark_returns_tombstone():
    s = TombstoneStore()
    result = s.mark("user:1", reason="test deletion")
    assert isinstance(result, Tombstone)
    assert result.key == "user:1"
    assert result.reason == "test deletion"


def test_mark_with_explicit_timestamp():
    s = TombstoneStore()
    s.mark("user:1", deleted_at=100.0)
    entry = s.peek("user:1")
    assert entry is not None
    assert entry.deleted_at == 100.0


def test_mark_overwrites_newer():
    s = TombstoneStore()
    s.mark("user:1", deleted_at=10.0)
    s.mark("user:1", deleted_at=20.0)
    entry = s.peek("user:1")
    assert entry is not None
    assert entry.deleted_at == 20.0


def test_mark_keeps_existing_if_newer():
    s = TombstoneStore()
    s.mark("user:1", deleted_at=20.0)
    result = s.mark("user:1", deleted_at=10.0)  # older — should be ignored
    entry = s.peek("user:1")
    assert entry is not None
    assert entry.deleted_at == 20.0
    assert result.deleted_at == 20.0  # returns existing


# ---------------------------------------------------------------------------
# peek & unmark
# ---------------------------------------------------------------------------


def test_peek_missing_returns_none():
    s = TombstoneStore()
    assert s.peek("ghost") is None


def test_peek_returns_entry():
    s = TombstoneStore()
    s.mark("k", reason="bye")
    entry = s.peek("k")
    assert entry is not None
    assert entry.reason == "bye"


def test_unmark_existing():
    s = TombstoneStore()
    s.mark("k")
    assert s.unmark("k") is True
    assert s.check("k") is False


def test_unmark_missing():
    s = TombstoneStore()
    assert s.unmark("ghost") is False


# ---------------------------------------------------------------------------
# TTL behavior
# ---------------------------------------------------------------------------


def test_ttl_zero_means_no_expiry():
    s = TombstoneStore(ttl=0)
    s.mark("k", deleted_at=0.0)  # ancient
    # With ttl=0, check never expires based on age
    assert s.check("k") is True


def test_ttl_expires_old_entries():
    s = TombstoneStore(ttl=10)
    # Use a fake clock that returns a fixed value for mark, then advances
    fake_now = [100.0]
    s.clock = lambda: fake_now[0]

    s.mark("k")  # marked at 100.0
    fake_now[0] = 105.0  # 5s later — still alive
    assert s.check("k") is True
    fake_now[0] = 115.0  # 15s later — expired
    assert s.check("k") is False


def test_ttl_boundary_exact():
    s = TombstoneStore(ttl=10)
    fake_now = [100.0]
    s.clock = lambda: fake_now[0]

    s.mark("k")  # at 100.0
    fake_now[0] = 110.0  # exactly at ttl — age == ttl, not > ttl
    assert s.check("k") is True
    fake_now[0] = 110.1  # just past ttl
    assert s.check("k") is False


# ---------------------------------------------------------------------------
# __contains__ and __len__
# ---------------------------------------------------------------------------


def test_contains_uses_check():
    s = TombstoneStore(ttl=10)
    fake_now = [100.0]
    s.clock = lambda: fake_now[0]

    s.mark("k")
    assert "k" in s
    fake_now[0] = 200.0
    assert "k" not in s  # expired


def test_len_counts_all_including_expired():
    s = TombstoneStore(ttl=1)
    s.mark("a", deleted_at=0.0)
    s.mark("b", deleted_at=0.0)
    assert len(s) == 2  # both present even if expired


# ---------------------------------------------------------------------------
# keys iteration
# ---------------------------------------------------------------------------


def test_keys_empty():
    s = TombstoneStore()
    assert list(s.keys()) == []


def test_keys_returns_all():
    s = TombstoneStore()
    s.mark("a")
    s.mark("b")
    s.mark("c")
    assert sorted(s.keys()) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


def test_compact_with_explicit_before():
    s = TombstoneStore()
    s.mark("a", deleted_at=1.0)
    s.mark("b", deleted_at=5.0)
    s.mark("c", deleted_at=10.0)
    removed = s.compact(before=6.0)
    assert removed == 2
    assert list(s.keys()) == ["c"]


def test_compact_with_ttl():
    s = TombstoneStore(ttl=10)
    fake_now = [100.0]
    s.clock = lambda: fake_now[0]

    s.mark("a")  # at 100.0
    fake_now[0] = 105.0
    s.mark("b")  # at 105.0
    fake_now[0] = 115.0

    # compact with no argument uses now - ttl = 115 - 10 = 105
    # "a" at 100.0 < 105 → purged; "b" at 105.0 is not < 105 → kept
    removed = s.compact()
    assert removed == 1
    assert "b" in list(s.keys())


def test_compact_no_ttl_no_before_returns_zero():
    s = TombstoneStore(ttl=0)
    s.mark("a", deleted_at=0.0)
    assert s.compact() == 0


def test_compact_empty_store():
    s = TombstoneStore()
    assert s.compact(before=999.0) == 0


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


def test_merge_disjoint_keys():
    a = TombstoneStore()
    b = TombstoneStore()
    a.mark("x", deleted_at=1.0)
    b.mark("y", deleted_at=2.0)

    merged = a.merge(b)
    assert merged == 1
    assert a.check("y") is True


def test_merge_last_write_wins():
    a = TombstoneStore()
    b = TombstoneStore()
    a.mark("x", deleted_at=10.0)
    b.mark("x", deleted_at=20.0)

    merged = a.merge(b)
    assert merged == 1
    entry = a.peek("x")
    assert entry is not None
    assert entry.deleted_at == 20.0


def test_merge_ignores_older():
    a = TombstoneStore()
    b = TombstoneStore()
    a.mark("x", deleted_at=20.0)
    b.mark("x", deleted_at=10.0)

    merged = a.merge(b)
    assert merged == 0
    entry = a.peek("x")
    assert entry is not None
    assert entry.deleted_at == 20.0


def test_merge_multiple_keys():
    a = TombstoneStore()
    b = TombstoneStore()
    a.mark("x", deleted_at=1.0)
    b.mark("x", deleted_at=2.0)  # newer
    b.mark("y", deleted_at=3.0)  # new
    b.mark("z", deleted_at=0.5)  # will be added

    merged = a.merge(b)
    assert merged == 3
    assert len(a) == 3


def test_merge_empty_into_empty():
    a = TombstoneStore()
    b = TombstoneStore()
    assert a.merge(b) == 0


def test_merge_preserves_reason():
    a = TombstoneStore()
    b = TombstoneStore()
    b.mark("x", deleted_at=1.0, reason="user requested")
    a.merge(b)
    assert a.peek("x").reason == "user requested"


# ---------------------------------------------------------------------------
# summary & repr
# ---------------------------------------------------------------------------


def test_summary_empty():
    s = TombstoneStore(ttl=30)
    info = s.summary()
    assert info["count"] == 0
    assert info["oldest_age"] == 0.0
    assert info["ttl"] == 30


def test_summary_with_entries():
    s = TombstoneStore()
    fake_now = [100.0]
    s.clock = lambda: fake_now[0]

    s.mark("a")  # at 100.0
    fake_now[0] = 105.0
    s.mark("b")  # at 105.0
    fake_now[0] = 110.0

    info = s.summary()
    assert info["count"] == 2
    assert info["oldest_age"] == pytest.approx(10.0, abs=0.1)  # a: 110-100
    assert info["newest_age"] == pytest.approx(5.0, abs=0.1)  # b: 110-105


def test_repr():
    s = TombstoneStore(ttl=60)
    s.mark("a")
    s.mark("b")
    r = repr(s)
    assert "count=2" in r
    assert "ttl=60" in r


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_mark_same_key_same_timestamp():
    s = TombstoneStore()
    s.mark("k", deleted_at=10.0, reason="first")
    result = s.mark("k", deleted_at=10.0, reason="second")
    # Equal timestamp → keep existing
    assert result.reason == "first"


def test_compact_preserves_exactly_at_boundary():
    s = TombstoneStore()
    s.mark("a", deleted_at=5.0)
    # compact(before=5.0) should NOT purge entry at exactly 5.0
    removed = s.compact(before=5.0)
    assert removed == 0
    assert s.check("a") is True


def test_large_batch():
    s = TombstoneStore()
    for i in range(1000):
        s.mark(f"key:{i}", deleted_at=float(i))
    assert len(s) == 1000
    removed = s.compact(before=500.0)
    assert removed == 500
    assert len(s) == 500
