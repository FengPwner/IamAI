"""Tests for snippets/dispatch_dampener.py — rate-limit supervisor recovery actions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from dispatch_dampener import (  # noqa: E402
    DampenerVerdict,
    DispatchDampener,
    SuppressionRecord,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_dampener(cooldown=60.0, max_burst=3, start=1000.0):
    """Build a dampener with a controllable clock."""
    counter = {"t": start}

    def clock():
        return counter["t"]

    d = DispatchDampener(cooldown=cooldown, max_burst=max_burst, clock=clock)
    return d, counter


def _advance(counter, seconds):
    counter["t"] += seconds


# ---------------------------------------------------------------------------
# DampenerVerdict
# ---------------------------------------------------------------------------


def test_verdict_allowed_is_truthy():
    v = DampenerVerdict("restart", allowed=True)
    assert bool(v) is True


def test_verdict_suppressed_is_falsy():
    v = DampenerVerdict("restart", allowed=False, suppressed_consecutive=2)
    assert bool(v) is False


def test_verdict_frozen():
    v = DampenerVerdict("restart", allowed=True)
    with pytest.raises(AttributeError):
        v.allowed = False  # type: ignore[misc]


def test_verdict_default_detail_empty():
    v = DampenerVerdict("restart", allowed=True)
    assert v.detail == ""


# ---------------------------------------------------------------------------
# construction & validation
# ---------------------------------------------------------------------------


def test_default_construction():
    d = DispatchDampener()
    assert d.cooldown == 300.0
    assert d.max_burst == 3
    assert d.suppressed_count == 0
    assert d.allowed_count == 0
    assert d.tracked_labels == []
    assert d.suppressions == []


def test_custom_construction():
    d = DispatchDampener(cooldown=120.0, max_burst=5)
    assert d.cooldown == 120.0
    assert d.max_burst == 5


def test_cooldown_zero_raises():
    with pytest.raises(ValueError, match="cooldown must be positive"):
        DispatchDampener(cooldown=0)


def test_cooldown_negative_raises():
    with pytest.raises(ValueError, match="cooldown must be positive"):
        DispatchDampener(cooldown=-1)


def test_max_burst_zero_raises():
    with pytest.raises(ValueError, match="max_burst must be >= 1"):
        DispatchDampener(max_burst=0)


# ---------------------------------------------------------------------------
# allow — basic
# ---------------------------------------------------------------------------


def test_allow_first_is_true():
    d, _ = _make_dampener()
    assert d.allow("restart") is True


def test_allow_within_burst():
    d, _ = _make_dampener(max_burst=3)
    assert d.allow("restart") is True
    assert d.allow("restart") is True
    assert d.allow("restart") is True


def test_allow_exceeds_burst_suppresses():
    d, _ = _make_dampener(max_burst=2)
    assert d.allow("restart") is True
    assert d.allow("restart") is True
    assert d.allow("restart") is False


def test_allow_burst_one():
    d, _ = _make_dampener(max_burst=1)
    assert d.allow("restart") is True
    assert d.allow("restart") is False
    assert d.allow("restart") is False


# ---------------------------------------------------------------------------
# allow — window expiry
# ---------------------------------------------------------------------------


def test_allow_after_cooldown_expires():
    d, c = _make_dampener(cooldown=60.0, max_burst=2)
    assert d.allow("restart") is True
    assert d.allow("restart") is True
    assert d.allow("restart") is False
    _advance(c, 61)
    assert d.allow("restart") is True


def test_allow_partial_window_expiry():
    """Only the oldest entry expires; the newer one stays."""
    d, c = _make_dampener(cooldown=60.0, max_burst=2)
    d.allow("restart")       # t=1000
    _advance(c, 30)
    d.allow("restart")       # t=1030
    assert d.allow("restart") is False  # t=1030, burst=2 full

    _advance(c, 31)          # t=1061: first entry (t=1000) expires
    assert d.allow("restart") is True   # t=1061: one slot free


# ---------------------------------------------------------------------------
# allow — per-label independence
# ---------------------------------------------------------------------------


def test_different_labels_independent():
    d, _ = _make_dampener(max_burst=2)
    assert d.allow("restart") is True
    assert d.allow("restart") is True
    assert d.allow("restart") is False

    # page_oncall is independent
    assert d.allow("page_oncall") is True
    assert d.allow("page_oncall") is True
    assert d.allow("page_oncall") is False


def test_tracked_labels_sorted():
    d, _ = _make_dampener()
    d.allow("zebra")
    d.allow("alpha")
    d.allow("middle")
    assert d.tracked_labels == ["alpha", "middle", "zebra"]


# ---------------------------------------------------------------------------
# counts
# ---------------------------------------------------------------------------


def test_allowed_count():
    d, _ = _make_dampener(max_burst=2)
    d.allow("restart")
    d.allow("restart")
    d.allow("restart")  # suppressed
    assert d.allowed_count == 2
    assert d.suppressed_count == 1


def test_suppressed_count_across_labels():
    d, _ = _make_dampener(max_burst=1)
    d.allow("a")   # allowed
    d.allow("a")   # suppressed
    d.allow("b")   # allowed
    d.allow("b")   # suppressed
    assert d.allowed_count == 2
    assert d.suppressed_count == 2


# ---------------------------------------------------------------------------
# suppressions
# ---------------------------------------------------------------------------


def test_suppression_record_created():
    d, c = _make_dampener(cooldown=60.0, max_burst=1)
    d.allow("restart")
    d.allow("restart")  # suppressed
    recs = d.suppressions
    assert len(recs) == 1
    assert recs[0].label == "restart"
    assert recs[0].consecutive == 1
    assert recs[0].window_remaining > 0


def test_suppression_consecutive_increments():
    d, _ = _make_dampener(max_burst=1)
    d.allow("restart")
    d.allow("restart")  # suppressed, consecutive=1
    d.allow("restart")  # suppressed, consecutive=2
    d.allow("restart")  # suppressed, consecutive=3
    recs = d.suppressions
    assert [r.consecutive for r in recs] == [1, 2, 3]


def test_suppression_consecutive_resets_on_allow():
    d, c = _make_dampener(cooldown=60.0, max_burst=1)
    d.allow("restart")
    d.allow("restart")  # suppressed, consecutive=1
    _advance(c, 61)
    d.allow("restart")  # allowed, streak resets
    d.allow("restart")  # suppressed, consecutive=1 again
    recs = d.suppressions
    assert [r.consecutive for r in recs] == [1, 1]


def test_suppression_window_remaining():
    d, c = _make_dampener(cooldown=60.0, max_burst=1)
    d.allow("restart")       # t=1000
    _advance(c, 20)
    d.allow("restart")       # t=1020, suppressed, remaining ≈ 40
    rec = d.suppressions[0]
    assert 39.0 <= rec.window_remaining <= 41.0


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------


def test_guard_allowed_calls_dispatch():
    d, _ = _make_dampener()
    calls = []
    verdict = d.guard("restart", lambda: calls.append("fired"))
    assert verdict.allowed is True
    assert calls == ["fired"]


def test_guard_suppressed_skips_dispatch():
    d, _ = _make_dampener(max_burst=1)
    d.allow("restart")  # fill the slot
    calls = []
    verdict = d.guard("restart", lambda: calls.append("fired"))
    assert verdict.allowed is False
    assert calls == []
    assert verdict.suppressed_consecutive == 1


def test_guard_returns_verdict_with_label():
    d, _ = _make_dampener(max_burst=1)
    v = d.guard("page_oncall", lambda: None)
    assert v.label == "page_oncall"
    assert v.allowed is True


def test_guard_suppressed_detail_includes_consecutive():
    d, _ = _make_dampener(max_burst=1)
    d.allow("restart")
    v = d.guard("restart", lambda: None)
    assert "1 consecutive" in v.detail


# ---------------------------------------------------------------------------
# time_until_next
# ---------------------------------------------------------------------------


def test_time_until_next_no_history():
    d, _ = _make_dampener()
    assert d.time_until_next("restart") == 0.0


def test_time_until_next_within_burst():
    d, _ = _make_dampener(max_burst=3)
    d.allow("restart")
    assert d.time_until_next("restart") == 0.0


def test_time_until_next_burst_full():
    d, c = _make_dampener(cooldown=60.0, max_burst=1)
    d.allow("restart")       # t=1000
    _advance(c, 20)
    remaining = d.time_until_next("restart")
    assert 39.0 <= remaining <= 41.0


def test_time_until_next_after_expiry():
    d, c = _make_dampener(cooldown=60.0, max_burst=1)
    d.allow("restart")
    _advance(c, 61)
    assert d.time_until_next("restart") == 0.0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_all():
    d, _ = _make_dampener(max_burst=1)
    d.allow("a")
    d.allow("a")  # suppressed
    d.allow("b")
    d.reset()
    assert d.allowed_count == 0
    assert d.suppressed_count == 0
    assert d.tracked_labels == []
    assert d.suppressions == []
    # can allow again
    assert d.allow("a") is True


def test_reset_single_label():
    d, _ = _make_dampener(max_burst=1)
    d.allow("a")
    d.allow("b")
    d.reset("a")
    assert d.allow("a") is True   # cleared
    assert d.allow("b") is False  # still full


# ---------------------------------------------------------------------------
# summary & repr
# ---------------------------------------------------------------------------


def test_summary():
    d, _ = _make_dampener(max_burst=2)
    d.allow("restart")
    d.allow("restart")
    d.allow("restart")  # suppressed
    d.allow("page")
    s = d.summary()
    assert s["labels"] == 2
    assert s["allowed"] == 3
    assert s["suppressed"] == 1


def test_repr():
    d, _ = _make_dampener(cooldown=120.0, max_burst=5)
    r = repr(d)
    assert "120" in r
    assert "max_burst=5" in r
    assert "allowed=0" in r
    assert "suppressed=0" in r


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_empty_label_allowed():
    """Empty string is a valid label (though not recommended)."""
    d, _ = _make_dampener()
    assert d.allow("") is True


def test_many_labels():
    d, _ = _make_dampener(max_burst=1)
    for i in range(100):
        assert d.allow(f"label_{i}") is True
    assert len(d.tracked_labels) == 100


def test_burst_with_mixed_labels():
    d, _ = _make_dampener(max_burst=2)
    assert d.allow("a") is True
    assert d.allow("b") is True
    assert d.allow("a") is True
    assert d.allow("b") is True
    assert d.allow("a") is False
    assert d.allow("b") is False


def test_rapid_successions():
    """Many calls at the same timestamp."""
    d, _ = _make_dampener(cooldown=60.0, max_burst=5)
    results = [d.allow("x") for _ in range(20)]
    assert results[:5] == [True] * 5
    assert results[5:] == [False] * 15
    assert d.allowed_count == 5
    assert d.suppressed_count == 15


def test_cooldown_boundary_exact():
    """Exactly at cooldown boundary: entry at t=1000 with cooldown=60.

    At t=1060 the entry is exactly 60s old. cutoff = 1060 - 60 = 1000.
    The prune condition is `window[0] <= cutoff`, so the entry at 1000
    IS pruned (<=). The slot is free.
    """
    d, c = _make_dampener(cooldown=60.0, max_burst=1)
    d.allow("restart")       # t=1000
    _advance(c, 60)          # t=1060
    assert d.allow("restart") is True  # entry at 1000 pruned


def test_suppression_record_is_frozen():
    rec = SuppressionRecord("x", 100.0, 1, 30.0)
    with pytest.raises(AttributeError):
        rec.label = "y"  # type: ignore[misc]


def test_guard_dispatch_exception_propagates():
    """If dispatch_fn raises, the exception propagates — dampener doesn't eat it."""
    d, _ = _make_dampener()

    def boom():
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        d.guard("restart", boom)

    # the allow was consumed (the dispatch was "allowed")
    assert d.allowed_count == 1
