"""Tests for snippets/sentinel.py — edge detector for boolean probes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from sentinel import Sentinel  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_initial_state_is_armed():
    s = Sentinel(probe=lambda: False)
    assert s.triggered is False
    assert s.fire_count == 0
    assert "armed" in repr(s)


# ---------------------------------------------------------------------------
# check — no fire while probe is False
# ---------------------------------------------------------------------------


def test_check_returns_probe_result():
    s = Sentinel(probe=lambda: False)
    assert s.check() is False

    s2 = Sentinel(probe=lambda: True)
    assert s2.check() is True


def test_no_fire_when_probe_stays_false():
    fired = []
    s = Sentinel(probe=lambda: False, on_fire=lambda: fired.append(1))
    for _ in range(10):
        s.check()
    assert fired == []
    assert s.fire_count == 0


# ---------------------------------------------------------------------------
# check — fires exactly once on rising edge
# ---------------------------------------------------------------------------


def test_fires_once_on_true():
    count = []
    s = Sentinel(probe=lambda: True, on_fire=lambda: count.append(1))
    s.check()
    s.check()
    s.check()
    assert len(count) == 1
    assert s.fire_count == 1


def test_triggered_after_fire():
    s = Sentinel(probe=lambda: True)
    s.check()
    assert s.triggered is True
    assert "triggered" in repr(s)


def test_no_callback_no_crash():
    s = Sentinel(probe=lambda: True)
    assert s.check() is True
    assert s.fire_count == 1


# ---------------------------------------------------------------------------
# rising edge detection — False then True
# ---------------------------------------------------------------------------


def test_rising_edge():
    state = {"v": False}
    s = Sentinel(probe=lambda: state["v"])
    assert s.check() is False
    assert s.triggered is False

    state["v"] = True
    assert s.check() is True
    assert s.triggered is True
    assert s.fire_count == 1


def test_does_not_refire_on_subsequent_true():
    state = {"v": False}
    s = Sentinel(probe=lambda: state["v"])

    state["v"] = True
    s.check()  # fire
    s.check()  # latched
    s.check()  # latched
    assert s.fire_count == 1


# ---------------------------------------------------------------------------
# rearm
# ---------------------------------------------------------------------------


def test_rearm_clears_latch():
    s = Sentinel(probe=lambda: True)
    s.check()
    assert s.triggered is True

    s.rearm()
    assert s.triggered is False
    assert "armed" in repr(s)


def test_rearm_allows_refire():
    count = []
    s = Sentinel(probe=lambda: True, on_fire=lambda: count.append(1))

    s.check()
    assert len(count) == 1
    s.check()
    assert len(count) == 1  # still latched

    s.rearm()
    s.check()
    assert len(count) == 2
    assert s.fire_count == 2


def test_rearm_when_already_armed_is_noop():
    s = Sentinel(probe=lambda: False)
    s.rearm()
    s.rearm()
    assert s.triggered is False
    assert s.fire_count == 0


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_armed():
    s = Sentinel(probe=lambda: False)
    assert "armed" in repr(s)
    assert "fires=0" in repr(s)


def test_repr_triggered():
    s = Sentinel(probe=lambda: True)
    s.check()
    assert "triggered" in repr(s)
    assert "fires=1" in repr(s)


# ---------------------------------------------------------------------------
# realistic scenario: writer death detection
# ---------------------------------------------------------------------------


def test_writer_death_detection():
    """Simulate detecting a writer process death across poll cycles."""
    alive = {"v": True}
    restarts = []

    s = Sentinel(
        probe=lambda: not alive["v"],  # fires when process is dead
        on_fire=lambda: restarts.append("restart"),
    )

    # poll 1-3: writer alive
    for _ in range(3):
        s.check()
    assert s.fire_count == 0
    assert restarts == []

    # poll 4: writer dies
    alive["v"] = False
    s.check()
    assert restarts == ["restart"]

    # poll 5-6: writer still dead, but sentinel latched — no double restart
    s.check()
    s.check()
    assert restarts == ["restart"]  # still just one

    # operator restarts the writer and rearms the sentinel
    alive["v"] = True
    s.rearm()

    # poll 7: writer alive, sentinel armed and ready
    s.check()
    assert s.fire_count == 1  # no new fire

    # poll 8: writer dies again
    alive["v"] = False
    s.check()
    assert restarts == ["restart", "restart"]
    assert s.fire_count == 2
