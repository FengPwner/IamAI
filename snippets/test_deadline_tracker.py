#!/usr/bin/env python3
"""Tests for deadline_tracker.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deadline_tracker import DeadlineTracker


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_tracker(t: float = 0.0):
    """Return a tracker whose clock we can advance."""
    state = {"t": t}
    dt = DeadlineTracker(now=lambda: state["t"])
    return dt, state


# ---------------------------------------------------------------------------
# basic state transitions
# ---------------------------------------------------------------------------

def test_ok_before_soft():
    dt, s = _make_tracker(50.0)
    dt.add("task", soft=100.0, grace=10.0)
    assert dt.check("task") == "ok"


def test_soft_between_soft_and_hard():
    dt, s = _make_tracker(100.0)
    dt.add("task", soft=100.0, grace=10.0)
    assert dt.check("task") == "soft"

    s["t"] = 105.0
    assert dt.check("task") == "soft"

    s["t"] = 109.99
    assert dt.check("task") == "soft"


def test_hard_past_grace():
    dt, s = _make_tracker(110.0)
    dt.add("task", soft=100.0, grace=10.0)
    assert dt.check("task") == "hard"

    s["t"] = 200.0
    assert dt.check("task") == "hard"


def test_complete_overrides_time():
    dt, s = _make_tracker(105.0)
    dt.add("task", soft=100.0, grace=10.0)
    assert dt.check("task") == "soft"

    dt.complete("task")
    assert dt.check("task") == "done"

    # Even past hard, done takes precedence
    s["t"] = 999.0
    assert dt.check("task") == "done"


def test_zero_grace_hard_equals_soft():
    dt, s = _make_tracker(100.0)
    dt.add("task", soft=100.0, grace=0.0)
    # At exactly soft, with grace=0 -> hard == soft -> "hard"
    assert dt.check("task") == "hard"


def test_negative_grace_raises():
    dt, _ = _make_tracker()
    try:
        dt.add("task", soft=100.0, grace=-1.0)
        assert False, "should have raised"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# remaining()
# ---------------------------------------------------------------------------

def test_remaining_before_hard():
    dt, s = _make_tracker(95.0)
    dt.add("task", soft=100.0, grace=10.0)
    assert dt.remaining("task") == 15.0  # hard=110, now=95


def test_remaining_past_hard():
    dt, s = _make_tracker(120.0)
    dt.add("task", soft=100.0, grace=10.0)
    assert dt.remaining("task") == -10.0


def test_remaining_completed():
    dt, s = _make_tracker(120.0)
    dt.add("task", soft=100.0, grace=10.0)
    dt.complete("task")
    assert dt.remaining("task") == float("inf")


# ---------------------------------------------------------------------------
# overdue() and approaching()
# ---------------------------------------------------------------------------

def test_overdue_lists_hard_deadlines():
    dt, s = _make_tracker(115.0)
    dt.add("a", soft=100.0, grace=10.0)  # hard=110 -> overdue
    dt.add("b", soft=100.0, grace=20.0)  # hard=120 -> not overdue
    dt.add("c", soft=90.0, grace=5.0)    # hard=95 -> overdue

    overdue = dt.overdue()
    assert "a" in overdue
    assert "c" in overdue
    assert "b" not in overdue


def test_overdue_excludes_completed():
    dt, s = _make_tracker(115.0)
    dt.add("a", soft=100.0, grace=10.0)
    dt.complete("a")
    assert dt.overdue() == []


def test_approaching_within_window():
    dt, s = _make_tracker(105.0)
    dt.add("a", soft=100.0, grace=10.0)  # hard=110, 5s away
    dt.add("b", soft=100.0, grace=30.0)  # hard=130, 25s away

    assert "a" in dt.approaching(within=10.0)
    assert "b" not in dt.approaching(within=10.0)
    assert "b" in dt.approaching(within=30.0)


def test_approaching_excludes_past_hard():
    dt, s = _make_tracker(115.0)
    dt.add("a", soft=100.0, grace=10.0)  # hard=110 -> past
    assert dt.approaching(within=100.0) == []


# ---------------------------------------------------------------------------
# remove() and names()
# ---------------------------------------------------------------------------

def test_remove_deadline():
    dt, _ = _make_tracker()
    dt.add("a", soft=100.0)
    dt.add("b", soft=200.0)
    dt.remove("a")
    assert dt.names() == ["b"]
    try:
        dt.check("a")
        assert False, "should have raised"
    except KeyError:
        pass


def test_names_returns_all():
    dt, _ = _make_tracker()
    dt.add("x", soft=10.0)
    dt.add("y", soft=20.0)
    dt.add("z", soft=30.0)
    assert set(dt.names()) == {"x", "y", "z"}


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

def test_summary_all_states():
    dt, s = _make_tracker(105.0)
    dt.add("ok_task", soft=200.0, grace=5.0)
    dt.add("soft_task", soft=100.0, grace=10.0)  # soft=100, hard=110
    dt.add("hard_task", soft=80.0, grace=10.0)    # soft=80, hard=90
    dt.add("done_task", soft=50.0, grace=5.0)
    dt.complete("done_task")

    s["t"] = 105.0
    summary = dt.summary()

    assert summary["ok_task"]["state"] == "ok"
    assert summary["soft_task"]["state"] == "soft"
    assert summary["hard_task"]["state"] == "hard"
    assert summary["done_task"]["state"] == "done"

    assert summary["ok_task"]["remaining"] == 100.0  # hard=205, now=105
    assert summary["soft_task"]["remaining"] == 5.0   # hard=110, now=105
    assert summary["hard_task"]["remaining"] == -15.0  # hard=90, now=105
    assert summary["done_task"]["remaining"] == float("inf")


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

def test_check_nonexistent_raises():
    dt, _ = _make_tracker()
    try:
        dt.check("nope")
        assert False, "should have raised"
    except KeyError:
        pass


def test_multiple_deadlines_independent():
    dt, s = _make_tracker(50.0)
    dt.add("a", soft=100.0, grace=10.0)
    dt.add("b", soft=40.0, grace=5.0)

    assert dt.check("a") == "ok"
    assert dt.check("b") == "hard"  # past hard (45)

    dt.complete("b")
    assert dt.check("a") == "ok"
    assert dt.check("b") == "done"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect
    passed = failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
            except Exception as e:
                print(f"FAIL {name}: {e}")
                failed += 1
    print(f"{passed} passed, {failed} failed, {passed + failed} total")
    sys.exit(1 if failed else 0)
